"""Build team season and recent-form data from ESPN public team schedules.

Scheduled daily on the default branch; supports manual workflow dispatch and preserves the last good archive when collection is incomplete.
"""
from __future__ import annotations

import json
import time
import calendar
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/schedule"
SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
TIMEOUT = 25
DELAY = 0.8
WORKERS = max(1, min(4, int(os.getenv("NBA_TEAM_HISTORY_WORKERS", "4"))))
SEASONS = sorted({int(value) for value in os.getenv("NBA_TEAM_HISTORY_SEASONS", "2027,2026,2025,2024,2023").split(",") if value.strip()}, reverse=True)
TEAM_IDS = {
    "ATL": 1, "BOS": 2, "NOP": 3, "CHI": 4, "CLE": 5, "DAL": 6,
    "DEN": 7, "DET": 8, "GSW": 9, "HOU": 10, "IND": 11, "LAC": 12,
    "LAL": 13, "MIA": 14, "MIL": 15, "MIN": 16, "BKN": 17, "NYK": 18,
    "ORL": 19, "PHI": 20, "PHX": 21, "POR": 22, "SAC": 23, "SAS": 24,
    "OKC": 25, "UTA": 26, "WAS": 27, "TOR": 28, "MEM": 29, "CHA": 30,
}
ID_TO_TEAM = {str(team_id): abbr for abbr, team_id in TEAM_IDS.items()}
BOX_SCORE_METRIC_FIELDS = (
    "possessions_estimate", "pace_estimate", "offensive_rating",
    "defensive_rating", "advanced_stats_source",
)


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
    """Reliable fallback: collect completed games from ESPN daily scoreboard feeds."""
    today = datetime.now(timezone.utc).date()
    if season == today.year + 1:
        start, end = date(season - 1, 10, 1), today
    else:
        start, end = date(season - 1, 10, 1), date(season, 6, 30)
    grouped: dict[str, list[dict[str, Any]]] = {abbr: [] for abbr in TEAM_IDS}
    dates = list(_date_values(start, end))

    def fetch_day(game_date: date):
        payload = get_json(SCOREBOARD_URL, {
            "dates": game_date.strftime("%Y%m%d"), "seasontype": 2, "limit": 100
        })
        return game_date, payload

    # A small bounded pool keeps the fallback from taking hours while avoiding
    # an aggressive burst against ESPN's public endpoints.
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = [executor.submit(fetch_day, game_date) for game_date in dates]
        for future in as_completed(futures):
            game_date, payload = future.result()
            for event in payload.get("events") or []:
                competitions = event.get("competitions") or []
                if not competitions:
                    continue
                competition = competitions[0]
                status = (event.get("status") or {}).get("type") or (competition.get("status") or {}).get("type") or {}
                competitors = competition.get("competitors") or []
                if not status.get("completed", False) and status.get("state") != "post":
                    continue
                if len(competitors) != 2:
                    continue
                for own in competitors:
                    team = own.get("team") or {}
                    opponent = next((c.get("team") or {} for c in competitors if c is not own), {})
                    abbreviation = ID_TO_TEAM.get(str(team.get("id") or ""), team.get("abbreviation"))
                    opponent_abbreviation = ID_TO_TEAM.get(str(opponent.get("id") or ""), opponent.get("abbreviation"))
                    if abbreviation not in grouped or not opponent_abbreviation:
                        continue
                    points_for, points_against = _score(own.get("score")), _score(next((c.get("score") for c in competitors if c is not own), None))
                    if points_for is None or points_against is None:
                        continue
                    grouped[abbreviation].append({
                        "game_id": str(event.get("id") or ""),
                        "date": event.get("date") or game_date.isoformat(),
                        "team": abbreviation,
                        "opponent": opponent_abbreviation,
                        "opponent_name": opponent.get("displayName"),
                        "home_away": own.get("homeAway"),
                        "points_for": points_for,
                        "points_against": points_against,
                        "win": points_for > points_against,
                        "result": "W" if points_for > points_against else "L",
                    })
    for rows in grouped.values():
        rows.sort(key=lambda row: row.get("date") or "")
    return grouped


def fetch_season_from_team_schedules(season: int) -> dict[str, list[dict[str, Any]]]:
    """Prefer 30 team-schedule requests; fall back to scoreboard if season coverage is incomplete."""
    today = datetime.now(timezone.utc).date()
    season_start, season_end = date(season - 1, 10, 1), (
        today if season == today.year + 1 else date(season, 6, 30)
    )

    def fetch_team(abbreviation: str, team_id: int):
        failures = []
        rows = []
        # ESPN has used both the ending year and starting year as the schedule
        # query value. Accept only games inside the requested NBA season.
        for query_season in (season, season - 1):
            try:
                payload = get_json(URL.format(team_id=team_id), {
                    "season": query_season, "seasontype": 2
                })
                candidate = parse_team_schedule(payload, str(team_id))
                candidate = [
                    row for row in candidate
                    if row.get("date")
                    and season_start <= datetime.fromisoformat(
                        str(row["date"]).replace("Z", "+00:00")
                    ).date() <= season_end
                ]
                if candidate:
                    rows = candidate
                    break
            except requests.RequestException as exc:
                failures.append(f"{abbreviation}/{query_season}: {exc}")
        return abbreviation, rows, failures

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = [
            executor.submit(fetch_team, abbreviation, team_id)
            for abbreviation, team_id in TEAM_IDS.items()
        ]
        results = [future.result() for future in as_completed(futures)]

    grouped = {abbreviation: rows for abbreviation, rows, _ in results}
    failures = [failure for _, _, team_failures in results for failure in team_failures]
    for abbreviation in TEAM_IDS:
        print(f"{season} {abbreviation}: {len(grouped.get(abbreviation, []))} completed games", flush=True)

    total = sum(len(rows) for rows in grouped.values())
    average = total / max(1, len(TEAM_IDS))
    minimum_expected = 5 if season == today.year + 1 else 60
    if average < minimum_expected:
        print(
            f"Team schedule coverage for {season} is only {average:.1f} games/team; "
            "using the daily scoreboard fallback to fill the season.",
            flush=True,
        )
        fallback = fetch_season_from_scoreboard(season)
        fallback_total = sum(len(rows) for rows in fallback.values())
        if fallback_total > total:
            grouped = fallback
            total = fallback_total
    if total == 0:
        detail = "; ".join(failures[:5])
        raise RuntimeError(f"ESPN returned no completed games for season {season}. {detail}")
    if failures:
        print(f"Season {season}: {len(failures)} schedule request attempts failed.", flush=True)
    return grouped


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


def merge_cached_boxscore_metrics(existing_teams: list[dict[str, Any]],
                                    refreshed_teams: list[dict[str, Any]]) -> int:
    """Carry verified boxscore metrics forward when schedule history is rebuilt."""
    cached: dict[tuple[str, str], dict[str, Any]] = {}
    for team in existing_teams or []:
        abbreviation = str(team.get("abbreviation") or "")
        for season_data in (team.get("seasons") or {}).values():
            for row in season_data.get("games") or []:
                game_id = str(row.get("game_id") or "")
                if not game_id:
                    continue
                values = {key: row[key] for key in BOX_SCORE_METRIC_FIELDS
                          if row.get(key) is not None}
                if values:
                    cached[(game_id, abbreviation)] = values
    merged = 0
    for team in refreshed_teams:
        abbreviation = str(team.get("abbreviation") or "")
        for season_data in (team.get("seasons") or {}).values():
            for row in season_data.get("games") or []:
                values = cached.get((str(row.get("game_id") or ""), abbreviation), {})
                copied = False
                for key, value in values.items():
                    if row.get(key) is None:
                        row[key] = value
                        copied = True
                merged += int(copied)
    return merged


def enrich_team_games_with_boxscores(teams: list[dict[str, Any]], seasons_to_enrich: set[str] | None = None,
                                     max_games: int = 600) -> None:
    """Progressively enrich missing ESPN boxscores while retaining prior verified metrics."""
    games: dict[str, list[dict[str, Any]]] = {}
    dates: dict[str, str] = {}
    for team in teams:
        for season, season_data in team.get("seasons", {}).items():
            if seasons_to_enrich is not None and str(season) not in seasons_to_enrich:
                continue
            for row in season_data.get("games", []):
                if row.get("game_id"):
                    game_id = str(row["game_id"])
                    games.setdefault(game_id, []).append(row)
                    dates[game_id] = max(dates.get(game_id, ""), str(row.get("date") or ""))
    missing = [
        game_id for game_id, rows in games.items()
        if len(rows) == 2 and not all(
            all(row.get(field) is not None for field in BOX_SCORE_METRIC_FIELDS)
            for row in rows
        )
    ]
    selected = sorted(missing, key=lambda game_id: dates.get(game_id, ""), reverse=True)[:max_games]
    print(f"Enriching {len(selected)} missing game boxscores across selected seasons (limit {max_games}).", flush=True)
    enriched = 0
    for game_id in selected:
        rows = games[game_id]
        if len(rows) != 2 or all(
            all(row.get(field) is not None for field in BOX_SCORE_METRIC_FIELDS)
            for row in rows
        ):
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
    model_fields = (
        "game_id", "date", "opponent", "home_away", "points_for", "points_against",
        "pace_estimate", "possessions_estimate", "offensive_rating", "defensive_rating",
        "rest_days", "back_to_back", "games_last_3_days", "games_last_5_days",
        "travel_miles", "road_trip_games",
    )
    snapshot = {
        "snapshot_date": stamp,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "ESPN team history and available boxscores",
        "teams": [{
            "abbreviation": team["abbreviation"],
            "seasons": {
                season: {
                    "summary": data.get("summary", {}),
                    "games": [
                        {key: row.get(key) for key in model_fields if key in row}
                        for row in data.get("games", [])
                    ],
                }
                for season, data in team.get("seasons", {}).items()
            },
        } for team in teams],
    }
    path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")


def _canonical_team(abbreviation: str | None) -> str | None:
    aliases = {"GS": "GSW", "NY": "NYK", "NO": "NOP", "SA": "SAS", "WSH": "WAS"}
    return aliases.get(str(abbreviation or ""), str(abbreviation or "")) or None


def haversine_miles(a: dict[str, Any], b: dict[str, Any]) -> float:
    import math
    lat1, lon1 = math.radians(float(a["latitude"])), math.radians(float(a["longitude"]))
    lat2, lon2 = math.radians(float(b["latitude"])), math.radians(float(b["longitude"]))
    dlat, dlon = lat2-lat1, lon2-lon1
    value = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 3958.7613 * 2 * math.asin(math.sqrt(value))


def enrich_schedule_travel(team_abbreviation: str, rows: list[dict[str, Any]], arenas: dict[str, Any]) -> None:
    own_code = _canonical_team(team_abbreviation)
    for index, row in enumerate(rows):
        row["travel_miles"] = None
        row["road_trip_games"] = 0
        if row.get("home_away") == "away":
            row["road_trip_games"] = (rows[index-1].get("road_trip_games", 0) + 1) if index and rows[index-1].get("home_away") == "away" else 1
        if not index:
            continue
        previous = rows[index-1]
        previous_venue = own_code if previous.get("home_away") == "home" else _canonical_team(previous.get("opponent"))
        current_venue = own_code if row.get("home_away") == "home" else _canonical_team(row.get("opponent"))
        origin, destination = arenas.get(previous_venue), arenas.get(current_venue)
        if origin and destination:
            row["travel_miles"] = round(haversine_miles(origin, destination), 1)



def reconcile_missing_opponent_records(grouped: dict[str, list[dict[str, Any]]]) -> int:
    """Rebuild a missing team-side row from its verified completed-game mirror."""
    rows_by_game: dict[str, list[dict[str, Any]]] = {}
    for team_rows in grouped.values():
        for row in team_rows:
            game_id = str(row.get("game_id") or "")
            if game_id:
                rows_by_game.setdefault(game_id, []).append(row)
    added = 0
    for game_id, rows in rows_by_game.items():
        if len(rows) != 1:
            continue
        source = rows[0]
        team = str(source.get("team") or "")
        opponent = str(source.get("opponent") or "")
        if not team or opponent not in grouped or opponent == team:
            continue
        if any(str(existing.get("game_id")) == game_id for existing in grouped[opponent]):
            continue
        home_away = source.get("home_away")
        points_for, points_against = source.get("points_for"), source.get("points_against")
        if home_away not in ("home", "away") or not isinstance(points_for, (int, float)) or not isinstance(points_against, (int, float)):
            continue
        mirror = {
            "game_id": game_id, "date": source.get("date"), "team": opponent,
            "opponent": team, "opponent_name": team,
            "home_away": "away" if home_away == "home" else "home",
            "points_for": points_against, "points_against": points_for,
            "win": points_against > points_for,
            "result": "W" if points_against > points_for else "L",
            "source": "ESPN completed-game reciprocal record",
        }
        grouped[opponent].append(mirror)
        added += 1
    if added:
        for team_rows in grouped.values():
            team_rows.sort(key=lambda row: row.get("date") or "")
    print(f"Reconstructed {added} missing reciprocal team-game records from verified final scores.", flush=True)
    return added

def fetch_team_database() -> list[dict[str, Any]]:
    teams = [
        {"id": str(team_id), "abbreviation": abbreviation, "seasons": {}, "source": "ESPN"}
        for abbreviation, team_id in TEAM_IDS.items()
    ]
    # Use ESPN's per-team schedule endpoint: 30 calls per season, not ~270 daily
    # scoreboard calls per season. This keeps five-season refreshes bounded.
    grouped_by_season = {
        season: fetch_season_from_team_schedules(season)
        for season in sorted(SEASONS)
    }
    for season_rows in grouped_by_season.values():
        reconcile_missing_opponent_records(season_rows)
    arena_file = DATA / "arenas.json"
    arena_payload = json.loads(arena_file.read_text(encoding="utf-8")) if arena_file.exists() else {}
    arenas = arena_payload.get("teams", {})
    for team in teams:
        for season in sorted(SEASONS):
            rows = sorted(grouped_by_season[season].get(team["abbreviation"], []), key=lambda row: row.get("date") or "")
            for index, row in enumerate(rows):
                current_date = datetime.fromisoformat(str(row["date"]).replace("Z", "+00:00")).date()
                previous_dates = [
                    datetime.fromisoformat(str(previous["date"]).replace("Z", "+00:00")).date()
                    for previous in rows[:index]
                ]
                if previous_dates:
                    gap = (current_date - previous_dates[-1]).days
                    row["rest_days"] = max(0, gap - 1)
                    row["back_to_back"] = gap <= 1
                else:
                    row["rest_days"] = None
                    row["back_to_back"] = None
                row["games_last_3_days"] = sum(1 for day in previous_dates if 0 < (current_date-day).days <= 3)
                row["games_last_5_days"] = sum(1 for day in previous_dates if 0 < (current_date-day).days <= 5)
            enrich_schedule_travel(team["abbreviation"], rows, arenas)
            team["seasons"][str(season)] = {"games": rows, "summary": summarize_games(rows)}
    # Preserve previously collected advanced metrics, then progressively
    # backfill missing boxscores across all archived seasons in bounded batches.
    existing_path = DATA / "teams.json"
    if existing_path.exists():
        try:
            existing_payload = json.loads(existing_path.read_text(encoding="utf-8"))
            restored = merge_cached_boxscore_metrics(existing_payload.get("teams", []), teams)
            print(f"Restored {restored} team-game rows with previously verified boxscore metrics.", flush=True)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            print(f"Could not restore cached boxscore metrics: {exc}", flush=True)
    enrich_team_games_with_boxscores(teams, {str(value) for value in SEASONS}, max_games=600)
    for team in teams:
        for season_data in team["seasons"].values():
            season_data["summary"] = summarize_games(season_data.get("games", []))
    return teams


def main() -> None:
    teams = fetch_team_database()
    print("Collected multi-season team logs from ESPN daily scoreboard feeds.")
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
