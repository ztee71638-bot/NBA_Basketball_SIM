"""Build a free-first NBA player roster and game-log archive from ESPN public endpoints.

Scheduled daily on the default branch; supports manual workflow dispatch and preserves the last good archive when collection is incomplete.
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster"
GAMELOG_URL = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{athlete_id}/gamelog"
TIMEOUT = 25
DELAY = float(os.getenv("NBA_HISTORY_REQUEST_DELAY", "0.5"))
WORKERS = max(1, min(6, int(os.getenv("NBA_HISTORY_WORKERS", "4"))))
MIN_TOTAL_GAME_LOGS = 100
SEASONS = [int(x) for x in os.getenv("NBA_HISTORY_SEASONS", "2027,2026,2025,2024,2023").split(",") if x.strip()]
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
                match = re.search(r"(\d+(?:\.\d+)?)\s*[-/]\s*(\d+(?:\.\d+)?)", str(raw_value))
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
        })
    return rows


def fetch_player_database() -> list[dict[str, Any]]:
    players_by_id: dict[str, dict[str, Any]] = {}
    latest_season = max(SEASONS)

    # Build a true multi-season roster index. The previous collector only
    # queried the latest roster, which excluded players who left the league
    # or changed teams before the current season.
    for season in SEASONS:
        for abbreviation, team_id in TEAM_IDS.items():
            print(f"Fetching ESPN roster for {abbreviation} ({season})...", flush=True)
            try:
                roster_payload = get_json(
                    ROSTER_URL.format(team_id=team_id), {"season": season}
                )
            except requests.RequestException as exc:
                print(f"Roster unavailable for {abbreviation}/{season}: {exc}", flush=True)
                continue

            for athlete in flatten_roster(roster_payload):
                athlete_id = str(athlete.get("id") or "")
                if not athlete_id:
                    continue
                status = athlete.get("status") or {}
                if not isinstance(status, dict):
                    status = {}

                # Apply availability filtering only to the latest roster.
                # Historical roster membership is valid even when a player
                # is now retired, waived, inactive, or no longer on an NBA team.
                if season == latest_season and status.get("type") and status.get("type") not in (
                    "active", "day-to-day", "injured"
                ):
                    continue

                player = players_by_id.setdefault(athlete_id, {
                    "id": athlete_id,
                    "name": athlete.get("displayName") or athlete.get("fullName"),
                    "team": abbreviation,
                    "position": (athlete.get("position") or {}).get("abbreviation"),
                    "jersey": athlete.get("jersey"),
                    "status": status.get("name") or "Historical rostered",
                    "seasons": {},
                    "roster_seasons": [],
                    "teams_by_season": {},
                    "source": "ESPN",
                })
                season_key = str(season)
                if season_key not in player["roster_seasons"]:
                    player["roster_seasons"].append(season_key)
                teams = player["teams_by_season"].setdefault(season_key, [])
                if abbreviation not in teams:
                    teams.append(abbreviation)

                # SEASONS is newest-first by default. Preserve the most
                # recent known team/identity as the primary display identity.
                if season == latest_season or not player.get("_latest_roster_season"):
                    player["team"] = abbreviation
                    player["name"] = athlete.get("displayName") or athlete.get("fullName") or player["name"]
                    player["position"] = (athlete.get("position") or {}).get("abbreviation") or player["position"]
                    player["jersey"] = athlete.get("jersey") or player["jersey"]
                    if season == latest_season:
                        player["status"] = status.get("name") or "Rostered"
                    player["_latest_roster_season"] = season
                elif season > player["_latest_roster_season"]:
                    player["_latest_roster_season"] = season
                    player["team"] = abbreviation

    if not players_by_id:
        raise RuntimeError("ESPN returned no historical rostered players; refusing to write an empty archive.")

    tasks = [
        (athlete_id, season)
        for athlete_id in players_by_id
        for season in SEASONS
    ]
    print(
        f"Fetching {len(tasks)} player-season logs for {len(players_by_id)} players "
        f"across {SEASONS} using {WORKERS} workers.",
        flush=True,
    )

    def fetch_one(task: tuple[str, int]) -> tuple[str, int, list[dict[str, Any]], str | None]:
        athlete_id, season = task
        try:
            payload = get_json(GAMELOG_URL.format(athlete_id=athlete_id), {"season": season})
            return athlete_id, season, parse_player_gamelog(payload), None
        except requests.RequestException as exc:
            return athlete_id, season, [], str(exc)

    failures = 0
    completed = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = [executor.submit(fetch_one, task) for task in tasks]
        for future in as_completed(futures):
            athlete_id, season, rows, error = future.result()
            players_by_id[athlete_id]["seasons"][str(season)] = rows
            completed += 1
            if error:
                failures += 1
                print(
                    f"Game log unavailable for {players_by_id[athlete_id]['name']} "
                    f"({season}): {error}",
                    flush=True,
                )
            if completed % 100 == 0 or completed == len(tasks):
                print(
                    f"Player logs: {completed}/{len(tasks)} requests complete; "
                    f"{failures} unavailable; "
                    f"{sum(len(v) for p in players_by_id.values() for v in p['seasons'].values())} game rows parsed.",
                    flush=True,
                )

    # Ensure every player has an explicit entry for every requested season.
    for player in players_by_id.values():
        player.pop("_latest_roster_season", None)
        player["roster_seasons"].sort(key=int, reverse=True)
        for season in SEASONS:
            player["seasons"].setdefault(str(season), [])
    total_logs = sum(
        len(rows)
        for player in players_by_id.values()
        for rows in player["seasons"].values()
    )
    if total_logs < MIN_TOTAL_GAME_LOGS:
        raise RuntimeError(
            f"Only {total_logs} player game-log rows were parsed from {len(tasks)} requests; "
            "refusing to overwrite the existing archive."
        )
    print(
        f"Collected {len(players_by_id)} players from {len(SEASONS)} historical roster seasons "
        f"and {total_logs} game-log rows; {failures}/{len(tasks)} player-season requests unavailable.",
        flush=True,
    )
    return sorted(players_by_id.values(), key=lambda p: (p["team"], p["name"] or ""))

def build_roster_index(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the small roster-only dataset needed to classify live player props."""
    fields = ("id", "name", "team", "position", "status", "roster_seasons", "teams_by_season")
    return [
        {key: player.get(key) for key in fields}
        for player in players
        if player.get("id") and player.get("name")
    ]


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
    output = DATA / "players.json"
    rendered = json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n"
    output.write_text(rendered, encoding="utf-8")
    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"Saved {len(players)} NBA player records across seasons {SEASONS}; compact archive size {size_mb:.1f} MiB.")
    if size_mb >= 90:
        raise RuntimeError(f"Player archive is still too large ({size_mb:.1f} MiB); refusing to publish it.")
    roster_payload = {
        "last_updated": payload["last_updated"],
        "source": "ESPN historical NBA roster index",
        "player_count": len(players),
        "players": build_roster_index(players),
    }
    roster_output = DATA / "player_roster.json"
    roster_output.write_text(
        json.dumps(roster_payload, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Saved lightweight market roster index: {roster_output.stat().st_size / 1024:.1f} KiB.")


if __name__ == "__main__":
    main()
