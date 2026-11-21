"""Build team season and recent-form data from ESPN public team schedules.

Scheduled daily on the default branch; supports manual workflow dispatch.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/schedule"
TIMEOUT = 25
DELAY = 0.35
SEASONS = [2027, 2026]
TEAM_IDS = {
    "ATL": 1, "BOS": 2, "NOP": 3, "CHI": 4, "CLE": 5, "DAL": 6,
    "DEN": 7, "DET": 8, "GSW": 9, "HOU": 10, "IND": 11, "LAC": 12,
    "LAL": 13, "MIA": 14, "MIL": 15, "MIN": 16, "BKN": 17, "NYK": 18,
    "ORL": 19, "PHI": 20, "PHX": 21, "POR": 22, "SAC": 23, "SAS": 24,
    "OKC": 25, "UTA": 26, "WAS": 27, "TOR": 28, "MEM": 29, "CHA": 30,
}
ID_TO_TEAM = {str(team_id): abbr for abbr, team_id in TEAM_IDS.items()}


def get_json(url: str, params: dict[str, Any]) -> Any:
    last_error = None
    for attempt in range(4):
        try:
            response = requests.get(url, params=params, timeout=TIMEOUT, headers={"User-Agent": "NBA-Simulator/0.1"})
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 3:
                    response.raise_for_status()
                time.sleep(min(float(response.headers.get("Retry-After", 2 ** attempt)), 30))
                continue
            response.raise_for_status()
            time.sleep(DELAY)
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    if last_error:
        raise last_error
    raise RuntimeError("Unable to retrieve ESPN team schedule")


def _score(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_team_schedule(payload: dict[str, Any], team_id: str) -> list[dict[str, Any]]:
    games = []
    for event in payload.get("events") or []:
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        competition = competitions[0]
        status = (event.get("status") or {}).get("type") or {}
        if not status.get("completed", False) and status.get("state") != "post":
            continue
        competitors = competition.get("competitors") or []
        own = next((c for c in competitors if str((c.get("team") or {}).get("id")) == str(team_id)), None)
        other = next((c for c in competitors if c is not own), None)
        if not own or not other:
            continue
        team = own.get("team") or {}
        opponent = other.get("team") or {}
        points_for, points_against = _score(own.get("score")), _score(other.get("score"))
        if points_for is None or points_against is None:
            continue
        games.append({
            "game_id": str(event.get("id") or ""),
            "date": event.get("date"),
            "team": ID_TO_TEAM.get(str(team_id), team.get("abbreviation")),
            "opponent": ID_TO_TEAM.get(str(opponent.get("id")), opponent.get("abbreviation")),
            "opponent_name": opponent.get("displayName"),
            "home_away": own.get("homeAway"),
            "points_for": points_for,
            "points_against": points_against,
            "win": points_for > points_against,
            "result": "W" if points_for > points_against else "L",
        })
    return sorted(games, key=lambda game: game.get("date") or "")


def summarize_games(games: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(games, key=lambda game: game.get("date") or "")
    recent = ordered[-10:]
    def mean(rows: list[dict[str, Any]], key: str) -> float | None:
        values = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
        return round(sum(values) / len(values), 2) if values else None
    return {
        "games": len(ordered),
        "wins": sum(1 for game in ordered if game["win"]),
        "win_pct": round(sum(1 for game in ordered if game["win"]) / len(ordered), 4) if ordered else None,
        "avg_points_for": mean(ordered, "points_for"),
        "avg_points_against": mean(ordered, "points_against"),
        "last10_games": len(recent),
        "last10_wins": sum(1 for game in recent if game["win"]),
        "last10_win_pct": round(sum(1 for game in recent if game["win"]) / len(recent), 4) if recent else None,
        "last10_avg_points_for": mean(recent, "points_for"),
        "last10_avg_points_against": mean(recent, "points_against"),
    }


def fetch_team_database() -> list[dict[str, Any]]:
    teams = []
    for abbreviation, team_id in TEAM_IDS.items():
        record = {"id": str(team_id), "abbreviation": abbreviation, "seasons": {}, "source": "ESPN"}
        for season in SEASONS:
            try:
                payload = get_json(URL.format(team_id=team_id), {"season": season})
                games = parse_team_schedule(payload, str(team_id))
                record["seasons"][str(season)] = {"games": games, "summary": summarize_games(games)}
            except requests.RequestException as exc:
                print(f"Team schedule unavailable for {abbreviation} ({season}): {exc}")
                record["seasons"][str(season)] = {"games": [], "summary": summarize_games([])}
        teams.append(record)
    return teams


def main() -> None:
    teams = fetch_team_database()
    valid = sum(1 for team in teams if any(season["summary"]["games"] for season in team["seasons"].values()))
    if valid < 20:
        raise RuntimeError(f"Only {valid} teams returned usable history; refusing to overwrite the existing archive.")
    DATA.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "source": "ESPN public team schedules",
        "seasons": SEASONS,
        "team_count": len(teams),
        "teams": teams,
    }
    (DATA / "teams.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved team history for {valid}/30 NBA teams.")


if __name__ == "__main__":
    main()
