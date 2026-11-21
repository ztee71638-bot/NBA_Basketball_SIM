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


def test_backtest_uses_only_prior_games_and_reports_metrics():
    team_a, team_b = [], []
    for index in range(30):
        date = f"2026-10-{index + 1:02d}T00:00:00+00:00" if index < 22 else f"2026-11-{index - 21:02d}T00:00:00+00:00"
        game_id = f"prior-{index}"
        team_a.append({
            "game_id": game_id, "date": date, "team": "AAA",
            "home_away": "home", "points_for": 112 + index % 4,
            "points_against": 105 + index % 3,
        })
        team_b.append({
            "game_id": game_id, "date": date, "team": "BBB",
            "home_away": "away", "points_for": 105 + index % 3,
            "points_against": 112 + index % 4,
        })
    target_date = "2026-11-20T00:00:00+00:00"
    team_a.append({"game_id": "target", "date": target_date, "team": "AAA",
                   "home_away": "home", "points_for": 114, "points_against": 108})
    team_b.append({"game_id": "target", "date": target_date, "team": "BBB",
                   "home_away": "away", "points_for": 108, "points_against": 114})
    payload = {"teams": [
        {"abbreviation": "AAA", "seasons": {"2027": {"games": team_a}}},
        {"abbreviation": "BBB", "seasons": {"2027": {"games": team_b}}},
    ]}
    result = module.run_backtest(payload)
    assert result["games_tested"] == 1
    assert "model_score_mae" in result
    assert "model_brier_score" in result
