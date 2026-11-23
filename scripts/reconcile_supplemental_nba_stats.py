"""Reconcile supplemental NBA Stats-derived data into the simulator archives.

Team-game metrics are joined only on season, date, team, opponent and final
scores. The script recomputes possession/pace/ratings with the simulator's
existing formulas and fills only missing canonical fields. Provider estimates
are retained separately for comparison, never substituted blindly.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SUPPLEMENTAL = DATA / "supplemental" / "boxscorelab"
SEASON_MAP = {"2022-23": "2023", "2023-24": "2024", "2024-25": "2025", "2025-26": "2026", "2026-27": "2027"}
BOX_FIELDS = (
    "field_goals_made", "field_goal_attempts", "field_goal_pct",
    "three_point_makes", "three_point_attempts", "three_point_pct",
    "free_throws_made", "free_throw_attempts", "offensive_rebounds",
    "defensive_rebounds", "rebounds", "assists", "steals", "blocks",
    "turnovers", "effective_fg_pct", "off_rating_est", "def_rating_est",
)
PLAYER_FIELDS = (
    "games_played", "minutes", "points", "rebounds", "assists", "steals",
    "blocks", "turnovers", "field_goals_made", "field_goal_attempts",
    "field_goal_pct", "three_point_makes", "three_point_attempts",
    "three_point_pct", "free_throws_made", "free_throw_attempts",
    "free_throw_pct", "points_pg", "rebounds_pg", "assists_pg", "ts_pct",
    "effective_fg_pct", "usage_rate", "ast_pct", "reb_pct", "tov_pct",
    "net_rating",
)


def number(value: Any) -> float | None:
    try:
        result = float(str(value).replace(",", "").strip())
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def normalized_name(value: Any) -> str:
    raw = unicodedata.normalize("NFKD", str(value or ""))
    ascii_name = "".join(char for char in raw if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", ascii_name.lower())


def _team_game_key(season: str, date_value: Any, team: Any, opponent: Any,
                   points_for: Any, points_against: Any) -> tuple | None:
    date_text = str(date_value or "")[:10]
    pf, pa = number(points_for), number(points_against)
    if not date_text or len(date_text) != 10 or pf is None or pa is None:
        return None
    return (
        str(season), date_text, str(team or "").upper(),
        str(opponent or "").upper(), int(round(pf)), int(round(pa)),
    )


def _candidate_game_dates(value: Any) -> list[str]:
    """Provider dates are local NBA dates; ESPN event timestamps are UTC."""
    text = str(value or "")[:10]
    try:
        local_date = date.fromisoformat(text)
    except ValueError:
        return []
    return [local_date.isoformat(), (local_date + timedelta(days=1)).isoformat()]


def reconcile_team_games(teams_payload: dict[str, Any],
                         supplemental_by_season: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    canonical: dict[tuple, dict[str, Any]] = {}
    duplicate_canonical = 0
    for team in teams_payload.get("teams") or []:
        abbreviation = str(team.get("abbreviation") or "").upper()
        for season, season_data in (team.get("seasons") or {}).items():
            for row in season_data.get("games") or []:
                key = _team_game_key(
                    str(season), row.get("date"), abbreviation, row.get("opponent"),
                    row.get("points_for"), row.get("points_against"),
                )
                if key is None:
                    continue
                if key in canonical:
                    duplicate_canonical += 1
                else:
                    canonical[key] = row

    report: dict[str, Any] = {
        "source_rows": 0, "matched_rows": 0, "unmatched_rows": 0,
        "score_or_key_mismatches": 0, "duplicate_source_rows": 0,
        "advanced_rows_added": 0, "advanced_fields_filled": 0,
        "by_season": {}, "unmatched_samples": [], "score_mismatch_samples": [],
    }
    for source_season, rows in supplemental_by_season.items():
        internal_season = SEASON_MAP[source_season]
        season_report = {
            "source_rows": len(rows), "matched_rows": 0, "unmatched_rows": 0,
            "score_or_key_mismatches": 0, "advanced_rows_added": 0,
            "advanced_fields_filled": 0,
        }
        seen_source_keys: set[tuple] = set()
        grouped: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
        for source in rows:
            team = str(source.get("team") or "").upper()
            opponent = str(source.get("opponent") or "").upper()
            date_value = source.get("game_date")
            pf, pa = number(source.get("points")), number(source.get("opponent_points"))
            key = _team_game_key(internal_season, date_value, team, opponent, pf, pa)
            if key is None:
                season_report["unmatched_rows"] += 1
                continue
            source_identity = (internal_season, key[1], team, opponent)
            if source_identity in seen_source_keys:
                report["duplicate_source_rows"] += 1
                season_report["unmatched_rows"] += 1
                continue
            seen_source_keys.add(source_identity)
            grouped[(internal_season, key[1], tuple(sorted((team, opponent))))].append(source)

        for game_key, game_rows in grouped.items():
            # Use only complete two-sided games so the opponent possession
            # estimate and the pace calculation have both source box scores.
            if len(game_rows) != 2 or {str(r.get("team") or "").upper() for r in game_rows} != set(game_key[2]):
                season_report["unmatched_rows"] += len(game_rows)
                continue
            matched: list[tuple[dict[str, Any], dict[str, Any], str]] = []
            for source in game_rows:
                team = str(source.get("team") or "").upper()
                opponent = str(source.get("opponent") or "").upper()
                candidate_dates = _candidate_game_dates(source.get("game_date"))
                candidate_keys = [
                    _team_game_key(
                        internal_season, candidate_date, team, opponent,
                        source.get("points"), source.get("opponent_points"),
                    )
                    for candidate_date in candidate_dates
                ]
                hits = [(key, canonical[key]) for key in candidate_keys if key in canonical]
                if len(hits) == 1:
                    target = hits[0][1]
                    matched.append((source, target, team))
                    continue
                if len(hits) > 1:
                    season_report["score_or_key_mismatches"] += 1
                    if len(report["score_mismatch_samples"]) < 25:
                        report["score_mismatch_samples"].append({
                            "season": source_season, "date": source.get("game_date"),
                            "team": team, "opponent": opponent, "reason": "ambiguous_date_match",
                        })
                    continue
                # Exact scores and participants are required. A one-day UTC
                # rollover is allowed, but a score conflict is never fuzzy-merged.
                near = [
                    k for k in canonical
                    if k[0] == internal_season and k[1] in candidate_dates
                    and k[2] == team and k[3] == opponent
                ]
                if near:
                    season_report["score_or_key_mismatches"] += 1
                    if len(report["score_mismatch_samples"]) < 25:
                        report["score_mismatch_samples"].append({
                            "season": source_season, "date": source.get("game_date"),
                            "team": team, "opponent": opponent,
                            "source_score": [source.get("points"), source.get("opponent_points")],
                            "canonical_scores": [[k[4], k[5]] for k in near],
                        })
                else:
                    season_report["unmatched_rows"] += 1
                    if len(report["unmatched_samples"]) < 25:
                        report["unmatched_samples"].append({
                            "season": source_season, "date": source.get("game_date"),
                            "team": team, "opponent": opponent,
                            "score": [source.get("points"), source.get("opponent_points")],
                        })
            if len(matched) != 2:
                # Each missing row was already classified above as either an
                # unmatched game or a score/key conflict; do not count it twice.
                continue

            source_by_team = {team: source for source, _, team in matched}
            target_by_team = {team: target for _, target, team in matched}
            teams = list(game_key[2])
            if set(source_by_team) != set(teams) or set(target_by_team) != set(teams):
                season_report["unmatched_rows"] += 2
                continue
            possessions: dict[str, float] = {}
            for team in teams:
                source = source_by_team[team]
                fga = number(source.get("field_goal_attempts"))
                oreb = number(source.get("offensive_rebounds"))
                turnovers = number(source.get("turnovers"))
                fta = number(source.get("free_throw_attempts"))
                if None in (fga, oreb, turnovers, fta):
                    possessions = {}
                    break
                estimate = fga - oreb + turnovers + 0.44 * fta
                if not math.isfinite(estimate) or estimate <= 0:
                    possessions = {}
                    break
                possessions[team] = estimate
            if len(possessions) != 2:
                season_report["unmatched_rows"] += 2
                continue

            pace = sum(possessions.values()) / 2
            for team in teams:
                source = source_by_team[team]
                opponent = str(source.get("opponent") or "").upper()
                target = target_by_team[team]
                box = {
                    field: number(source.get(field))
                    for field in BOX_FIELDS
                    if source.get(field) not in (None, "")
                }
                target["supplemental_boxscore"] = {
                    "provider": "BoxScore Lab",
                    "upstream_source": "NBA Stats (provider attribution)",
                    "license": "CC BY 4.0",
                    "season": source_season,
                    "game_date": str(source.get("game_date"))[:10],
                    "opponent": opponent,
                    "stats": box,
                }
                fill_values = {
                    "possessions_estimate": round(possessions[team], 2),
                    "pace_estimate": round(pace, 2),
                    "offensive_rating": round(number(source["points"]) / possessions[team] * 100, 2),
                    "defensive_rating": round(number(source["opponent_points"]) / possessions[opponent] * 100, 2),
                    "advanced_stats_source": (
                        "BoxScore Lab/NBA Stats boxscore; standardized as "
                        "FGA - OREB + TO + 0.44*FTA"
                    ),
                }
                filled = False
                for field, value in fill_values.items():
                    if target.get(field) is None:
                        target[field] = value
                        filled = True
                        season_report["advanced_fields_filled"] += 1
                if filled:
                    season_report["advanced_rows_added"] += 1
                season_report["matched_rows"] += 1

        report["source_rows"] += season_report["source_rows"]
        for key in (
            "matched_rows", "unmatched_rows", "score_or_key_mismatches",
            "advanced_rows_added", "advanced_fields_filled",
        ):
            report[key] += season_report[key]
        report["by_season"][source_season] = season_report

    report["duplicate_canonical_rows"] = duplicate_canonical
    return report


def _numeric_player_record(row: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in PLAYER_FIELDS:
        value = number(row.get(field))
        if value is not None:
            result[field] = value
    for field in ("player_name", "team", "position"):
        if row.get(field) not in (None, ""):
            result[field] = row[field]
    return result


def reconcile_player_totals(players_payload: dict[str, Any],
                            supplemental_by_season: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    players = players_payload.get("players") or []
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for player in players:
        by_name[normalized_name(player.get("name"))].append(player)
    report = {"source_rows": 0, "matched_rows": 0, "unmatched_rows": 0, "by_season": {}, "unmatched_samples": []}
    for source_season, rows in supplemental_by_season.items():
        season_key = SEASON_MAP[source_season]
        season_report = {"source_rows": len(rows), "matched_rows": 0, "unmatched_rows": 0}
        for row in rows:
            name_key = normalized_name(row.get("player_name"))
            team = str(row.get("team") or "").upper()
            candidates = by_name.get(name_key, [])
            team_candidates = [
                player for player in candidates
                if team in {
                    str(value).upper()
                    for value in (player.get("teams_by_season") or {}).get(season_key, [])
                }
            ]
            season_candidates = [
                player for player in candidates
                if season_key in {str(value) for value in (player.get("roster_seasons") or [])}
            ]
            if len(team_candidates) == 1:
                player = team_candidates[0]
            elif len(candidates) == 1:
                player = candidates[0]
            elif len(season_candidates) == 1:
                player = season_candidates[0]
            else:
                season_report["unmatched_rows"] += 1
                if len(report["unmatched_samples"]) < 50:
                    report["unmatched_samples"].append({
                        "season": source_season,
                        "player_name": row.get("player_name"),
                        "team": team,
                        "same_name_candidates": len(candidates),
                        "same_season_candidates": len(season_candidates),
                        "same_team_candidates": len(team_candidates),
                    })
                continue
            record = _numeric_player_record(row)
            record.update({
                "season": source_season,
                "source": "BoxScore Lab / NBA Stats",
                "license": "CC BY 4.0",
            })
            totals = player.setdefault("season_advanced_totals", {}).setdefault(season_key, [])
            identity = (normalized_name(record.get("player_name")), team)
            if not any(
                (normalized_name(existing.get("player_name")), str(existing.get("team") or "").upper()) == identity
                for existing in totals
            ):
                totals.append(record)
            season_report["matched_rows"] += 1
        report["source_rows"] += season_report["source_rows"]
        report["matched_rows"] += season_report["matched_rows"]
        report["unmatched_rows"] += season_report["unmatched_rows"]
        report["by_season"][source_season] = season_report
    return report


def main(supplemental_dir: Path = SUPPLEMENTAL) -> None:
    teams_path = DATA / "teams.json"
    players_path = DATA / "players.json"
    teams_payload = json.loads(teams_path.read_text(encoding="utf-8"))
    players_payload = json.loads(players_path.read_text(encoding="utf-8"))
    team_rows: dict[str, list[dict[str, Any]]] = {}
    player_rows: dict[str, list[dict[str, Any]]] = {}
    for season in SEASON_MAP:
        suffix = season.replace("-", "_")
        team_data = json.loads((supplemental_dir / f"{suffix}_team_games.json").read_text(encoding="utf-8"))
        player_data = json.loads((supplemental_dir / f"{suffix}_player_totals.json").read_text(encoding="utf-8"))
        team_rows[season] = team_data["rows"]
        player_rows[season] = player_data["rows"]

    team_report = reconcile_team_games(teams_payload, team_rows)
    player_report = reconcile_player_totals(players_payload, player_rows)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "BoxScore Lab (upstream attribution: NBA Stats)",
        "license": "CC BY 4.0",
        "team_games": team_report,
        "player_totals": player_report,
        "model_input_policy": (
            "Only exact date/team/opponent/final-score matches enrich team history. "
            "Existing canonical metrics are never overwritten. Newly filled advanced "
            "metrics use the simulator's established possession formula."
        ),
    }
    teams_path.write_text(json.dumps(teams_payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    players_path.write_text(json.dumps(players_payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    report_path = DATA / "supplemental" / "reconciliation_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    if team_report["duplicate_canonical_rows"] or team_report["duplicate_source_rows"]:
        raise SystemExit("Duplicate keys found during supplemental reconciliation.")
    mismatch_limit = max(10, int(team_report["source_rows"] * 0.01))
    if team_report["score_or_key_mismatches"] > mismatch_limit:
        raise SystemExit(
            f"Score/key conflicts exceed the 1% tolerance: "
            f"{team_report['score_or_key_mismatches']} > {mismatch_limit}."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--supplemental-dir", type=Path, default=SUPPLEMENTAL)
    main(parser.parse_args().supplemental_dir)
