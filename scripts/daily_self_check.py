"""Daily live prediction ledger and post-game results reconciliation.

Predictions are immutable once a game starts. Final scores are attached only
after ESPN marks the event completed. Missing data is reported, never scored.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from urllib.request import Request, urlopen
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_model import apply_probability_calibration, predict

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LEDGER = DATA / "daily_predictions.json"
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
ALIASES = {"GS": "GSW", "NY": "NYK", "NO": "NOP", "SA": "SAS", "WSH": "WAS"}


def fetch_scoreboard(day: str) -> dict:
    request = Request(f"{SCOREBOARD}?dates={day}", headers={"User-Agent": "NBA-Simulator/1.0"})
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def team_rows(payload: dict) -> dict[str, list[dict]]:
    result = {}
    for team in payload.get("teams", []):
        rows = []
        for season in team.get("seasons", {}).values():
            rows.extend(season.get("games", []))
        rows.sort(key=lambda row: row.get("date", ""))
        result[team.get("abbreviation")] = rows
    return result


def parse_events(payload: dict) -> list[dict]:
    parsed = []
    for event in payload.get("events", []):
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        competition = competitions[0]
        competitors = competition.get("competitors") or []
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        event_status = (event.get("status") or {}).get("type") or {}
        competition_status = (competition.get("status") or {}).get("type") or {}
        status = {**event_status, **competition_status}
        parsed.append({
            "game_id": str(event.get("id") or competition.get("id") or ""),
            "date": event.get("date") or competition.get("date"),
            "home_team": ALIASES.get(home.get("team", {}).get("abbreviation"), home.get("team", {}).get("abbreviation")),
            "away_team": ALIASES.get(away.get("team", {}).get("abbreviation"), away.get("team", {}).get("abbreviation")),
            "home_score": _score(home.get("score")),
            "away_score": _score(away.get("score")),
            "status": status.get("state", ""),
            "completed": bool(status.get("completed")) or status.get("state") == "post",
        })
    return [game for game in parsed if game["game_id"] and game["home_team"] and game["away_team"]]


def _score(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def make_prediction(game: dict, rows_by_team: dict, metrics: dict, generated_at: str) -> dict | None:
    home_rows = rows_by_team.get(game["home_team"], [])
    away_rows = rows_by_team.get(game["away_team"], [])
    if len(home_rows) < 5 or len(away_rows) < 5:
        return None
    league_values = [
        float(row["points_for"])
        for rows in rows_by_team.values() for row in rows
        if isinstance(row.get("points_for"), (int, float)) and row["points_for"] > 0
    ]
    if not league_values:
        return None
    league_average = mean(league_values)
    league_sd = (sum((value - league_average) ** 2 for value in league_values) / len(league_values)) ** 0.5
    projection = predict(home_rows, away_rows, league_average, league_sd)
    if not projection:
        return None
    home_points, away_points, raw_probability = projection
    calibration = metrics.get("opponent_model_calibration") or {}
    probability = apply_probability_calibration(raw_probability, calibration) if calibration.get("live_enabled") else raw_probability
    return {
        "game_id": game["game_id"], "game_date": game.get("date"),
        "home_team": game["home_team"], "away_team": game["away_team"],
        "predicted_home_score": round(home_points, 2),
        "predicted_away_score": round(away_points, 2),
        "predicted_winner": game["home_team"] if probability >= 0.5 else game["away_team"],
        "home_win_probability": round(probability, 6),
        "confidence": round(max(probability, 1 - probability), 6),
        "model_version": metrics.get("model_version", "opponent-weighted-score-v1"),
        "created_at": generated_at,
        "prediction_status": "pregame",
        "actual": None,
        "evaluation": None,
    }


def reconcile_record(record: dict, game: dict) -> bool:
    if not game.get("completed") or game.get("home_score") is None or game.get("away_score") is None:
        return False
    if record.get("actual") is not None:
        return False
    home_score, away_score = game["home_score"], game["away_score"]
    actual_winner = record["home_team"] if home_score > away_score else record["away_team"] if away_score > home_score else "tie"
    record["actual"] = {
        "home_score": home_score, "away_score": away_score,
        "winner": actual_winner, "finalized_at": datetime.now(timezone.utc).isoformat(),
        "source": "ESPN scoreboard",
    }
    record["evaluation"] = {
        "winner_correct": record["predicted_winner"] == actual_winner,
        "home_score_absolute_error": round(abs(record["predicted_home_score"] - home_score), 2),
        "away_score_absolute_error": round(abs(record["predicted_away_score"] - away_score), 2),
        "combined_score_absolute_error": round(abs(record["predicted_home_score"] - home_score) + abs(record["predicted_away_score"] - away_score), 2),
        "brier_score": round((record["home_win_probability"] - (1.0 if actual_winner == record["home_team"] else 0.0)) ** 2, 6) if actual_winner != "tie" else None,
    }
    record["prediction_status"] = "final"
    return True


def summarize(records: list[dict]) -> dict:
    evaluated = [r for r in records if r.get("evaluation")]
    result = {"predictions_saved": len(records), "games_evaluated": len(evaluated),
              "pending_results": sum(1 for r in records if r.get("prediction_status") == "pregame")}
    if evaluated:
        result.update({
            "winner_accuracy": round(mean(float(r["evaluation"]["winner_correct"]) for r in evaluated), 4),
            "home_score_mae": round(mean(r["evaluation"]["home_score_absolute_error"] for r in evaluated), 3),
            "away_score_mae": round(mean(r["evaluation"]["away_score_absolute_error"] for r in evaluated), 3),
            "combined_score_mae_per_team": round(mean(r["evaluation"]["combined_score_absolute_error"] / 2 for r in evaluated), 3),
            "brier_score": round(mean(r["evaluation"]["brier_score"] for r in evaluated if r["evaluation"]["brier_score"] is not None), 4) if any(r["evaluation"]["brier_score"] is not None for r in evaluated) else None,
        })
    return result


def run(ledger_path: Path = LEDGER, data_dir: Path = DATA, scoreboard_fetcher=fetch_scoreboard) -> dict:
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {
        "schema_version": 1, "created_at": stamp, "source": "ESPN scoreboard",
        "records": [], "daily": {}, "overall": {},
    }
    by_id = {str(r["game_id"]): r for r in ledger.get("records", [])}
    teams_path = data_dir / "teams.json"
    metrics_path = data_dir / "model_metrics.json"
    teams = json.loads(teams_path.read_text()) if teams_path.exists() else {"teams": []}
    metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else {}
    rows = team_rows(teams)
    # Previous/current/next UTC scoreboard dates cover overnight NBA schedules.
    dates = [(now + timedelta(days=offset)).strftime("%Y%m%d") for offset in (-1, 0, 1)]
    seen = 0
    changed = False
    for day in dates:
        for game in parse_events(scoreboard_fetcher(day)):
            seen += 1
            existing = by_id.get(game["game_id"])
            if existing:
                changed = reconcile_record(existing, game) or changed
                continue
            # Unknown status is not proof that a game is upcoming. Only save
            # predictions when ESPN explicitly marks the event as pregame.
            if game["completed"] or game["status"] != "pre":
                continue
            prediction = make_prediction(game, rows, metrics, stamp)
            if prediction:
                by_id[game["game_id"]] = prediction
                changed = True
    records = sorted(by_id.values(), key=lambda r: (r.get("game_date") or "", r["game_id"]))
    daily = {}
    for record in records:
        key = (record.get("game_date") or "unknown")[:10]
        daily.setdefault(key, []).append(record)
    daily_summary = {day: summarize(items) for day, items in sorted(daily.items())}
    overall_summary = summarize(records)
    def within_days(record: dict, days: int) -> bool:
        try:
            game_time = datetime.fromisoformat(str(record.get("game_date", "")).replace("Z", "+00:00"))
            if game_time.tzinfo is None:
                game_time = game_time.replace(tzinfo=timezone.utc)
            return now - timedelta(days=days) <= game_time <= now
        except (TypeError, ValueError):
            return False
    rolling_summary = {
        "7d": summarize([record for record in records if within_days(record, 7)]),
        "30d": summarize([record for record in records if within_days(record, 30)]),
    }
    # Persist only meaningful ledger changes. Hourly heartbeat timestamps are
    # printed to Actions logs but must not create a commit when no game data or
    # rolling-window summary has changed.
    ledger_changed = (
        changed
        or ledger.get("daily") != daily_summary
        or ledger.get("overall") != overall_summary
        or ledger.get("rolling") != rolling_summary
        or not ledger_path.exists()
    )
    last_run = {"at": stamp, "scoreboard_dates_checked": dates, "events_seen": seen}
    if ledger_changed:
        ledger["updated_at"] = stamp
        ledger["records"] = records
        ledger["daily"] = daily_summary
        ledger["overall"] = overall_summary
        ledger["rolling"] = rolling_summary
        ledger["last_run"] = last_run
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "last_run": last_run,
        "ledger_changed": ledger_changed,
        "overall": overall_summary,
        "rolling": rolling_summary,
    }, indent=2))
    return ledger


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument("--data-dir", type=Path, default=DATA)
    args = parser.parse_args()
    run(args.ledger, args.data_dir)
