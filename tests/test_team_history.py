import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "refresh_team_history.py"
spec = importlib.util.spec_from_file_location("refresh_team_history", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_parse_team_schedule_maps_home_away_scores():
    payload = {"events": [{
        "id": "g1",
        "date": "2026-11-20T00:00Z",
        "status": {"type": {"completed": True, "state": "post"}},
        "competitions": [{"competitors": [
            {"homeAway": "away", "team": {"id": "2", "abbreviation": "BOS"}, "score": "101"},
            {"homeAway": "home", "team": {"id": "13", "abbreviation": "LAL"}, "score": "110"},
        ]}],
    }]}
    rows = module.parse_team_schedule(payload, "13")
    assert len(rows) == 1
    assert rows[0]["team"] == "LAL"
    assert rows[0]["opponent"] == "BOS"
    assert rows[0]["points_for"] == 110
    assert rows[0]["points_against"] == 101
    assert rows[0]["win"] is True


def test_summarize_games_uses_recent_ten():
    games = [{"points_for": i + 100, "points_against": 100, "win": i % 2 == 0} for i in range(12)]
    summary = module.summarize_games(games)
    assert summary["games"] == 12
    assert summary["last10_games"] == 10
    assert summary["last10_avg_points_for"] == 105.5


def test_team_map_has_30_teams():
    assert len(module.TEAM_IDS) == 30
