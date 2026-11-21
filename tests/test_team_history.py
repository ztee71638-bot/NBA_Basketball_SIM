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
    assert summary["last10_avg_points_for"] == 106.5


def test_team_map_has_30_teams():
    assert len(module.TEAM_IDS) == 30


def test_parse_team_schedule_reads_competition_level_status():
    payload = {"events": [{
        "id": "g2",
        "date": "2026-11-21T00:00Z",
        "competitions": [{
            "status": {"type": {"completed": True, "state": "post"}},
            "competitors": [
                {"homeAway": "home", "team": {"id": "1", "abbreviation": "ATL"}, "score": "112"},
                {"homeAway": "away", "team": {"id": "2", "abbreviation": "BOS"}, "score": "105"},
            ],
        }],
    }]}
    rows = module.parse_team_schedule(payload, "1")
    assert len(rows) == 1
    assert rows[0]["points_for"] == 112


def test_parse_team_schedule_accepts_numeric_completed_scores_without_status():
    payload = {"events": [{
        "id": "g3", "date": "2026-11-22T00:00Z",
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": "13", "abbreviation": "LAL"}, "score": "108"},
            {"homeAway": "away", "team": {"id": "2", "abbreviation": "BOS"}, "score": "102"},
        ]}],
    }]}
    rows = module.parse_team_schedule(payload, "13")
    assert len(rows) == 1
    assert rows[0]["points_for"] == 108




def test_date_ranges_cover_partial_weeks():
    from datetime import date
    assert list(module._date_ranges(date(2026, 10, 15), date(2026, 10, 30), 7)) == [
        "20261015-20261021", "20261022-20261028", "20261029-20261030"
    ]
