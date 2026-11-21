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
