import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "backtest_model.py"
spec = importlib.util.spec_from_file_location("backtest_model", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_weighted_stats_prefers_recent_games():
    rows = [{"points_for": 100}, {"points_for": 100}, {"points_for": 130}]
    result = module.weighted_stats(rows, "points_for", half_life=1)
    assert result is not None
    assert result[0] > 110


def test_predict_returns_finite_matchup_estimates():
    rows = [{"points_for": 115 + i, "points_against": 108 + i % 3} for i in range(8)]
    result = module.predict(rows, rows[::-1], 112, 12)
    assert result is not None
    assert len(result) == 3
    assert 0 < result[2] < 1




def test_expected_calibration_error_is_zero_for_perfect_calibration():
    probabilities = [0.0, 0.0, 1.0, 1.0]
    outcomes = [0.0, 0.0, 1.0, 1.0]
    assert module.expected_calibration_error(probabilities, outcomes) == 0.0

def test_advanced_efficiency_prediction_uses_pace_and_efficiency_history():
    home = [{
        "points_for": 118, "offensive_rating": 118.0, "defensive_rating": 110.0,
        "pace_estimate": 100.0
    } for _ in range(12)]
    away = [{
        "points_for": 108, "offensive_rating": 108.0, "defensive_rating": 116.0,
        "pace_estimate": 98.0
    } for _ in range(12)]
    result = module.predict_advanced(home, away, 99.0, 113.0, 113.0)
    assert result is not None
    home_points, away_points, home_probability, pace = result
    assert home_points > away_points
    assert 0 < home_probability < 1
    assert 0 < pace < 120


def test_backtest_travel_and_rest_use_only_pre_game_schedule():
    from datetime import datetime, timezone
    cutoff = datetime.fromisoformat("2026-11-20T00:00:00+00:00")
    rows = [
        {"date": "2026-11-19T00:00:00+00:00", "home_away": "home", "opponent": "BOS"},
    ]
    arenas = {
        "ATL": {"latitude": 33.7573, "longitude": -84.3963},
        "BOS": {"latitude": 42.3662, "longitude": -71.0621},
    }
    assert module.current_rest_days(rows, cutoff) == 0
    miles = module.current_travel_miles(rows, "ATL", "BOS", "away", cutoff, arenas)
    assert miles > 900


def test_backtest_uses_only_prior_games_and_reports_metrics():
    team_a, team_b = [], []
    for index in range(30):
        date = f"2026-10-{index + 1:02d}T00:00:00+00:00" if index < 22 else f"2026-11-{index - 21:02d}T00:00:00+00:00"
        game_id = f"prior-{index}"
        team_a.append({
            "game_id": game_id, "date": date, "team": "AAA", "opponent": "BBB",
            "home_away": "home", "points_for": 112 + index % 4,
            "points_against": 105 + index % 3,
        })
        team_b.append({
            "game_id": game_id, "date": date, "team": "BBB", "opponent": "AAA",
            "home_away": "away", "points_for": 105 + index % 3,
            "points_against": 112 + index % 4,
        })
    target_date = "2026-11-20T00:00:00+00:00"
    team_a.append({"game_id": "target", "date": target_date, "team": "AAA", "opponent": "BBB",
                   "home_away": "home", "points_for": 114, "points_against": 108})
    team_b.append({"game_id": "target", "date": target_date, "team": "BBB", "opponent": "AAA",
                   "home_away": "away", "points_for": 108, "points_against": 114})
    payload = {"teams": [
        {"abbreviation": "AAA", "seasons": {"2027": {"games": team_a}}},
        {"abbreviation": "BBB", "seasons": {"2027": {"games": team_b}}},
    ]}
    result = module.run_backtest(payload)
    assert result["games_tested"] == 1
    assert "model_score_mae" in result
    assert "model_brier_score" in result
    assert result["by_season"]["2027"]["games"] == 1
    assert sum(bucket["games"] for bucket in result["production_baseline_confidence_buckets"]) == 1




def test_confidence_buckets_report_sample_size_accuracy_and_brier():
    report = module.probability_bucket_report(
        [0.72, 0.68, 0.31, 0.27],
        [1.0, 0.0, 0.0, 1.0],
    )
    assert sum(bucket["games"] for bucket in report) == 4
    assert report[0]["confidence_range"] == "65%-70%"
    assert report[0]["games"] == 2
    assert report[0]["observed_accuracy"] == 0.5
    assert report[0]["brier_score"] == 0.2122


def test_logistic_probability_calibration_corrects_overconfidence():
    probabilities = [0.8] * 100 + [0.2] * 100
    outcomes = [1.0] * 60 + [0.0] * 40 + [1.0] * 40 + [0.0] * 60
    calibration = module.fit_probability_calibrator(probabilities, outcomes)
    high = module.apply_probability_calibration(0.8, calibration)
    low = module.apply_probability_calibration(0.2, calibration)
    raw_brier = sum((p-y)**2 for p,y in zip(probabilities,outcomes))/len(outcomes)
    calibrated_brier = sum((module.apply_probability_calibration(p,calibration)-y)**2
                           for p,y in zip(probabilities,outcomes))/len(outcomes)
    assert calibration["enabled"] is True
    assert 0.54 < high < 0.66
    assert 0.34 < low < 0.46
    assert calibrated_brier < raw_brier


def test_calibrator_uses_identity_until_minimum_history_is_available():
    calibration = module.fit_probability_calibrator([0.8] * 20, [1.0] * 20)
    assert calibration["enabled"] is False
    assert module.apply_probability_calibration(0.8, calibration) == 0.8


def test_backtest_excludes_non_nba_exhibition_games_from_team_baselines():
    team_a, team_b = [], []
    for index in range(30):
        date = f"2026-10-{index + 1:02d}T00:00:00+00:00" if index < 22 else f"2026-11-{index - 21:02d}T00:00:00+00:00"
        game_id = f"prior-{index}"
        team_a.append({"game_id":game_id,"date":date,"home_away":"home","opponent":"BBB",
                       "points_for":112,"points_against":105})
        team_b.append({"game_id":game_id,"date":date,"home_away":"away","opponent":"AAA",
                       "points_for":105,"points_against":112})
    target_date = "2026-11-20T00:00:00+00:00"
    team_a.append({"game_id":"target","date":target_date,"home_away":"home","opponent":"BBB",
                   "points_for":114,"points_against":108})
    team_b.append({"game_id":"target","date":target_date,"home_away":"away","opponent":"AAA",
                   "points_for":108,"points_against":114})
    team_a.append({"game_id":"exhibition-only","date":"2026-10-10T00:00:00+00:00",
                   "home_away":"home","opponent":"ADL","points_for":140,"points_against":70})
    payload={"teams":[
        {"abbreviation":"AAA","seasons":{"2027":{"games":team_a}}},
        {"abbreviation":"BBB","seasons":{"2027":{"games":team_b}}},
    ]}
    result=module.run_backtest(payload)
    assert result["games_tested"] == 1
    assert result["excluded_non_nba_opponent_rows"] == 1


def test_browser_baseline_probability_uses_recent_team_profiles_and_shared_shock():
    rows_a = [
        {"date": f"2026-10-{day:02d}T00:00:00+00:00", "season": "2027",
         "points_for": 110 + day % 3, "points_against": 104 + day % 2}
        for day in range(1, 13)
    ]
    rows_b = [
        {"date": f"2026-10-{day:02d}T00:00:00+00:00", "season": "2027",
         "points_for": 106 + day % 2, "points_against": 112 + day % 3}
        for day in range(1, 13)
    ]
    league = [
        {"date": row["date"], "points_for": value}
        for row in rows_a + rows_b
        for value in [row["points_for"]]
    ]
    probability = module.browser_baseline_probability(rows_a, rows_b, league)
    assert probability is not None
    assert 0.5 < probability < 1.0


def test_browser_team_profile_rows_excludes_future_and_keeps_only_prior_season_tail():
    rows = []
    for season in ("2025", "2026", "2027"):
        for day in range(1, 13):
            rows.append({"season": season, "date": f"{int(season)-1}-10-{day:02d}T00:00:00+00:00"})
    profile = module.browser_team_profile_rows(rows[:-2])
    assert len(profile) == 20
    assert {row["season"] for row in profile} == {"2026", "2027"}
