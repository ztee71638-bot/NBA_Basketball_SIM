"""Build team season and recent-form data from ESPN public team schedules.

Scheduled daily on the default branch; supports manual workflow dispatch and preserves the last good archive when collection is incomplete.
"""
from __future__ import annotations

import json
import time
import calendar
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/schedule"
SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
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
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code and 400 <= status_code < 500 and status_code != 429:
                raise
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
        status = (event.get("status") or {}).get("type") or (competition.get("status") or {}).get("type") or {}
        competitors = competition.get("competitors") or []
        # ESPN schedule payloads are inconsistent about where status lives.
        # A completed box score has numeric scores for both competitors, so use
        # that as the final guard rather than silently dropping every game.
        # Ignore scheduled/live games even when ESPN supplies 0-0 placeholders.
        if not status.get("completed", False) and status.get("state") != "post":
            continue
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


def _date_values(start: date, end: date):
    cursor = start
    while cursor <= end:
        yield cursor
        cursor = date.fromordinal(cursor.toordinal() + 1)


def fetch_season_from_scoreboard(season: int) -> dict[str, list[dict[str, Any]]]:
    """Fallback: build team game logs from ESPN's scoreboard date-range feed."""
    today = datetime.now(timezone.utc).date()
    if season == today.year + 1:
        start, end = date(season - 1, 10, 1), today
    else:
        start, end = date(season - 1, 10, 1), date(season, 6, 30)
    grouped: dict[str, list[dict[str, Any]]] = {abbr: [] for abbr in TEAM_IDS}
    for game_date in _date_values(start, end):
        # ESPN's NBA scoreboard accepts single-day dates; range queries return HTTP 400.
        payload = get_json(SCOREBOARD_URL, {"dates": game_date.strftime("%Y%m%d"), "seasontype": 2, "limit": 100})
        for event in payload.get("events") or []:
            competitions = event.get("competitions") or []
            if not competitions:
                continue
            competition = competitions[0]
            status = (event.get("status") or {}).get("type") or {}
            competitors = competition.get("competitors") or []
            # Ignore scheduled/live games even when ESPN supplies 0-0 placeholders.
            if not status.get("completed", False) and status.get("state") != "post":
                continue
            if len(competitors) != 2:
                continue
            for own in competitors:
                own_team = own.get("team") or {}
                own_abbr = ID_TO_TEAM.get(str(own_team.get("id")), own_team.get("abbreviation"))
                if own_abbr not in grouped:
                    continue
                other = next((item for item in competitors if item is not own), None)
                if not other:
                    continue
                other_team = other.get("team") or {}
                pf, pa = _score(own.get("score")), _score(other.get("score"))
                if pf is None or pa is None:
                    continue
                grouped[own_abbr].append({
                    "game_id": str(event.get("id") or ""),
                    "date": event.get("date"),
                    "team": own_abbr,
                    "opponent": ID_TO_TEAM.get(str(other_team.get("id")), other_team.get("abbreviation")),
                    "opponent_name": other_team.get("displayName"),
                    "home_away": own.get("homeAway"),
                    "points_for": pf,
                    "points_against": pa,
                    "win": pf > pa,
                    "result": "W" if pf > pa else "L",
                })
    return {abbr: sorted(rows, key=lambda row: row.get("date") or "") for abbr, rows in grouped.items()}



def _stat_map(team_box: dict[str, Any]) -> dict[str, float]:
    import re
    result: dict[str, float] = {}
    for item in team_box.get("statistics") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("name") or "").lower()
        value = item.get("displayValue", item.get("value"))
        parsed = _score(value)
        if parsed is not None:
            result[key] = parsed
        if key in ("fieldgoalsmade-fieldgoalsattempted", "fieldgoals"):
            match = re.search(r"(?:^|\s)(\d+)\s*[-/]\s*(\d+)", str(value))
            if match:
                result["fieldgoalsattempted"] = float(match.group(2))
        if key in ("freethrowsmade-freethrowsattempted", "freethrows"):
            match = re.search(r"(?:^|\s)(\d+)\s*[-/]\s*(\d+)", str(value))
            if match:
                result["freethrowsattempted"] = float(match.group(2))
    return result


def _possessions(stats: dict[str, float]) -> float | None:
    fga = stats.get("fieldgoalsattempted")
    fta = stats.get("freethrowsattempted")
    turnovers = stats.get("totalturnovers", stats.get("turnovers"))
    offensive_rebounds = stats.get("offensiverebounds")
    if None in (fga, fta, turnovers, offensive_rebounds):
        return None
    estimate = fga - offensive_rebounds + turnovers + 0.44 * fta
    return estimate if estimate > 0 else None


def enrich_team_games_with_boxscores(teams: list[dict[str, Any]]) -> None:
    """Attach estimated possessions and efficiency from completed ESPN boxscores."""
    games: dict[str, list[dict[str, Any]]] = {}
    for team in teams:
        for season_data in team.get("seasons", {}).values():
            for row in season_data.get("games", []):
                if row.get("game_id"):
                    games.setdefault(str(row["game_id"]), []).append(row)
    enriched = 0
    for game_id, rows in games.items():
        if len(rows) != 2 or all(row.get("pace_estimate") for row in rows):
            continue
        try:
            payload = get_json(
                "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary",
                {"event": game_id},
            )
        except requests.RequestException as exc:
            print(f"Boxscore unavailable for {game_id}: {exc}")
            continue
        boxes = (payload.get("boxscore") or {}).get("teams") or []
        by_abbr: dict[str, dict[str, float]] = {}
        for box in boxes:
            team_info = box.get("team") or {}
            abbreviation = team_info.get("abbreviation") or ID_TO_TEAM.get(str(team_info.get("id") or ""))
            if abbreviation:
                by_abbr[str(abbreviation)] = _stat_map(box)
        if len(by_abbr) < 2:
            continue
        first, second = rows
        stats_first, stats_second = by_abbr.get(first.get("team")), by_abbr.get(second.get("team"))
        if not stats_first or not stats_second:
            continue
        poss_first, poss_second = _possessions(stats_first), _possessions(stats_second)
        if not poss_first or not poss_second:
            continue
        pace = (poss_first + poss_second) / 2
        for row, own_poss, opp_poss in ((first, poss_first, poss_second), (second, poss_second, poss_first)):
            row["possessions_estimate"] = round(own_poss, 2)
            row["pace_estimate"] = round(pace, 2)
            row["offensive_rating"] = round(row["points_for"] / own_poss * 100, 2)
            row["defensive_rating"] = round(row["points_against"] / opp_poss * 100, 2)
            row["advanced_stats_source"] = "ESPN boxscore; estimated possessions = FGA - OREB + TO + 0.44*FTA"
        enriched += 1
    print(f"Added pace/efficiency estimates to {enriched} completed games.")


def write_immutable_team_snapshot(teams: list[dict[str, Any]]) -> None:
    snapshot_dir = DATA / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = snapshot_dir / f"team-metrics-{stamp}.json"
    if path.exists():
        print(f"Immutable daily snapshot already exists: {path.name}")
        return
    snapshot = {
        "snapshot_date": stamp,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "ESPN team history and available boxscores",
        "teams": [{
            "abbreviation": team["abbreviation"],
            "seasons": {
                season: {
                    "summary": data.get("summary", {}),
                    "games_with_advanced_metrics": sum(
                        1 for row in data.get("games", []) if row.get("pace_estimate") is not None
                    ),
                }
                for season, data in team.get("seasons", {}).items()
            },
        } for team in teams],
    }
    path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")

def fetch_team_database() -> list[dict[str, Any]]:
    teams = [
        {"id": str(team_id), "abbreviation": abbreviation, "seasons": {}, "source": "ESPN"}
        for abbreviation, team_id in TEAM_IDS.items()
    ]
    # Fetch both the active and previous regular seasons. Keep only completed games.
    grouped_by_season = {
        season: fetch_season_from_scoreboard(season)
        for season in sorted(SEASONS)
    }
    for team in teams:
        for season in sorted(SEASONS):
            rows = grouped_by_season[season].get(team["abbreviation"], [])
            team["seasons"][str(season)] = {"games": rows, "summary": summarize_games(rows)}
    enrich_team_games_with_boxscores(teams)
    for team in teams:
        for season_data in team["seasons"].values():
            season_data["summary"] = summarize_games(season_data.get("games", []))
    return teams


def main() -> None:
    teams = fetch_team_database()
    print("Collected current-season team logs from ESPN daily scoreboard feeds.")
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
    write_immutable_team_snapshot(teams)
    print(f"Saved team history for {valid}/30 NBA teams across seasons {SEASONS}.")


if __name__ == "__main__":
    main()
