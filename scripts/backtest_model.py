"""Strict walk-forward backtest for the NBA score projection model.

Only games dated before each test game are used to build team and league
baselines. The script reports prediction errors; it does not tune parameters
on the test results or claim that a small sample is calibrated.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "teams.json"
ARENAS_PATH = ROOT / "data" / "arenas.json"


def parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def weighted_stats(rows: list[dict[str, Any]], key: str, half_life: float = 8.0):
    values = [(float(row[key]), len(rows) - 1 - index)
              for index, row in enumerate(rows)
              if isinstance(row.get(key), (int, float))]
    if not values:
        return None
    weights = [0.5 ** (age / half_life) for _, age in values]
    total = sum(weights)
    avg = sum(value * weight for (value, _), weight in zip(values, weights)) / total
    variance = sum(weight * (value - avg) ** 2
                   for (value, _), weight in zip(values, weights)) / total
    return avg, math.sqrt(variance), len(values)


def predict(home_rows, away_rows, league_average, league_sd):
    home_off = weighted_stats(home_rows, "points_for")
    home_def = weighted_stats(home_rows, "points_against")
    away_off = weighted_stats(away_rows, "points_for")
    away_def = weighted_stats(away_rows, "points_against")
    if not all((home_off, home_def, away_off, away_def)):
        return None
    def shrink(value, count):
        reliability = count / (count + 8)
        return league_average + (value - league_average) * reliability
    h_off, h_def = shrink(home_off[0], home_off[2]), shrink(home_def[0], home_def[2])
    a_off, a_def = shrink(away_off[0], away_off[2]), shrink(away_def[0], away_def[2])
    # Keep this calculation aligned with the browser model.
    home_mean = league_average + (h_off - league_average) * 0.55 + (a_def - league_average) * 0.45 + 1.8
    away_mean = league_average + (a_off - league_average) * 0.55 + (h_def - league_average) * 0.45
    def blended_sd(stats):
        reliability = stats[2] / (stats[2] + 10)
        return math.sqrt(reliability * stats[1] ** 2 + (1 - reliability) * league_sd ** 2)
    home_sd, away_sd = blended_sd(home_off), blended_sd(away_off)
    combined_sd = math.sqrt(home_sd ** 2 + away_sd ** 2)
    p_home = 0.5 * (1 + math.erf((home_mean - away_mean) / (math.sqrt(2) * combined_sd)))
    return home_mean, away_mean, p_home


def predict_advanced(home_rows, away_rows, league_pace, league_off_rating, league_def_rating,
                     home_rest_days: float = 1.0, away_rest_days: float = 1.0,
                     home_travel_miles: float = 0.0, away_travel_miles: float = 0.0):
    """Experimental efficiency/pace projection using only pregame team history."""
    h_off = weighted_stats(home_rows, "offensive_rating")
    h_def = weighted_stats(home_rows, "defensive_rating")
    a_off = weighted_stats(away_rows, "offensive_rating")
    a_def = weighted_stats(away_rows, "defensive_rating")
    h_pace = weighted_stats(home_rows, "pace_estimate")
    a_pace = weighted_stats(away_rows, "pace_estimate")
    if not all((h_off, h_def, a_off, a_def, h_pace, a_pace)):
        return None
    def shrink(value, count, baseline):
        reliability = count / (count + 10)
        return baseline + (value - baseline) * reliability
    home_off = shrink(h_off[0], h_off[2], league_off_rating)
    home_def = shrink(h_def[0], h_def[2], league_def_rating)
    away_off = shrink(a_off[0], a_off[2], league_off_rating)
    away_def = shrink(a_def[0], a_def[2], league_def_rating)
    pace = (shrink(h_pace[0], h_pace[2], league_pace) + shrink(a_pace[0], a_pace[2], league_pace)) / 2
    home_mean = ((home_off + away_def) / 2) * pace / 100 + 1.8
    away_mean = ((away_off + home_def) / 2) * pace / 100
    # Small, capped schedule effects are experimental and must beat the
    # no-adjustment baseline before any production promotion.
    def schedule_adjustment(rest_days, travel_miles):
        rest_bonus = max(-0.8, min(0.8, (float(rest_days)-1.0)*0.2))
        travel_penalty = max(0.0, min(1.2, float(travel_miles or 0.0)*0.00035))
        return rest_bonus-travel_penalty
    home_mean += schedule_adjustment(home_rest_days, home_travel_miles)
    away_mean += schedule_adjustment(away_rest_days, away_travel_miles)
    home_score_sd = weighted_stats(home_rows, "points_for")
    away_score_sd = weighted_stats(away_rows, "points_for")
    home_sd = home_score_sd[1] if home_score_sd else 12.0
    away_sd = away_score_sd[1] if away_score_sd else 12.0
    # Match the simulator's shared-environment shock (0.35 coefficient -> 0.1225 correlation).
    combined_sd = math.sqrt(max(1.0, home_sd ** 2 + away_sd ** 2 - 2 * 0.1225 * home_sd * away_sd))
    p_home = 0.5 * (1 + math.erf((home_mean-away_mean)/(math.sqrt(2)*max(8.0,combined_sd))))
    return home_mean, away_mean, p_home, pace


def current_rest_days(rows, cutoff):
    prior = [row for row in rows if parse_date(row["date"]) < cutoff]
    if not prior:
        return 1.0
    gap = (cutoff.date() - parse_date(prior[-1]["date"]).date()).days
    return float(max(0, gap - 1))


def current_travel_miles(rows, team_abbreviation, opponent_abbreviation, home_away, cutoff, arenas):
    prior = [row for row in rows if parse_date(row["date"]) < cutoff]
    if not prior:
        return 0.0
    aliases = {"GS":"GSW","NY":"NYK","NO":"NOP","SA":"SAS","WSH":"WAS"}
    team = aliases.get(team_abbreviation, team_abbreviation)
    opponent = aliases.get(opponent_abbreviation, opponent_abbreviation)
    previous = prior[-1]
    previous_opponent = aliases.get(previous.get("opponent"), previous.get("opponent"))
    origin_code = team if previous.get("home_away") == "home" else previous_opponent
    destination_code = team if home_away == "home" else opponent
    origin, destination = arenas.get(origin_code), arenas.get(destination_code)
    if not origin or not destination:
        return 0.0
    lat1, lon1 = math.radians(origin["latitude"]), math.radians(origin["longitude"])
    lat2, lon2 = math.radians(destination["latitude"]), math.radians(destination["longitude"])
    dlat, dlon = lat2-lat1, lon2-lon1
    value = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 3958.7613 * 2 * math.asin(math.sqrt(value))


def expected_calibration_error(probabilities, outcomes, bins: int = 10):
    if not probabilities:
        return None
    total = len(probabilities)
    error = 0.0
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        selected = [(p, y) for p, y in zip(probabilities, outcomes)
                    if lower <= p < upper or (index == bins-1 and p == 1.0)]
        if selected:
            confidence = mean(p for p, _ in selected)
            accuracy = mean(y for _, y in selected)
            error += len(selected) / total * abs(confidence-accuracy)
    return round(error, 4)



def _logit(probability: float) -> float:
    value = min(0.995, max(0.005, float(probability)))
    return math.log(value / (1.0 - value))


def _sigmoid(value: float) -> float:
    value = max(-30.0, min(30.0, float(value)))
    return 1.0 / (1.0 + math.exp(-value))


def fit_probability_calibrator(probabilities, outcomes, min_samples: int = 100,
                               regularization: float = 1.0) -> dict[str, float | int | bool]:
    """Fit a regularized logistic mapping using only already-observed predictions."""
    if len(probabilities) != len(outcomes):
        raise ValueError("Calibration probabilities and outcomes must have equal lengths")
    count = len(probabilities)
    if count < min_samples:
        return {"intercept": 0.0, "slope": 1.0, "training_games": count, "enabled": False}
    xs = [_logit(p) for p in probabilities]
    ys = [1.0 if float(y) >= 0.5 else 0.0 for y in outcomes]
    intercept, slope = 0.0, 1.0
    for _ in range(40):
        g0 = regularization * intercept
        g1 = regularization * (slope - 1.0)
        h00 = regularization
        h01 = 0.0
        h11 = regularization
        for x, y in zip(xs, ys):
            q = _sigmoid(intercept + slope * x)
            weight = q * (1.0 - q)
            error = q - y
            g0 += error
            g1 += error * x
            h00 += weight
            h01 += weight * x
            h11 += weight * x * x
        determinant = h00 * h11 - h01 * h01
        if determinant <= 1e-12:
            break
        delta0 = (g0 * h11 - g1 * h01) / determinant
        delta1 = (g1 * h00 - g0 * h01) / determinant
        intercept -= delta0
        slope = max(0.05, min(3.0, slope - delta1))
        intercept = max(-2.5, min(2.5, intercept))
        if max(abs(delta0), abs(delta1)) < 1e-8:
            break
    return {
        "intercept": round(intercept, 8),
        "slope": round(slope, 8),
        "training_games": count,
        "enabled": True,
    }


def apply_probability_calibration(probability: float, calibration: dict[str, Any]) -> float:
    """Apply a fitted calibrator; identity is returned for unavailable fits."""
    if not calibration or not calibration.get("enabled"):
        return min(1.0, max(0.0, float(probability)))
    return _sigmoid(
        float(calibration.get("intercept", 0.0))
        + float(calibration.get("slope", 1.0)) * _logit(probability)
    )

def run_backtest(payload: dict[str, Any], min_prior_games: int = 5, arenas_payload: dict[str, Any] | None = None):
    by_team = {}
    arenas = (arenas_payload or {}).get("teams", {})
    nba_team_codes = {team.get("abbreviation") for team in payload.get("teams", [])}
    opponent_aliases = {"GS": "GSW", "NY": "NYK", "NO": "NOP", "SA": "SAS", "WSH": "WAS"}
    all_rows = []
    for team in payload.get("teams", []):
        seasons = team.get("seasons", {})
        rows = []
        for _, season in sorted(seasons.items(), key=lambda x: int(x[0])):
            rows.extend(
                dict(row, team=team["abbreviation"], season=str(_))
                for row in season.get("games", [])
                if row.get("date") and row.get("game_id")
                and isinstance(row.get("points_for"), (int, float))
                and isinstance(row.get("points_against"), (int, float))
                and row.get("points_for", 0) > 0 and row.get("points_against", 0) > 0
                and opponent_aliases.get(row.get("opponent"), row.get("opponent")) in nba_team_codes
            )
        rows.sort(key=lambda row: parse_date(row["date"]))
        by_team[team["abbreviation"]] = rows
        all_rows.extend(rows)

    games = defaultdict(list)
    for row in all_rows:
        games[row["game_id"]].append(row)
    ordered = sorted(games.values(), key=lambda rows: parse_date(rows[0]["date"]))
    errors_home, errors_away, briers, correct = [], [], [], []
    model_probabilities, model_outcomes = [], []
    calibrated_probabilities, calibrated_briers = [], []
    baseline_errors_home, baseline_errors_away, baseline_correct = [], [], []
    baseline_briers, baseline_probabilities, baseline_outcomes = [], [], []
    advanced_errors, advanced_correct, advanced_briers = [], [], []
    advanced_baseline_errors, advanced_baseline_correct, advanced_probabilities, advanced_outcomes = [], [], [], []
    advanced_baseline_briers, advanced_baseline_probabilities, advanced_baseline_outcomes = [], [], []
    used = 0
    for matchup in ordered:
        if len(matchup) != 2:
            continue
        home = next((r for r in matchup if r.get("home_away") == "home"), None)
        away = next((r for r in matchup if r.get("home_away") == "away"), None)
        if not home or not away:
            continue
        cutoff = parse_date(home["date"])
        prior = {
            abbr: [row for row in rows if parse_date(row["date"]) < cutoff]
            for abbr, rows in by_team.items()
        }
        h_rows, a_rows = prior.get(home["team"], []), prior.get(away["team"], [])
        if len(h_rows) < min_prior_games or len(a_rows) < min_prior_games:
            continue
        league_rows = [row for row in all_rows if parse_date(row["date"]) < cutoff]
        league_values = [row["points_for"] for row in league_rows]
        if len(league_values) < 60:
            continue
        league_avg = mean(league_values)
        league_sd = math.sqrt(mean((value - league_avg) ** 2 for value in league_values))
        prediction = predict(h_rows, a_rows, league_avg, league_sd)
        if not prediction:
            continue
        pred_h, pred_a, p_home = prediction
        actual_h, actual_a = home["points_for"], away["points_for"]
        home_win = actual_h > actual_a
        # Strictly walk-forward calibration: fit only on predictions whose
        # game outcomes were already observed before this test game.
        if len(model_probabilities) >= 100:
            prior_calibration = fit_probability_calibrator(model_probabilities, model_outcomes)
            calibrated_p_home = apply_probability_calibration(p_home, prior_calibration)
        else:
            calibrated_p_home = p_home
        calibrated_probabilities.append(calibrated_p_home)
        calibrated_briers.append((calibrated_p_home - float(home_win)) ** 2)
        errors_home.append(abs(pred_h - actual_h))
        errors_away.append(abs(pred_a - actual_a))
        briers.append((p_home - float(home_win)) ** 2)
        model_probabilities.append(p_home)
        model_outcomes.append(float(home_win))
        correct.append((pred_h > pred_a) == home_win)

        # Previous simple last-10 scoring/allowance baseline, included only
        # as a benchmark; the new model is evaluated on the same games.
        h10, a10 = h_rows[-10:], a_rows[-10:]
        h_pf, h_pa = mean(r["points_for"] for r in h10), mean(r["points_against"] for r in h10)
        a_pf, a_pa = mean(r["points_for"] for r in a10), mean(r["points_against"] for r in a10)
        base_h = (h_pf + a_pa) / 2 + 1.5
        base_a = (a_pf + h_pa) / 2 - 1.5
        baseline_errors_home.append(abs(base_h - actual_h))
        baseline_errors_away.append(abs(base_a - actual_a))
        baseline_correct.append((base_h > base_a) == home_win)
        base_home_sd = weighted_stats(h10, "points_for")
        base_away_sd = weighted_stats(a10, "points_for")
        base_combined_sd = math.sqrt((base_home_sd[1] if base_home_sd else 12.0)**2 +
                                     (base_away_sd[1] if base_away_sd else 12.0)**2)
        base_probability = 0.5 * (1 + math.erf((base_h-base_a)/(math.sqrt(2)*max(8.0,base_combined_sd))))
        baseline_probabilities.append(base_probability)
        baseline_outcomes.append(float(home_win))
        baseline_briers.append((base_probability-float(home_win))**2)

        # Experimental pace/efficiency model is evaluated only when the test
        # game and all required pregame history contain verified boxscore data.
        if all(home.get(key) is not None and away.get(key) is not None
               for key in ("pace_estimate", "offensive_rating", "defensive_rating")):
            advanced_rows = [row for row in league_rows if all(
                row.get(key) is not None
                for key in ("pace_estimate", "offensive_rating", "defensive_rating")
            )]
            if len(advanced_rows) >= 60:
                league_pace = mean(row["pace_estimate"] for row in advanced_rows)
                league_off = mean(row["offensive_rating"] for row in advanced_rows)
                league_def = mean(row["defensive_rating"] for row in advanced_rows)
                advanced_prediction = predict_advanced(
                    [r for r in h_rows if all(r.get(k) is not None for k in ("pace_estimate", "offensive_rating", "defensive_rating"))],
                    [r for r in a_rows if all(r.get(k) is not None for k in ("pace_estimate", "offensive_rating", "defensive_rating"))],
                    league_pace, league_off, league_def,
                    home_rest_days=current_rest_days(h_rows, cutoff),
                    away_rest_days=current_rest_days(a_rows, cutoff),
                    home_travel_miles=current_travel_miles(h_rows, home["team"], away["team"], "home", cutoff, arenas),
                    away_travel_miles=current_travel_miles(a_rows, away["team"], home["team"], "away", cutoff, arenas),
                )
                if advanced_prediction:
                    adv_h, adv_a, adv_prob, _ = advanced_prediction
                    advanced_errors.extend((abs(adv_h-actual_h),abs(adv_a-actual_a)))
                    advanced_correct.append((adv_h>adv_a)==home_win)
                    advanced_briers.append((adv_prob-float(home_win))**2)
                    advanced_baseline_errors.extend((abs(base_h-actual_h),abs(base_a-actual_a)))
                    advanced_baseline_correct.append((base_h>base_a)==home_win)
                    advanced_probabilities.append(adv_prob)
                    advanced_outcomes.append(float(home_win))
                    advanced_baseline_probabilities.append(base_probability)
                    advanced_baseline_outcomes.append(float(home_win))
                    advanced_baseline_briers.append((base_probability-float(home_win))**2)
        used += 1

    if not used:
        return {"games_tested": 0, "message": "Not enough prior games for a walk-forward evaluation yet."}
    return {
        "games_tested": used,
        "excluded_non_nba_opponent_rows": sum(
            1 for team in payload.get("teams", [])
            for season in (team.get("seasons") or {}).values()
            for row in (season.get("games") or [])
            if opponent_aliases.get(row.get("opponent"), row.get("opponent")) not in nba_team_codes
        ),
        "model_score_mae": round(mean(errors_home + errors_away), 3),
        "baseline_score_mae": round(mean(baseline_errors_home + baseline_errors_away), 3),
        "model_winner_accuracy": round(mean(correct), 4),
        "baseline_winner_accuracy": round(mean(baseline_correct), 4),
        "model_brier_score": round(mean(briers), 4),
        "model_calibration_error": expected_calibration_error(model_probabilities, model_outcomes),
        "calibrated_brier_score": round(mean(calibrated_briers), 4),
        "calibrated_calibration_error": expected_calibration_error(calibrated_probabilities, model_outcomes),
        "calibration_validation_games": len(calibrated_probabilities),
        "calibration": {
            **fit_probability_calibrator(model_probabilities, model_outcomes),
            "validation_brier_score": round(mean(calibrated_briers), 4),
            "validation_calibration_error": expected_calibration_error(calibrated_probabilities, model_outcomes),
            "raw_brier_score": round(mean(briers), 4),
            "raw_calibration_error": expected_calibration_error(model_probabilities, model_outcomes),
            "baseline_brier_score": round(mean(baseline_briers), 4),
            "baseline_calibration_error": expected_calibration_error(baseline_probabilities, baseline_outcomes),
            "live_enabled": bool(
                len(calibrated_probabilities) >= 500
                and mean(calibrated_briers) < mean(briers)
                and expected_calibration_error(calibrated_probabilities, model_outcomes)
                    < expected_calibration_error(model_probabilities, model_outcomes)
                and mean(calibrated_briers) <= mean(baseline_briers)
                and expected_calibration_error(calibrated_probabilities, model_outcomes)
                    <= expected_calibration_error(baseline_probabilities, baseline_outcomes)
            ),
        },
        "baseline_brier_score": round(mean(baseline_briers), 4),
        "baseline_calibration_error": expected_calibration_error(baseline_probabilities, baseline_outcomes),
        "advanced_games_tested": len(advanced_correct),
        "advanced_score_mae": round(mean(advanced_errors), 3) if advanced_errors else None,
        "advanced_baseline_score_mae": round(mean(advanced_baseline_errors), 3) if advanced_baseline_errors else None,
        "advanced_winner_accuracy": round(mean(advanced_correct), 4) if advanced_correct else None,
        "advanced_baseline_winner_accuracy": round(mean(advanced_baseline_correct), 4) if advanced_baseline_correct else None,
        "advanced_brier_score": round(mean(advanced_briers), 4) if advanced_briers else None,
        "advanced_baseline_brier_score": round(mean(advanced_baseline_briers), 4) if advanced_baseline_briers else None,
        "advanced_calibration_error": expected_calibration_error(advanced_probabilities, advanced_outcomes),
        "advanced_baseline_calibration_error": expected_calibration_error(advanced_baseline_probabilities, advanced_baseline_outcomes),
        "note": "Chronological multi-season walk-forward results; each prediction uses only games dated earlier than the test game. The experimental pace/efficiency model also includes small capped rest and straight-line travel adjustments; it is not promoted unless it beats the same-game baseline.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DATA_PATH)
    parser.add_argument("--min-prior-games", type=int, default=5)
    parser.add_argument("--output", type=Path, default=None, help="Optional path for a JSON metrics snapshot")
    parser.add_argument("--arenas", type=Path, default=ARENAS_PATH)
    args = parser.parse_args()
    payload = json.loads(args.data.read_text(encoding="utf-8"))
    arenas = json.loads(args.arenas.read_text(encoding="utf-8")) if args.arenas.exists() else {}
    result = run_backtest(payload, args.min_prior_games, arenas)
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    rendered = json.dumps(result, indent=2) + "\n"
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
