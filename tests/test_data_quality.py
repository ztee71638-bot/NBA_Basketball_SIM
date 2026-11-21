import importlib.util
from datetime import datetime, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "audit_data_quality.py"
spec = importlib.util.spec_from_file_location("audit_data_quality", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    teams = []
    for code, opponent, points, against in (
        ("AAA", "BBB", 110, 100),
        ("BBB", "AAA", 100, 110),
    ):
        teams.append({
            "abbreviation": code,
            "seasons": {"2027": {"games": [{
                "game_id": "game-1", "date": "2026-11-20T00:00:00+00:00",
                "opponent": opponent, "points_for": points, "points_against": against,
            }]}}
        })
    return {"last_updated": "2026-11-21T00:00:00+00:00", "team_count": 2, "teams": teams}


def test_audit_detects_consistent_two_team_game_and_reports_partial_team_coverage():
    result = module.audit_payloads(
        fixture(), None, datetime(2026, 11, 21, 1, tzinfo=timezone.utc)
    )
    assert result["team_history"]["unpaired_or_mismatched_games"] == 0
    assert result["status"] == "error"  # Fixture intentionally has only two teams, not 30.
    assert any("30 NBA teams" in item for item in result["errors"])


def test_audit_flags_unpaired_or_mismatched_game_records():
    payload = fixture()
    payload["teams"][1]["seasons"]["2027"]["games"][0]["points_for"] = 99
    result = module.audit_payloads(
        payload, None, datetime(2026, 11, 21, 1, tzinfo=timezone.utc)
    )
    assert result["team_history"]["unpaired_or_mismatched_games"] == 1
    assert any("matching two-team record" in item for item in result["warnings"])


def test_audit_flags_stale_team_history():
    payload = fixture()
    payload["team_count"] = 30
    payload["teams"] += [
        {"abbreviation": f"T{i}", "seasons": {"2027": {"games": []}}}
        for i in range(28)
    ]
    result = module.audit_payloads(
        payload, None, datetime(2026, 11, 25, 0, tzinfo=timezone.utc)
    )
    assert any("over 48-hour" in item for item in result["warnings"])


def test_audit_does_not_treat_opponent_pair_as_duplicate_team_game_id():
    result = module.audit_payloads(
        fixture(), None, datetime(2026, 11, 21, 1, tzinfo=timezone.utc)
    )
    assert result["team_history"]["seasons"]["2027"]["unique_game_ids"] == 1
    assert result["team_history"]["seasons"]["2027"]["duplicate_team_game_ids"] == 0
    assert not any("duplicate team-game IDs" in item for item in result["errors"])


def test_current_season_partial_schedule_is_not_flagged_as_incomplete_finished_season():
    payload = fixture()
    for team in payload["teams"]:
        team["seasons"] = {"2026": team["seasons"]["2027"]}
    result = module.audit_payloads(
        payload, None, datetime(2026, 11, 21, 1, tzinfo=timezone.utc)
    )
    assert not any("average history is below 60 games/team" in item for item in result["warnings"])


def test_audit_reports_mismatch_reasons_and_record_examples():
    payload = fixture()
    payload["teams"][1]["seasons"]["2027"]["games"][0]["points_for"] = 99
    result = module.audit_payloads(
        payload, None, datetime(2026, 11, 21, 1, tzinfo=timezone.utc)
    )
    audit = result["team_history"]
    assert audit["mismatch_breakdown"] == {"score_mismatch": 1}
    assert audit["mismatch_examples"][0]["season_game"] == "2027:game-1"
    assert audit["mismatch_examples"][0]["records"][0]["team"] == "AAA"


def test_audit_excludes_non_nba_exhibition_opponent_from_nba_pairing_warnings():
    payload = fixture()
    payload["teams"][0]["seasons"]["2027"]["games"].append({
        "game_id": "exhibition-1", "date": "2026-10-10T00:00:00+00:00",
        "opponent": "ADL", "points_for": 124, "points_against": 134,
    })
    payload["teams"][1]["seasons"]["2027"]["games"].append({
        "game_id": "exhibition-2", "date": "2026-10-11T00:00:00+00:00",
        "opponent": None, "points_for": 111, "points_against": 100,
    })
    result = module.audit_payloads(
        payload, None, datetime(2026, 11, 21, 1, tzinfo=timezone.utc)
    )
    audit = result["team_history"]
    assert audit["unpaired_or_mismatched_games"] == 0
    assert audit["non_nba_or_unresolved_opponent_games"] == 2
    assert not any("matching two-team record" in item for item in result["warnings"])


def test_audit_still_flags_missing_record_against_known_nba_team():
    payload = fixture()
    payload["teams"][1]["seasons"]["2027"]["games"] = []
    result = module.audit_payloads(
        payload, None, datetime(2026, 11, 21, 1, tzinfo=timezone.utc)
    )
    assert result["team_history"]["unpaired_or_mismatched_games"] == 1
    assert result["team_history"]["mismatch_breakdown"] == {"missing_opponent_record": 1}


def test_player_audit_reports_per_season_log_coverage_and_missing_player_sample():
    players = {
        "player_count": 2,
        "last_updated": "2026-11-21T00:00:00+00:00",
        "players": [
            {"id": "1", "name": "Player One", "team": "AAA",
             "seasons": {"2027": {"games": [{"date": "2026-11-20"}]},
                         "2026": {"games": [{"date": "2025-11-20"}, {"date": "2025-11-22"}]}}},
            {"id": "2", "name": "Player Two", "team": "BBB", "seasons": {}},
        ],
    }
    result = module.audit_payloads(
        fixture(), players, datetime(2026, 11, 21, 1, tzinfo=timezone.utc)
    )
    summary = result["player_history"]
    assert summary["game_logs_by_season"] == {"2026": 2, "2027": 1}
    assert summary["players_with_logs_by_season"] == {"2026": 1, "2027": 1}
    assert summary["players_without_any_logs"] == 1
    assert summary["players_without_logs_sample"] == [
        {"id": "2", "name": "Player Two", "team": "BBB"}
    ]



def test_audit_reports_advanced_boxscore_coverage_and_requires_both_teams():
    payload = fixture()
    for team in payload["teams"]:
        team["seasons"]["2027"]["games"][0].update({
            "pace_estimate": 99.5,
            "offensive_rating": 112.0,
            "defensive_rating": 108.0,
        })
    now = datetime(2026, 11, 21, 1, tzinfo=timezone.utc)
    complete = module.audit_payloads(payload, None, now)
    season = complete["team_history"]["seasons"]["2027"]
    assert season["advanced_team_game_rows"] == 2
    assert season["advanced_games_with_both_teams"] == 1
    assert season["advanced_coverage_pct"] == 100.0

    del payload["teams"][1]["seasons"]["2027"]["games"][0]["pace_estimate"]
    partial = module.audit_payloads(payload, None, now)
    season = partial["team_history"]["seasons"]["2027"]
    assert season["advanced_team_game_rows"] == 1
    assert season["advanced_games_with_both_teams"] == 0
    assert season["advanced_coverage_pct"] == 50.0


def test_audit_warns_when_advanced_boxscore_coverage_is_low_for_a_season():
    payload = fixture()
    for team in payload["teams"]:
        team["seasons"]["2026"] = {"games": [{
            "game_id": "older-game", "date": "2025-11-20T00:00:00+00:00",
            "opponent": "BBB" if team["abbreviation"] == "AAA" else "AAA",
            "points_for": 110 if team["abbreviation"] == "AAA" else 100,
            "points_against": 100 if team["abbreviation"] == "AAA" else 110,
        }]}
    result = module.audit_payloads(
        payload, None, datetime(2026, 11, 21, 1, tzinfo=timezone.utc)
    )
    assert any(
        "Season 2026: advanced box-score coverage is only 0.0%" in item
        for item in result["warnings"]
    )


def test_player_audit_detects_duplicate_game_logs_and_invalid_box_score_values():
    players = {
        "player_count": 1,
        "last_updated": "2026-11-21T00:00:00+00:00",
        "players": [{
            "id": "1", "name": "Player One", "team": "AAA",
            "seasons": {"2027": {"games": [
                {"event_id": "g1", "date": "2026-11-20", "points": 20,
                 "field_goals_made": 8, "field_goals_attempted": 7},
                {"event_id": "g1", "date": "2026-11-20", "points": -2},
            ]}},
        }],
    }
    result = module.audit_payloads(
        fixture(), players, datetime(2026, 11, 21, 1, tzinfo=timezone.utc)
    )
    summary = result["player_history"]
    assert summary["duplicate_player_game_logs"] == 1
    assert summary["invalid_player_stat_rows"] == 2
    assert any("duplicate game logs" in item for item in result["errors"])
    assert any("impossible box-score values" in item for item in result["errors"])


def test_player_audit_detects_invalid_and_out_of_season_game_dates():
    players = {
        "player_count": 1,
        "last_updated": "2026-11-21T00:00:00+00:00",
        "players": [{
            "id": "1", "name": "Player One", "team": "AAA",
            "seasons": {"2027": {"games": [
                {"event_id": "g1", "date": "not-a-date", "points": 10},
                {"event_id": "g2", "date": "2024-11-20", "points": 10},
            ]}},
        }],
    }
    result = module.audit_payloads(
        fixture(), players, datetime(2026, 11, 21, 1, tzinfo=timezone.utc)
    )
    summary = result["player_history"]
    assert summary["invalid_player_game_dates"] == 1
    assert summary["out_of_season_player_game_logs"] == 1
    assert any("missing or invalid dates" in item for item in result["errors"])
    assert any("outside their declared season" in item for item in result["warnings"])


def test_audit_validates_advanced_metric_formulas_against_both_team_box_scores():
    payload = fixture()
    first = payload["teams"][0]["seasons"]["2027"]["games"][0]
    second = payload["teams"][1]["seasons"]["2027"]["games"][0]
    first.update({
        "possessions_estimate": 100.0, "pace_estimate": 99.0,
        "offensive_rating": 110.0, "defensive_rating": round(100 / 98 * 100, 2),
    })
    second.update({
        "possessions_estimate": 98.0, "pace_estimate": 99.0,
        "offensive_rating": round(100 / 98 * 100, 2), "defensive_rating": 110.0,
    })
    now = datetime(2026, 11, 21, 1, tzinfo=timezone.utc)
    valid = module.audit_payloads(payload, None, now)
    assert valid["team_history"]["advanced_metric_integrity_errors"] == 0
    assert not any("advanced metrics" in item for item in valid["errors"])

    first["offensive_rating"] = 125.0
    invalid = module.audit_payloads(payload, None, now)
    assert invalid["team_history"]["advanced_metric_integrity_errors"] == 1
    assert any("do not reconcile" in item for item in invalid["errors"])
