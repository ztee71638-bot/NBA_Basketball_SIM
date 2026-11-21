import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "reconcile_supplemental_nba_stats.py"
spec = importlib.util.spec_from_file_location("reconcile_supplemental_nba_stats", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def team_fixture():
    return {
        "teams": [
            {"abbreviation": "AAA", "seasons": {"2026": {"games": [{
                "game_id": "g1", "date": "2026-01-01T00:00:00Z",
                "opponent": "BBB", "points_for": 110, "points_against": 100,
                "possessions_estimate": None, "pace_estimate": None,
                "offensive_rating": None, "defensive_rating": None,
            }]}}},
            {"abbreviation": "BBB", "seasons": {"2026": {"games": [{
                "game_id": "g1", "date": "2026-01-01T00:00:00Z",
                "opponent": "AAA", "points_for": 100, "points_against": 110,
                "possessions_estimate": None, "pace_estimate": None,
                "offensive_rating": None, "defensive_rating": None,
            }]}}},
        ]
    }


def source_fixture():
    common = {
        "season": "2025-26", "game_date": "2026-01-01",
        "field_goal_attempts": "80", "offensive_rebounds": "10",
        "turnovers": "12", "free_throw_attempts": "20",
        "field_goals_made": "40", "three_point_makes": "10",
        "three_point_attempts": "25", "free_throws_made": "20",
        "defensive_rebounds": "30", "rebounds": "40", "assists": "25",
        "steals": "5", "blocks": "4",
    }
    return [
        {**common, "team": "AAA", "opponent": "BBB", "points": "110", "opponent_points": "100"},
        {**common, "team": "BBB", "opponent": "AAA", "points": "100", "opponent_points": "110",
         "field_goal_attempts": "85", "offensive_rebounds": "8", "turnovers": "15",
         "free_throw_attempts": "18"},
    ]


def test_exact_two_sided_score_match_enriches_only_missing_canonical_fields():
    teams = team_fixture()
    report = module.reconcile_team_games(teams, {"2025-26": source_fixture()})
    first = teams["teams"][0]["seasons"]["2026"]["games"][0]
    assert report["matched_rows"] == 2
    assert report["unmatched_rows"] == 0
    assert report["advanced_rows_added"] == 2
    assert first["possessions_estimate"] == 90.8
    assert first["pace_estimate"] == round((90.8 + (85 - 8 + 15 + 0.44 * 18)) / 2, 2)
    assert first["supplemental_boxscore"]["provider"] == "BoxScore Lab"


def test_existing_canonical_metrics_are_never_overwritten():
    teams = team_fixture()
    row = teams["teams"][0]["seasons"]["2026"]["games"][0]
    row.update({
        "possessions_estimate": 95.0, "pace_estimate": 96.0,
        "offensive_rating": 115.0, "defensive_rating": 105.0,
        "advanced_stats_source": "ESPN boxscore",
    })
    module.reconcile_team_games(teams, {"2025-26": source_fixture()})
    assert row["possessions_estimate"] == 95.0
    assert row["pace_estimate"] == 96.0
    assert row["offensive_rating"] == 115.0
    assert row["advanced_stats_source"] == "ESPN boxscore"


def test_score_mismatch_is_reported_and_not_fuzzy_merged():
    teams = team_fixture()
    rows = source_fixture()
    rows[0]["points"] = "111"
    report = module.reconcile_team_games(teams, {"2025-26": rows})
    assert report["score_or_key_mismatches"] == 1
    assert report["advanced_rows_added"] == 0


def test_player_totals_match_by_name_and_season_team():
    players = {"players": [{
        "id": "123", "name": "Test Player",
        "teams_by_season": {"2026": ["BOS"]},
    }]}
    source = [{
        "player_name": "Test Player", "team": "BOS", "games_played": "60",
        "points": "1200", "points_pg": "20", "ts_pct": "0.61",
        "usage_rate": "0.25",
    }]
    report = module.reconcile_player_totals(players, {"2025-26": source})
    totals = players["players"][0]["season_advanced_totals"]["2026"]
    assert report["matched_rows"] == 1
    assert totals[0]["points"] == 1200.0
    assert totals[0]["ts_pct"] == 0.61
