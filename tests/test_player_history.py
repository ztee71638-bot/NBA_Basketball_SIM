import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "refresh_player_history.py"
spec = importlib.util.spec_from_file_location("refresh_player_history", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_flatten_roster_supports_flat_and_grouped_shapes():
    payload = {"athletes": [
        {"id": "1", "displayName": "Player One"},
        {"position": "Guard", "items": [{"id": "2", "displayName": "Player Two"}]},
    ]}
    assert [p["id"] for p in module.flatten_roster(payload)] == ["1", "2"]


def test_parse_player_gamelog_maps_common_stats():
    payload = {
        "names": ["date", "opponent", "gameResult", "minutes", "fieldGoalsMade",
                  "threePointsMade", "freeThrowsMade", "rebounds", "assists",
                  "steals", "blocks", "points"],
        "events": [{
            "id": "game-1",
            "date": "2026-11-20T00:00Z",
            "opponent": {"displayName": "Boston Celtics", "abbreviation": "BOS"},
            "gameResult": "W",
            "stats": ["35", "10-18", "3-7", "5-6", "8", "7", "2", "1", "28"],
        }],
    }
    rows = module.parse_player_gamelog(payload)
    assert len(rows) == 1
    assert rows[0]["minutes"] == 35
    assert rows[0]["points"] == 28
    assert rows[0]["rebounds"] == 8
    assert rows[0]["assists"] == 7
    assert rows[0]["steals"] == 2
    assert rows[0]["blocks"] == 1


def test_number_handles_missing_and_invalid_values():
    assert module._number(None) is None
    assert module._number("not available") is None
    assert module._number("12.5") == 12.5


def test_team_id_map_has_30_teams():
    assert len(module.TEAM_IDS) == 30
    assert module.TEAM_IDS["LAL"] == 13
