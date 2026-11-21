"""Audit NBA simulator archive coverage, consistency, and freshness.

The audit reports missing data as warnings; it never fabricates or fills records.
Use --strict in CI when a release must be blocked by any warning.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def age_hours(value: str | None, now: datetime) -> float | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return round((now - stamp).total_seconds() / 3600, 2)
    except (TypeError, ValueError):
        return None


def audit_payloads(teams_payload: dict[str, Any], players_payload: dict[str, Any] | None = None,
                   now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    warnings: list[str] = []
    errors: list[str] = []
    teams = teams_payload.get("teams") or []
    if teams_payload.get("team_count") != 30 or len(teams) != 30:
        errors.append(f"Expected 30 NBA teams; found {len(teams)}.")
    abbreviations = [team.get("abbreviation") for team in teams]
    duplicates = sorted(code for code, count in Counter(abbreviations).items() if count > 1)
    if duplicates:
        errors.append("Duplicate team records: " + ", ".join(duplicates))

    season_counts: dict[str, dict[str, int]] = defaultdict(dict)
    game_ids_by_season: dict[str, set[str]] = defaultdict(set)
    duplicate_ids_by_season: Counter[str] = Counter()
    paired_games: dict[str, list[dict[str, Any]]] = defaultdict(list)
    malformed = 0
    for team in teams:
        abbreviation = team.get("abbreviation") or "UNKNOWN"
        for season, season_data in (team.get("seasons") or {}).items():
            rows = season_data.get("games") or []
            season_counts[str(season)][abbreviation] = len(rows)
            seen = set()
            for row in rows:
                game_id = str(row.get("game_id") or "")
                if not game_id or not row.get("date") or not isinstance(row.get("points_for"), (int, float)) or not isinstance(row.get("points_against"), (int, float)):
                    malformed += 1
                    continue
                if game_id in seen:
                    duplicate_ids_by_season[str(season)] += 1
                    errors.append(f"Duplicate game {game_id} for {abbreviation} in season {season}.")
                seen.add(game_id)
                game_ids_by_season[str(season)].add(game_id)
                paired_games[f"{season}:{game_id}"].append({
                    "team": abbreviation, "opponent": row.get("opponent"),
                    "points_for": row.get("points_for"), "points_against": row.get("points_against")
                })
    if malformed:
        warnings.append(f"{malformed} team-game rows have missing IDs, dates, or numeric scores.")
    season_summary = {}
    for season, counts in sorted(season_counts.items()):
        total = sum(counts.values())
        active_teams = sum(value > 0 for value in counts.values())
        # A normal NBA game appears once in each team log. Count only duplicates within one team season.
        duplicate_ids = duplicate_ids_by_season[season]
        season_summary[season] = {
            "team_records": len(counts), "teams_with_games": active_teams,
            "team_game_rows": total, "unique_game_ids": len(set(game_ids_by_season[season])),
            "duplicate_team_game_ids": duplicate_ids,
            "min_team_games": min(counts.values()) if counts else 0,
            "max_team_games": max(counts.values()) if counts else 0,
        }
        if active_teams < 30:
            warnings.append(f"Season {season}: only {active_teams}/30 teams have game history.")
        if duplicate_ids:
            errors.append(f"Season {season}: {duplicate_ids} duplicate team-game IDs.")
        # A finished regular season should ordinarily have about 82 games/team.
        if total and total / max(1, active_teams) < 60 and int(season) < now.year:
            warnings.append(f"Season {season}: average history is below 60 games/team.")
    mismatched = 0
    non_nba_or_unresolved_opponent_games = 0
    nba_team_codes = set(abbreviations)
    mismatch_breakdown = Counter()
    mismatch_examples: list[dict[str, Any]] = []
    for key, rows in sorted(paired_games.items()):
        reasons = []
        if len(rows) == 1 and (
            not rows[0].get("opponent") or rows[0].get("opponent") not in nba_team_codes
        ):
            # The historical schedule includes preseason/exhibition games
            # against international/select teams, plus occasional missing
            # opponent labels. These are not missing NBA-vs-NBA counterparts.
            non_nba_or_unresolved_opponent_games += 1
            continue
        if len(rows) != 2:
            reasons.append("missing_opponent_record" if len(rows) == 1 else "unexpected_record_count")
        else:
            a, b = rows
            if a["opponent"] != b["team"] or b["opponent"] != a["team"]:
                reasons.append("opponent_abbreviation_mismatch")
            if a["points_for"] != b["points_against"] or a["points_against"] != b["points_for"]:
                reasons.append("score_mismatch")
        if reasons:
            mismatched += 1
            for reason in reasons:
                mismatch_breakdown[reason] += 1
            if len(mismatch_examples) < 50:
                mismatch_examples.append({
                    "season_game": key,
                    "reason": reasons,
                    "records": rows,
                })
    if mismatched:
        warnings.append(f"{mismatched} game IDs do not have a fully matching two-team record.")

    team_age = age_hours(teams_payload.get("last_updated"), now)
    if team_age is None:
        warnings.append("Team history timestamp is missing or invalid.")
    elif team_age > 48:
        warnings.append(f"Team history is {team_age} hours old (over 48-hour threshold).")

    player_summary = {"available": players_payload is not None}
    if players_payload is not None:
        player_rows = players_payload.get("players") or []
        player_summary.update({
            "player_count": len(player_rows),
            "declared_player_count": players_payload.get("player_count"),
            "seasons": players_payload.get("seasons", []),
            "last_updated": players_payload.get("last_updated"),
            "age_hours": age_hours(players_payload.get("last_updated"), now),
        })
        if len(player_rows) < 100:
            warnings.append(f"Player archive contains only {len(player_rows)} records.")
        if players_payload.get("player_count") != len(player_rows):
            errors.append("Player archive declared count does not match actual records.")
        if player_summary["age_hours"] is None or player_summary["age_hours"] > 48:
            warnings.append("Player archive timestamp is missing or older than 48 hours.")
        player_ids = [str(row.get("id") or "") for row in player_rows]
        if len(player_ids) != len(set(player_ids)):
            errors.append("Player archive contains duplicate ESPN player IDs.")
        missing_logs = sum(not any((row.get("seasons") or {}).values()) for row in player_rows)
        player_summary["players_without_any_logs"] = missing_logs
        if missing_logs:
            warnings.append(f"{missing_logs} player records have no game logs in any stored season.")
    else:
        warnings.append("Player archive could not be audited because data/players.json is missing or unreadable.")

    status = "error" if errors else ("warning" if warnings else "ok")
    return {
        "generated_at": now.isoformat(),
        "status": status,
        "team_history": {
            "last_updated": teams_payload.get("last_updated"),
            "age_hours": team_age,
            "team_count": len(teams),
            "seasons": season_summary,
            "unpaired_or_mismatched_games": mismatched,
            "non_nba_or_unresolved_opponent_games": non_nba_or_unresolved_opponent_games,
            "mismatch_breakdown": dict(sorted(mismatch_breakdown.items())),
            "mismatch_examples": mismatch_examples,
        },
        "player_history": player_summary,
        "warnings": warnings,
        "errors": errors,
        "note": "This is a coverage and integrity audit, not a measure of predictive accuracy."
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--teams", type=Path, default=DATA / "teams.json")
    parser.add_argument("--players", type=Path, default=DATA / "players.json")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    teams = json.loads(args.teams.read_text(encoding="utf-8"))
    players = None
    if args.players.exists():
        try:
            players = json.loads(args.players.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            players = None
    result = audit_payloads(teams, players)
    rendered = json.dumps(result, indent=2)
    print(rendered)
    for warning in result["warnings"]:
        print(f"::warning::{warning}")
    for error in result["errors"]:
        print(f"::error::{error}")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if result["errors"] or (args.strict and result["warnings"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
