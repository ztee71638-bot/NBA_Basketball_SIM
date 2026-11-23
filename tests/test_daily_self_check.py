import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "daily_self_check.py"
spec = importlib.util.spec_from_file_location("daily_self_check", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_parse_events_extracts_home_away_and_final_status():
    payload = {"events": [{"id": "g1", "date": "2026-11-23T19:00Z", "competitions": [{
        "status": {"type": {"state": "post", "completed": True}},
        "competitors": [
            {"homeAway": "home", "score": "110", "team": {"abbreviation": "GS"}},
            {"homeAway": "away", "score": "105", "team": {"abbreviation": "BOS"}},
        ],
    }]}]}
    game = module.parse_events(payload)[0]
    assert game["home_team"] == "GSW"
    assert game["away_team"] == "BOS"
    assert game["completed"] is True
    assert game["home_score"] == 110


def test_reconcile_only_scores_completed_games_and_is_idempotent():
    record = {"home_team": "BOS", "away_team": "NYK", "predicted_winner": "BOS",
              "predicted_home_score": 111.0, "predicted_away_score": 105.0,
              "home_win_probability": 0.7, "actual": None, "prediction_status": "pregame"}
    assert not module.reconcile_record(record, {"completed": False, "home_score": 0, "away_score": 0})
    assert module.reconcile_record(record, {"completed": True, "home_score": 110, "away_score": 108})
    assert record["evaluation"]["winner_correct"] is True
    assert record["evaluation"]["home_score_absolute_error"] == 1.0
    assert not module.reconcile_record(record, {"completed": True, "home_score": 99, "away_score": 100})


def test_summary_excludes_pending_games():
    records = [
        {"prediction_status": "pregame", "evaluation": None},
        {"prediction_status": "final", "evaluation": {"winner_correct": True,
         "home_score_absolute_error": 2, "away_score_absolute_error": 4,
         "combined_score_absolute_error": 6, "brier_score": 0.09}},
    ]
    result = module.summarize(records)
    assert result["predictions_saved"] == 2
    assert result["games_evaluated"] == 1
    assert result["winner_accuracy"] == 1.0
    assert result["pending_results"] == 1


def test_prediction_never_uses_game_actual_score():
    game = {"game_id": "g1", "home_team": "BOS", "away_team": "NYK",
            "home_score": 140, "away_score": 90, "completed": False, "date": "2026-11-24"}
    rows = {"BOS": [{"points_for": 110+i, "points_against": 105} for i in range(10)],
            "NYK": [{"points_for": 105+i, "points_against": 110} for i in range(10)]}
    prediction = module.make_prediction(game, rows, {}, "2026-11-24T00:00:00+00:00")
    assert prediction is not None
    assert prediction["actual"] is None
    assert "home_score" not in prediction



def test_parse_events_falls_back_to_event_status_when_competition_status_is_empty():
    payload = {"events": [{"id": "g2", "date": "2026-11-24T19:00Z",
        "status": {"type": {"state": "post", "completed": True}},
        "competitions": [{"status": {}, "competitors": [
            {"homeAway": "home", "score": "108", "team": {"abbreviation": "BOS"}},
            {"homeAway": "away", "score": "102", "team": {"abbreviation": "NYK"}},
        ]}]}]}
    game = module.parse_events(payload)[0]
    assert game["status"] == "post"
    assert game["completed"] is True
