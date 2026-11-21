"""Build a free-first NBA player roster and game-log archive from ESPN public endpoints."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster"
GAMELOG_URL = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{athlete_id}/gamelog"
TIMEOUT = 25
DELAY = float(os.getenv("NBA_HISTORY_REQUEST_DELAY", "0.8"))
SEASONS = [int(x) for x in os.getenv("NBA_HISTORY_SEASONS", "2027,2026").split(",") if x.strip()]
TEAM_IDS = {
    "ATL": 1, "BOS": 2, "NOP": 3, "CHI": 4, "CLE": 5, "DAL": 6,
    "DEN": 7, "DET": 8, "GSW": 9, "HOU": 10, "IND": 11, "LAC": 12,
    "LAL": 13, "MIA": 14, "MIL": 15, "MIN": 16, "BKN": 17, "NYK": 18,
    "ORL": 19, "PHI": 20, "PHX": 21, "POR": 22, "SAC": 23, "SAS": 24,
    "OKC": 25, "UTA": 26, "WAS": 27, "TOR": 28, "MEM": 29, "CHA": 30,
}


def get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    last_error = None
    for attempt in range(4):
        try:
            response = requests.get(
                url, params=params, timeout=TIMEOUT,
                headers={"User-Agent": "NBA-Simulator/0.1", "Accept": "application/json"},
            )
            if response.status_code == 429 or response.status_code >= 500:
                wait = float(response.headers.get("Retry-After", 2 ** attempt))
                time.sleep(min(wait, 30))
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
    raise RuntimeError("Unable to retrieve ESPN response")


def flatten_roster(payload: dict[str, Any]) -> list[dict[str, Any]]:
    athletes = payload.get("athletes") or []
    players: list[dict[str, Any]] = []
    for entry in athletes:
        if isinstance(entry, dict) and isinstance(entry.get("items"), list):
            players.extend(item for item in entry["items"] if isinstance(item, dict))
        elif isinstance(entry, dict):
            players.append(entry)
    return players


def _number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def parse_player_gamelog(payload: dict[str, Any]) -> list[dict[str, Any]]:
    names = list(payload.get("names") or [])
    labels = list(payload.get("labels") or [])
    events = payload.get("events") or []
    rows = []
    for event in events:
        values = list(event.get("stats") or [])
        stat_names = names
        if len(stat_names) == len(values) + 3:
            stat_names = stat_names[3:]
        elif len(stat_names) != len(values):
            stat_names = labels[3:] if len(labels) == len(values) + 3 else labels
        raw = dict(zip(stat_names, values))
        def pick(*keys: str) -> float | None:
            for key in keys:
                if key in raw:
                    return _number(raw[key])
            return None
        opponent = event.get("opponent") or {}
        rows.append({
            "event_id": str(event.get("id") or ""),
            "date": event.get("date"),
            "opponent": opponent.get("displayName") or opponent.get("abbreviation"),
            "opponent_abbreviation": opponent.get("abbreviation"),
            "result": event.get("gameResult"),
            "minutes": pick("minutes", "min"),
            "points": pick("points", "pts"),
            "rebounds": pick("rebounds", "reb"),
            "assists": pick("assists", "ast"),
            "steals": pick("steals", "stl"),
            "blocks": pick("blocks", "blk"),
            "raw_stats": values,
        })
    return rows


def fetch_player_database() -> list[dict[str, Any]]:
    players_by_id: dict[str, dict[str, Any]] = {}
    for abbreviation, team_id in TEAM_IDS.items():
        try:
            roster_payload = get_json(ROSTER_URL.format(team_id=team_id), {"season": max(SEASONS)})
        except requests.RequestException as exc:
            print(f"Roster unavailable for {abbreviation}: {exc}")
            continue
        for athlete in flatten_roster(roster_payload):
            athlete_id = str(athlete.get("id") or "")
            if not athlete_id:
                continue
            status = athlete.get("status") or {}
            if status.get("type") and status.get("type") not in ("active", "day-to-day", "injured"):
                continue
            player = players_by_id.setdefault(athlete_id, {
                "id": athlete_id,
                "name": athlete.get("displayName") or athlete.get("fullName"),
                "team": abbreviation,
                "position": (athlete.get("position") or {}).get("abbreviation"),
                "jersey": athlete.get("jersey"),
                "status": status.get("name") or "Rostered",
                "seasons": {},
                "source": "ESPN",
            })
            for season in SEASONS:
                try:
                    payload = get_json(GAMELOG_URL.format(athlete_id=athlete_id), {"season": season})
                    player["seasons"][str(season)] = parse_player_gamelog(payload)
                except requests.RequestException as exc:
                    print(f"Game log unavailable for {player['name']} ({season}): {exc}")
                    player["seasons"][str(season)] = []
    return sorted(players_by_id.values(), key=lambda p: (p["team"], p["name"] or ""))


def main() -> None:
    players = fetch_player_database()
    if len(players) < 100:
        raise RuntimeError(f"Only {len(players)} player records retrieved; refusing to overwrite the existing archive.")
    DATA.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "source": "ESPN public roster and athlete game-log endpoints",
        "seasons": SEASONS,
        "player_count": len(players),
        "players": players,
    }
    (DATA / "players.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Saved {len(players)} NBA player records across seasons {SEASONS}.")


if __name__ == "__main__":
    main()
