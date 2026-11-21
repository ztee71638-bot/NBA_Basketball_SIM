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



def test_parse_player_gamelog_retains_minutes_and_impact_fields():
    payload = {
        "labels": ["MIN", "FG", "3PT", "FT", "OREB", "REB", "AST", "TO", "+/-", "PTS"],
        "events": {"impact-1": {"id": "impact-1", "date": "2026-11-20T00:00Z"}},
        "seasonTypes": [{"categories": [{"events": [{
            "eventId": "impact-1",
            "stats": ["34", "9-17", "2-5", "4-4", "3", "8", "6", "2", "+11", "24"]
        }]}]}],
    }
    row = module.parse_player_gamelog(payload)[0]
    assert row["minutes"] == 34
    assert row["turnovers"] == 2
    assert row["offensive_rebounds"] == 3
    assert row["plus_minus"] == 11
    assert row["field_goals_attempted"] == 17
    assert row["three_pointers_attempted"] == 5
    assert row["free_throws_attempted"] == 4

def test_number_handles_missing_and_invalid_values():
    assert module._number(None) is None
    assert module._number("not available") is None
    assert module._number("12.5") == 12.5


def test_player_archive_collects_current_and_previous_seasons_by_default():
    assert module.SEASONS == [2027, 2026, 2025, 2024, 2023]


def test_team_id_map_has_30_teams():
    assert len(module.TEAM_IDS) == 30
    assert module.TEAM_IDS["LAL"] == 13


def test_parse_player_gamelog_supports_event_dictionary():
    payload = {
        "names": ["minutes", "points"],
        "events": {"game-2": {"id": "game-2", "date": "2026-11-21T00:00Z", "stats": ["32", "24"]}},
    }
    rows = module.parse_player_gamelog(payload)
    assert len(rows) == 1
    assert rows[0]["event_id"] == "game-2"
    assert rows[0]["minutes"] == 32
    assert rows[0]["points"] == 24


def test_parse_player_gamelog_supports_current_nested_espn_shape():
    payload = {
        "labels": ["MIN", "FG", "3PT", "FT", "REB", "AST", "STL", "BLK", "PTS"],
        "events": {"game-3": {
            "id": "game-3", "gameDate": "2026-11-20T00:00Z",
            "opponent": {"displayName": "Boston Celtics", "abbreviation": "BOS"},
            "gameResult": "W",
        }},
        "seasonTypes": [{ "categories": [{ "events": [{
            "eventId": "game-3", "stats": ["35", "10-18", "3-7", "5-6", "8", "7", "2", "1", "28"]
        }]}]}],
    }
    rows = module.parse_player_gamelog(payload)
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-11-20T00:00Z"
    assert rows[0]["opponent_abbreviation"] == "BOS"
    assert rows[0]["minutes"] == 35
    assert rows[0]["points"] == 28
    assert rows[0]["rebounds"] == 8
    assert rows[0]["assists"] == 7


def test_player_database_fetches_all_seasons_with_bounded_parallel_workers(monkeypatch):
    calls = []
    def fake_get_json(url, params=None):
        calls.append((url, params))
        if "/roster" in url:
            team_id = url.rsplit("/", 2)[-2]
            if team_id == "1":
                return {"athletes": [{"id": "athlete-1", "displayName": "Test Player",
                                      "position": {"abbreviation": "G"}, "status": {"type": "active"}}]}
            return {"athletes": []}
        return {
            "names": ["minutes", "points"],
            "events": {"game-1": {"id": "game-1", "date": "2026-11-20T00:00Z",
                                   "stats": ["34", "24"]}},
        }
    monkeypatch.setattr(module, "get_json", fake_get_json)
    monkeypatch.setattr(module, "WORKERS", 2)
    players = module.fetch_player_database()
    assert len(players) == 1
    assert sorted(players[0]["seasons"]) == ["2023", "2024", "2025", "2026", "2027"]
    assert all(len(players[0]["seasons"][str(season)]) == 1 for season in module.SEASONS)
    assert len([call for call in calls if "/gamelog" in call[0]]) == 5
