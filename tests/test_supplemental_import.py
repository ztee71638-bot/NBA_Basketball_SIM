import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "import_supplemental_nba_stats.py"
spec = importlib.util.spec_from_file_location("import_supplemental_nba_stats", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_player_totals_csv_preserves_raw_columns_and_detects_entities():
    rows = ["player,team,points,minutes,games"] + [
        f"Player {i},T{i % 30:02d},{i},10,1" for i in range(100)
    ]
    parsed = module.parse_and_validate_csv("\n".join(rows), "2026-27", "player_totals")
    assert parsed["row_count"] == 100
    assert parsed["columns"] == ["player", "team", "points", "minutes", "games"]
    assert parsed["unique_players"] == 100
    assert parsed["unique_teams"] == 30


def test_team_standings_requires_exactly_thirty_distinct_teams():
    rows = ["team,wins,losses,points_for,points_against"] + [
        f"T{i:02d},{i},0,100,99" for i in range(30)
    ]
    parsed = module.parse_and_validate_csv("\n".join(rows), "2026-27", "team_standings")
    assert parsed["row_count"] == 30
    assert parsed["unique_teams"] == 30


def test_supplemental_import_rejects_incomplete_player_dataset():
    rows = ["player,team,points,minutes,games"] + [
        f"Player {i},BOS,{i},10,1" for i in range(10)
    ]
    try:
        module.parse_and_validate_csv("\n".join(rows), "2026-27", "player_totals")
    except ValueError as exc:
        assert "expected at least 100" in str(exc)
    else:
        raise AssertionError("incomplete dataset should be rejected")


def test_duplicate_full_rows_are_counted_without_silently_dropping_data():
    rows = ["player,team,points,minutes,games"] + [
        f"Player {i},BOS,{i},10,1" for i in range(99)
    ]
    rows.append("Player 0,BOS,0,10,1")
    parsed = module.parse_and_validate_csv("\n".join(rows), "2026-27", "player_totals")
    assert parsed["row_count"] == 100
    assert parsed["duplicate_full_rows"] == 1
