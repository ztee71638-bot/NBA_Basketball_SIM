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
