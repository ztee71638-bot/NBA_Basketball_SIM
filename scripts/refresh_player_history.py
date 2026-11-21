"""Build a free-first NBA player roster and game-log archive from ESPN public endpoints.

Scheduled daily on the default branch; supports manual workflow dispatch and preserves the last good archive when collection is incomplete.
"""
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
                if attempt == 3:
                    response.raise_for_status()
                wait = float(response.headers.get("Retry-After", 2 ** attempt))
                time.sleep(min(wait, 30))
                continue
            response.raise_for_status()
            time.sleep(DELAY)
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            # Permanent client errors (for example a missing athlete season)
            # should not incur four exponential-backoff retries.
            if status_code and 400 <= status_code < 500 and status_code != 429:
                raise
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
    event_meta = payload.get("events") or {}
    stat_rows: list[dict[str, Any]] = []

    # Current ESPN Web v3 shape: events is an ID->metadata dictionary,
    # while actual per-game stats are nested under seasonTypes/categories.
    if isinstance(event_meta, dict) and payload.get("seasonTypes"):
        for season_type in payload.get("seasonTypes") or []:
            for category in season_type.get("categories") or []:
                for row in category.get("events") or []:
                    if isinstance(row, dict):
                        event_id = str(row.get("eventId") or row.get("id") or "")
                        metadata = event_meta.get(event_id, {})
                        if isinstance(metadata, dict):
                            stat_rows.append({**metadata, **row, "id": event_id})
    else:
        # Compatibility with older/flat ESPN payload variants.
        if isinstance(event_meta, dict):
            candidates = list(event_meta.values())
        elif isinstance(event_meta, list):
            candidates = event_meta
        else:
            candidates = []
        stat_rows.extend(item for item in candidates if isinstance(item, dict))

    rows = []
    seen = set()
    for event in stat_rows:
        event_id = str(event.get("eventId") or event.get("id") or "")
        values = list(event.get("stats") or [])
        if event_id and event_id in seen:
            continue
        if event_id:
            seen.add(event_id)
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
        if not isinstance(opponent, dict):
            opponent = {}
        def pair(*keys: str) -> tuple[float | None, float | None]:
            for key in keys:
                raw_value = raw.get(key)
                if raw_value is None:
                    continue
                import re
                match = re.search(r"(\\d+(?:\\.\\d+)?)\\s*[-/]\\s*(\\d+(?:\\.\\d+)?)", str(raw_value))
                if match:
                    return float(match.group(1)), float(match.group(2))
            return None, None

        fg_made, fg_attempted = pair("field goals", "fg", "FG")
        three_made, three_attempted = pair("3pt", "3PT", "three pointers")
        ft_made, ft_attempted = pair("ft", "FT", "free throws")
        rows.append({
            "event_id": event_id,
            "date": event.get("date") or event.get("gameDate"),
            "opponent": opponent.get("displayName") or opponent.get("name") or opponent.get("abbreviation"),
            "opponent_abbreviation": opponent.get("abbreviation"),
            "result": event.get("gameResult"),
            "minutes": pick("minutes", "min", "MIN"),
            "points": pick("points", "pts", "PTS"),
            "rebounds": pick("rebounds", "reb", "REB"),
            "assists": pick("assists", "ast", "AST"),
            "steals": pick("steals", "stl", "STL"),
            "blocks": pick("blocks", "blk", "BLK"),
            "offensive_rebounds": pick("offensive rebounds", "offensiveRebounds", "OREB"),
            "turnovers": pick("turnovers", "to", "TO"),
            "plus_minus": pick("plus/minus", "+/-", "plusMinus"),
            "field_goals_made": fg_made,
            "field_goals_attempted": fg_attempted,
            "three_pointers_made": three_made,
            "three_pointers_attempted": three_attempted,
            "free_throws_made": ft_made,
            "free_throws_attempted": ft_attempted,
            "raw_stats": values,
        })
    return rows


def fetch_player_database() -> list[dict[str, Any]]:
    players_by_id: dict[str, dict[str, Any]] = {}
    for abbreviation, team_id in TEAM_IDS.items():
        print(f"Fetching ESPN roster for {abbreviation}...", flush=True)
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
    print(f"Collected {len(players_by_id)} unique rostered players; game-log retrieval finished.", flush=True)
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
