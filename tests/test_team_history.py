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
        {"home_away": "away", "opponent": "BOS"},
        {"home_away": "away", "opponent": "NYK"},
        {"home_away": "home", "opponent": "MIA"},
    ]
    module.enrich_schedule_travel("ATL", rows, {"ATL": atl, "BOS": bos, "NYK": bos})
    assert rows[1]["travel_miles"] == round(distance, 1)
    assert rows[1]["road_trip_games"] == 1
    assert rows[2]["road_trip_games"] == 2
    assert rows[3]["road_trip_games"] == 0


def test_arena_coordinate_file_covers_all_30_current_teams():
    import json
    from pathlib import Path
    arena_path = Path(module.__file__).parents[1] / "data" / "arenas.json"
    payload = json.loads(arena_path.read_text(encoding="utf-8"))
    assert len(payload["teams"]) == 30
    assert all(-90 <= row["latitude"] <= 90 and -180 <= row["longitude"] <= 180
               for row in payload["teams"].values())

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


def test_multiseason_fetch_uses_one_team_schedule_request_per_team(monkeypatch):
    calls = []
    def fake_get_json(url, params):
        calls.append((url, params))
        team_id = url.rsplit("/", 2)[-2]
        opponent_id = "2" if team_id != "2" else "1"
        abbreviation = module.ID_TO_TEAM[team_id]
        opponent_abbreviation = module.ID_TO_TEAM[opponent_id]
        events = []
        for index in range(6):
            events.append({
                "id": f"schedule-game-{team_id}-{index}",
                "date": f"2026-11-{20-index:02d}T00:00Z",
                "status": {"type": {"completed": True, "state": "post"}},
                "competitions": [{"competitors": [
                    {"homeAway": "home", "team": {"id": team_id, "abbreviation": abbreviation}, "score": "110"},
                    {"homeAway": "away", "team": {"id": opponent_id, "abbreviation": opponent_abbreviation}, "score": "105"},
                ]}],
            })
        return {"events": events}
    monkeypatch.setattr(module, "get_json", fake_get_json)
    grouped = module.fetch_season_from_team_schedules(2027)
    assert len(calls) == 30
    assert len(grouped) == 30
    assert len(grouped["ATL"]) == 6
    assert grouped["ATL"][0]["points_for"] == 110

def test_schedule_collection_falls_back_to_scoreboard_when_season_is_empty(monkeypatch):
    from datetime import date
    season = module.datetime.now(module.timezone.utc).year + 1
    monkeypatch.setattr(module, "_date_values", lambda start, end: [date(start.year, start.month, start.day)])
    def fake_get_json(url, params=None):
        if "/teams/" in url:
            return {"events": []}
        return {"events": [{
            "id": "fallback-game", "date": "2026-11-20T00:00Z",
            "status": {"type": {"completed": True, "state": "post"}},
            "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"id": "18", "abbreviation": "NY"}, "score": "115"},
                {"homeAway": "away", "team": {"id": "3", "abbreviation": "NO"}, "score": "109"},
            ]}],
        }]}
    monkeypatch.setattr(module, "get_json", fake_get_json)
    grouped = module.fetch_season_from_team_schedules(season)
    assert grouped["NYK"][0]["points_for"] == 115
    assert grouped["NOP"][0]["points_against"] == 115


def test_reconcile_missing_opponent_record_uses_reciprocal_score_and_venue():
    grouped = {
        "BOS": [{
            "game_id": "g-repair", "date": "2026-11-20T00:00Z",
            "team": "BOS", "opponent": "LAL", "opponent_name": "Los Angeles Lakers",
            "home_away": "home", "points_for": 112, "points_against": 104,
            "win": True, "result": "W",
        }],
        "LAL": [],
    }
    assert module.reconcile_missing_opponent_records(grouped) == 1
    mirror = grouped["LAL"][0]
    assert mirror["game_id"] == "g-repair"
    assert mirror["team"] == "LAL" and mirror["opponent"] == "BOS"
    assert mirror["home_away"] == "away"
    assert mirror["points_for"] == 104 and mirror["points_against"] == 112
    assert mirror["win"] is False and mirror["result"] == "L"


def test_reconcile_does_not_overwrite_existing_opponent_record():
    grouped = {
        "BOS": [{"game_id":"g-existing","team":"BOS","opponent":"LAL","home_away":"home","points_for":112,"points_against":104}],
        "LAL": [{"game_id":"g-existing","team":"LAL","opponent":"BOS","home_away":"away","points_for":104,"points_against":112}],
    }
    assert module.reconcile_missing_opponent_records(grouped) == 0
    assert len(grouped["LAL"]) == 1



def test_merge_cached_boxscore_metrics_preserves_verified_history():
    cached = [{
        "abbreviation": "BOS",
        "seasons": {"2026": {"games": [{
            "game_id": "cached-game", "possessions_estimate": 98.5,
            "pace_estimate": 99.2, "offensive_rating": 114.0,
            "defensive_rating": 108.0,
            "advanced_stats_source": "ESPN boxscore",
        }]}},
    }]
    refreshed = [{
        "abbreviation": "BOS",
        "seasons": {"2026": {"games": [
            {"game_id": "cached-game", "points_for": 112},
            {"game_id": "new-game", "points_for": 108},
        ]}},
    }]
    restored = module.merge_cached_boxscore_metrics(cached, refreshed)
    assert restored == 1
    row = refreshed[0]["seasons"]["2026"]["games"][0]
    assert row["pace_estimate"] == 99.2
    assert row["offensive_rating"] == 114.0
    assert "pace_estimate" not in refreshed[0]["seasons"]["2026"]["games"][1]


def test_boxscore_enrichment_prioritizes_missing_games_and_skips_complete(monkeypatch):
    fields = {
        "possessions_estimate": 98.0, "pace_estimate": 99.0,
        "offensive_rating": 112.0, "defensive_rating": 108.0,
        "advanced_stats_source": "ESPN boxscore",
    }
    teams = []
    for abbreviation, opponent in (("BOS", "LAL"), ("LAL", "BOS")):
        games = []
        for game_id, date in (
            ("old-missing", "2026-10-01T00:00Z"),
            ("complete", "2026-10-02T00:00Z"),
            ("new-missing", "2026-10-03T00:00Z"),
        ):
            row = {"game_id": game_id, "date": date, "team": abbreviation,
                   "opponent": opponent, "points_for": 110, "points_against": 105}
            if game_id == "complete":
                row.update(fields)
            games.append(row)
        teams.append({"abbreviation": abbreviation,
                      "seasons": {"2027": {"games": games}}})

    calls = []
    def fake_get_json(url, params):
        calls.append(params["event"])
        def box(abbreviation):
            return {"team": {"abbreviation": abbreviation}, "statistics": [
                {"name": "fieldGoalsMade-fieldGoalsAttempted", "displayValue": "40-85"},
                {"name": "freeThrowsMade-freeThrowsAttempted", "displayValue": "18-22"},
                {"name": "offensiveRebounds", "displayValue": "10"},
                {"name": "totalTurnovers", "displayValue": "12"},
            ]}
        return {"boxscore": {"teams": [box("BOS"), box("LAL")]}}

    monkeypatch.setattr(module, "get_json", fake_get_json)
    module.enrich_team_games_with_boxscores(teams, {"2027"}, max_games=1)
    assert calls == ["new-missing"]
    for team in teams:
        rows = {row["game_id"]: row for row in team["seasons"]["2027"]["games"]}
        assert rows["complete"]["pace_estimate"] == 99.0
        assert rows["new-missing"]["pace_estimate"] is not None
        assert "pace_estimate" not in rows["old-missing"]
