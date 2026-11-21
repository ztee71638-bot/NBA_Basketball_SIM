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



def test_parse_team_boxscore_stats_and_estimated_possessions():
    stats = module._stat_map({"statistics": [
        {"name": "fieldGoalsMade-fieldGoalsAttempted", "displayValue": "40-85"},
        {"name": "freeThrowsMade-freeThrowsAttempted", "displayValue": "18-22"},
        {"name": "offensiveRebounds", "displayValue": "10"},
        {"name": "totalTurnovers", "displayValue": "12"},
    ]})
    assert stats["fieldgoalsattempted"] == 85
    assert stats["freethrowsattempted"] == 22
    assert round(module._possessions(stats), 2) == 96.68


def test_parse_team_schedule_does_not_treat_zero_zero_as_final():
    payload = {"events": [{
        "id": "future", "status": {"type": {"completed": False, "state": "pre"}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": "1"}, "score": "0"},
            {"homeAway": "away", "team": {"id": "2"}, "score": "0"},
        ]}],
    }]}
    assert module.parse_team_schedule(payload, "1") == []


def test_daily_team_snapshot_is_immutable_and_contains_model_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DATA", tmp_path)
    teams = [{
        "abbreviation": "BOS",
        "seasons": {"2027": {
            "summary": {"games": 1},
            "games": [{
                "game_id": "g1", "date": "2026-11-20T00:00Z",
                "points_for": 110, "points_against": 105,
                "pace_estimate": 98.5, "offensive_rating": 112.0,
                "defensive_rating": 106.6, "rest_days": 1,
            }],
        }},
    }]
    module.write_immutable_team_snapshot(teams)
    path = next((tmp_path / "snapshots").glob("team-metrics-*.json"))
    first = path.read_text(encoding="utf-8")
    teams[0]["seasons"]["2027"]["games"][0]["points_for"] = 999
    module.write_immutable_team_snapshot(teams)
    assert path.read_text(encoding="utf-8") == first
    import json
    payload = json.loads(first)
    assert payload["teams"][0]["seasons"]["2027"]["games"][0]["pace_estimate"] == 98.5


def test_travel_distance_uses_arena_coordinates_and_road_trip_streak():
    atl = {"latitude": 33.7573, "longitude": -84.3963}
    bos = {"latitude": 42.3662, "longitude": -71.0621}
    distance = module.haversine_miles(atl, bos)
    assert 900 < distance < 1000
    rows = [
        {"home_away": "home", "opponent": "BOS"},
        {"home_away": "away", "opponent": "ATL"},
        {"home_away": "away", "opponent": "NYK"},
        {"home_away": "home", "opponent": "MIA"},
    ]
    module.enrich_schedule_travel("ATL", rows, {"ATL": atl, "BOS": bos, "NYK": bos})
    assert rows[1]["travel_miles"] == round(distance, 1)
    assert rows[1]["road_trip_games"] == 1
    assert rows[2]["road_trip_games"] == 2
    assert rows[3]["road_trip_games"] == 0

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
        "status": {"type": {"completed": True, "state": "post"}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": "13", "abbreviation": "LAL"}, "score": "108"},
            {"homeAway": "away", "team": {"id": "2", "abbreviation": "BOS"}, "score": "102"},
        ]}],
    }]}
    rows = module.parse_team_schedule(payload, "13")
    assert len(rows) == 1
    assert rows[0]["points_for"] == 108






def test_team_id_canonicalization_handles_espn_short_abbreviations():
    payload = {"events": [{
        "id": "g4", "date": "2026-11-20T00:00Z",
        "status": {"type": {"completed": True}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": "18", "abbreviation": "NY"}, "score": "115"},
            {"homeAway": "away", "team": {"id": "3", "abbreviation": "NO"}, "score": "109"},
        ]}],
    }]}
    rows = module.parse_team_schedule(payload, "18")
    assert rows[0]["team"] == "NYK"
    assert rows[0]["opponent"] == "NOP"


def test_date_values_includes_both_endpoints():
    from datetime import date
    assert [d.isoformat() for d in module._date_values(date(2026, 10, 1), date(2026, 10, 3))] == [
        "2026-10-01", "2026-10-02", "2026-10-03"
    ]


def test_scoreboard_fallback_builds_team_rows(monkeypatch):
    from datetime import date
    season = module.datetime.now(module.timezone.utc).year + 1
    monkeypatch.setattr(module, "_date_values", lambda start, end: [date(start.year, start.month, start.day)])
    payload = {"events": [{
        "id": "scoreboard-game", "date": "2026-11-20T00:00Z",
        "status": {"type": {"completed": True, "state": "post"}},
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": "18", "abbreviation": "NY"}, "score": "115"},
            {"homeAway": "away", "team": {"id": "3", "abbreviation": "NO"}, "score": "109"},
        ]}],
    }]}
    monkeypatch.setattr(module, "get_json", lambda url, params=None: payload)
    grouped = module.fetch_season_from_scoreboard(season)
    assert grouped["NYK"][0]["points_for"] == 115
    assert grouped["NOP"][0]["points_against"] == 115
