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


def weighted_profile_metric(rows: list[dict[str, Any]], key: str, half_life: float = 8.0):
    """Mirror the browser's recency-weighted mean, SD and effective sample size."""
    values = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
    if not values:
        return None
    weights = [0.5 ** (age / half_life) for age in range(len(values)-1, -1, -1)]
    total_weight = sum(weights)
    squared_weight = sum(weight * weight for weight in weights)
    avg = sum(value * weight for value, weight in zip(values, weights)) / total_weight
    variance = sum(weight * (value-avg) ** 2 for value, weight in zip(values, weights)) / total_weight
    effective_count = total_weight * total_weight / squared_weight if squared_weight else 0.0
    return avg, math.sqrt(variance), effective_count


def browser_team_profile_rows(prior_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Match teamSeasonGames(): latest populated season plus the prior season's last ten."""
    populated = sorted({str(row.get("season")) for row in prior_rows if row.get("season")})
    if not populated:
        return []
    latest = populated[-1]
    current = [row for row in prior_rows if str(row.get("season")) == latest]
    earlier = [season for season in populated if int(season) < int(latest)]
    previous = []
    if earlier:
        previous_season = earlier[-1]
        previous = [row for row in prior_rows if str(row.get("season")) == previous_season][-10:]
    return sorted(previous + current, key=lambda row: parse_date(row["date"]))


def browser_baseline_probability(home_rows, away_rows, league_rows, league_profile=None):
    """Estimate the default UI's last-10 baseline win probability before calibration."""
    if not home_rows or not away_rows:
        return None
    home_recent, away_recent = home_rows[-10:], away_rows[-10:]
    avg = lambda rows, key: mean(float(row[key]) for row in rows)
    home_mean = (avg(home_recent, "points_for") + avg(away_recent, "points_against")) / 2 + 1.5
    away_mean = (avg(away_recent, "points_for") + avg(home_recent, "points_against")) / 2 - 1.5

    league = league_profile or weighted_profile_metric(sorted(league_rows, key=lambda row: parse_date(row["date"])), "points_for")
    if not league:
        return None
    league_sd = league[1]

    def team_sd(prior_rows):
        profile_rows = browser_team_profile_rows(prior_rows)
        offense = weighted_profile_metric(profile_rows, "points_for")
        if not offense:
            return max(8.0, league_sd)
        variance_reliability = offense[2] / (offense[2] + 10)
        return math.sqrt(
            variance_reliability * offense[1] ** 2
            + (1 - variance_reliability) * league_sd ** 2
        )

    home_team_sd, away_team_sd = team_sd(home_rows), team_sd(away_rows)
    input_sd = (home_team_sd + away_team_sd) / 2
    sim_home_sd = math.sqrt(0.7 * home_team_sd ** 2 + 0.3 * input_sd ** 2)
    sim_away_sd = math.sqrt(0.7 * away_team_sd ** 2 + 0.3 * input_sd ** 2)
    # Match the simulator's shared environment shock (0.35 coefficient).
    combined_sd = math.sqrt(max(
        1.0,
        sim_home_sd ** 2 + sim_away_sd ** 2
        - 2 * 0.1225 * sim_home_sd * sim_away_sd,
    ))
    return 0.5 * (1 + math.erf((home_mean - away_mean) / (math.sqrt(2) * combined_sd)))


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




def binary_log_loss(probabilities, outcomes):
    """Mean Bernoulli log loss; lower is better and confident misses are penalized."""
    if len(probabilities) != len(outcomes):
        raise ValueError("Log-loss probabilities and outcomes must have equal lengths")
    if not probabilities:
        return None
    losses = []
    for probability, outcome in zip(probabilities, outcomes):
        p = min(1.0 - 1e-15, max(1e-15, float(probability)))
        y = 1.0 if float(outcome) >= 0.5 else 0.0
        losses.append(-(y * math.log(p) + (1.0 - y) * math.log(1.0 - p)))
    return round(mean(losses), 4)


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


def probability_bucket_report(probabilities, outcomes):
    """Summarize the production baseline by predicted-side confidence."""
    edges = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 1.000001)
    report = []
    for lower, upper in zip(edges, edges[1:]):
        selected = [
            (float(p), float(y)) for p, y in zip(probabilities, outcomes)
            if lower <= max(float(p), 1.0 - float(p)) < upper
        ]
        if not selected:
            continue
        report.append({
            "confidence_range": f"{lower:.0%}-{min(upper, 1.0):.0%}",
            "games": len(selected),
            "average_confidence": round(mean(max(p, 1.0 - p) for p, _ in selected), 4),
            "observed_accuracy": round(mean(float((p >= 0.5) == (y >= 0.5)) for p, y in selected), 4),
            "brier_score": round(mean((p - y) ** 2 for p, y in selected), 4),
        })
    return report



def rolling_window_report(model_score_errors, baseline_score_errors,
                          model_correct, baseline_correct, model_briers,
                          baseline_briers, model_probabilities,
                          baseline_probabilities, outcomes):
    """Compare recent chronological holdout windows without reusing future games."""
    report = {}
    available = len(model_correct)
    for window in (100, 250, 500):
        if available < window:
            continue
        model_probs = model_probabilities[-window:]
        baseline_probs = baseline_probabilities[-window:]
        window_outcomes = outcomes[-window:]
        report[str(window)] = {
            "games": window,
            "model_score_mae": round(mean(model_score_errors[-window:]), 3),
            "baseline_score_mae": round(mean(baseline_score_errors[-window:]), 3),
            "model_winner_accuracy": round(mean(model_correct[-window:]), 4),
            "baseline_winner_accuracy": round(mean(baseline_correct[-window:]), 4),
            "model_brier_score": round(mean(model_briers[-window:]), 4),
            "baseline_brier_score": round(mean(baseline_briers[-window:]), 4),
            "model_log_loss": binary_log_loss(model_probs, window_outcomes),
            "baseline_log_loss": binary_log_loss(baseline_probs, window_outcomes),
            "model_calibration_error": expected_calibration_error(model_probs, window_outcomes),
            "baseline_calibration_error": expected_calibration_error(baseline_probs, window_outcomes),
        }
    return report


def run_backtest(payload: dict[str, Any], min_prior_games: int = 5, arenas_payload: dict[str, Any] | None = None, include_predictions: bool = False):
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
    advanced_score_errors_by_game, advanced_baseline_score_errors_by_game = [], []
    advanced_season_diagnostics = defaultdict(lambda: {
        "games": 0, "model_score_errors": [], "baseline_score_errors": [],
        "model_correct": [], "baseline_correct": [], "model_briers": [],
        "baseline_briers": [], "model_probabilities": [],
        "baseline_probabilities": [], "outcomes": [],
    })
    used = 0
    prediction_records = []
    model_score_errors_by_game = []
    baseline_score_errors_by_game = []
    season_diagnostics = defaultdict(lambda: {
        "games": 0, "model_score_errors": [], "baseline_score_errors": [],
        "model_correct": [], "baseline_correct": [], "model_briers": [],
        "baseline_briers": [],
    })
    # Matchups are chronological. Freeze shared league context at the earliest
    # tipoff each calendar day; this conservatively excludes all same-day games
    # from the league baseline while team histories still use each exact cutoff.
    # That avoids look-ahead and avoids rebuilding large league aggregates for
    # every matchup on a busy slate.
    cached_cutoff = None
    cached_context = None
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
        cutoff_key = cutoff.date().isoformat()
        if cutoff_key != cached_cutoff:
            league_rows = [row for row in all_rows if parse_date(row["date"]) < cutoff]
            league_values = [row["points_for"] for row in league_rows]
            if len(league_values) < 60:
                cached_cutoff, cached_context = cutoff_key, None
                continue
            league_avg = mean(league_values)
            league_sd = math.sqrt(mean((value - league_avg) ** 2 for value in league_values))
            sorted_league_rows = sorted(league_rows, key=lambda row: parse_date(row["date"]))
            league_profile = weighted_profile_metric(sorted_league_rows, "points_for")
            advanced_rows = [row for row in league_rows if all(
                row.get(key) is not None
                for key in ("pace_estimate", "offensive_rating", "defensive_rating")
            )]
            cached_context = {
                "league_rows": league_rows,
                "league_avg": league_avg,
                "league_sd": league_sd,
                "league_profile": league_profile,
                "advanced_rows": advanced_rows,
                "league_pace": mean(row["pace_estimate"] for row in advanced_rows) if advanced_rows else None,
                "league_off": mean(row["offensive_rating"] for row in advanced_rows) if advanced_rows else None,
                "league_def": mean(row["defensive_rating"] for row in advanced_rows) if advanced_rows else None,
            }
            cached_cutoff = cutoff_key
        if cached_context is None:
            continue
        league_rows = cached_context["league_rows"]
        league_avg = cached_context["league_avg"]
        league_sd = cached_context["league_sd"]
        league_profile = cached_context["league_profile"]
        advanced_rows = cached_context["advanced_rows"]
        prediction = predict(h_rows, a_rows, league_avg, league_sd)
        if not prediction:
            continue
        pred_h, pred_a, p_home = prediction
        actual_h, actual_a = home["points_for"], away["points_for"]
        home_win = actual_h > actual_a
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
        # This is the default UI model: last-10 means plus the same
        # recency-weighted team variance and shared scoring shock as the simulator.
        base_probability = browser_baseline_probability(h_rows, a_rows, league_rows, league_profile)
        if base_probability is None:
            base_probability = 0.5 * (1 + math.erf((base_h-base_a)/(math.sqrt(2)*max(8.0,base_combined_sd))))
        baseline_probabilities.append(base_probability)
        baseline_outcomes.append(float(home_win))
        baseline_briers.append((base_probability-float(home_win))**2)
        model_score_errors_by_game.append((abs(pred_h-actual_h)+abs(pred_a-actual_a))/2)
        baseline_score_errors_by_game.append((abs(base_h-actual_h)+abs(base_a-actual_a))/2)

        season_key = str(home.get("season") or "unknown")
        season_row = season_diagnostics[season_key]
        season_row["games"] += 1
        season_row["model_score_errors"].extend((abs(pred_h-actual_h), abs(pred_a-actual_a)))
        season_row["baseline_score_errors"].extend((abs(base_h-actual_h), abs(base_a-actual_a)))
        season_row["model_correct"].append(float((pred_h > pred_a) == home_win))
        season_row["baseline_correct"].append(float((base_h > base_a) == home_win))
        season_row["model_briers"].append((p_home-float(home_win))**2)
        season_row["baseline_briers"].append((base_probability-float(home_win))**2)

        if include_predictions:
            def recent_average(rows, key):
                sample = rows[-10:]
                values = [float(row[key]) for row in sample if isinstance(row.get(key), (int, float))]
                return round(mean(values), 3) if values else None
            prediction_records.append({
                "game_id": str(home["game_id"]),
                "date": home["date"],
                "season": season_key,
                "home_team": home["team"],
                "away_team": away["team"],
                "model_version": "opponent-weighted-score-v1",
                "baseline_version": "last10-ui-v1",
                "pregame_inputs": {
                    "league_points_average": round(league_avg, 3),
                    "league_points_sd": round(league_sd, 3),
                    "home_prior_games": len(h_rows),
                    "away_prior_games": len(a_rows),
                    "home_recent10_points_for": recent_average(h_rows, "points_for"),
                    "home_recent10_points_against": recent_average(h_rows, "points_against"),
                    "away_recent10_points_for": recent_average(a_rows, "points_for"),
                    "away_recent10_points_against": recent_average(a_rows, "points_against"),
                },
                "production_baseline": {
                    "home_score": round(base_h, 2),
                    "away_score": round(base_a, 2),
                    "home_win_probability": round(base_probability, 6),
                },
                "experimental_model": {
                    "home_score": round(pred_h, 2),
                    "away_score": round(pred_a, 2),
                    "home_win_probability": round(p_home, 6),
                },
                "actual": {
                    "home_score": actual_h,
                    "away_score": actual_a,
                    "home_win": bool(home_win),
                },
            })

        # Fit only on prior, already-observed default-UI baseline predictions.
        if len(baseline_probabilities) > 100:
            prior_calibration = fit_probability_calibrator(
                baseline_probabilities[:-1], baseline_outcomes[:-1]
            )
            calibrated_p_home = apply_probability_calibration(base_probability, prior_calibration)
        else:
            calibrated_p_home = base_probability
        calibrated_probabilities.append(calibrated_p_home)
        calibrated_briers.append((calibrated_p_home - float(home_win)) ** 2)

        # Experimental pace/efficiency model is evaluated only when the test
        # game and all required pregame history contain verified boxscore data.
        if all(home.get(key) is not None and away.get(key) is not None
               for key in ("pace_estimate", "offensive_rating", "defensive_rating")):
            if len(advanced_rows) >= 60:
                league_pace = cached_context["league_pace"]
                league_off = cached_context["league_off"]
                league_def = cached_context["league_def"]
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
                    advanced_score_errors_by_game.append((abs(adv_h-actual_h)+abs(adv_a-actual_a))/2)
                    advanced_baseline_score_errors_by_game.append((abs(base_h-actual_h)+abs(base_a-actual_a))/2)
                    advanced_season = advanced_season_diagnostics[season_key]
                    advanced_season["games"] += 1
                    advanced_season["model_score_errors"].extend((abs(adv_h-actual_h), abs(adv_a-actual_a)))
                    advanced_season["baseline_score_errors"].extend((abs(base_h-actual_h), abs(base_a-actual_a)))
                    advanced_season["model_correct"].append(float((adv_h>adv_a)==home_win))
                    advanced_season["baseline_correct"].append(float((base_h>base_a)==home_win))
                    advanced_season["model_briers"].append((adv_prob-float(home_win))**2)
                    advanced_season["baseline_briers"].append((base_probability-float(home_win))**2)
                    advanced_season["model_probabilities"].append(adv_prob)
                    advanced_season["baseline_probabilities"].append(base_probability)
                    advanced_season["outcomes"].append(float(home_win))
        used += 1

    if not used:
        return {"games_tested": 0, "message": "Not enough prior games for a walk-forward evaluation yet."}
    result = {
        "model_version": "opponent-weighted-score-v1",
        "production_baseline_version": "last10-ui-v1",
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
        "model_log_loss": binary_log_loss(model_probabilities, model_outcomes),
        "model_calibration_error": expected_calibration_error(model_probabilities, model_outcomes),
        "calibrated_brier_score": round(mean(calibrated_briers), 4),
        "calibrated_calibration_error": expected_calibration_error(calibrated_probabilities, model_outcomes),
        "calibration_validation_games": len(calibrated_probabilities),
        "calibration": {
            **fit_probability_calibrator(baseline_probabilities, baseline_outcomes),
            "training_model": "last10_baseline_simulation_probability",
            "validation_brier_score": round(mean(calibrated_briers), 4),
            "validation_calibration_error": expected_calibration_error(calibrated_probabilities, baseline_outcomes),
            "raw_brier_score": round(mean(baseline_briers), 4),
            "raw_calibration_error": expected_calibration_error(baseline_probabilities, baseline_outcomes),
            "opponent_adjusted_model_brier_score": round(mean(briers), 4),
            "opponent_adjusted_model_calibration_error": expected_calibration_error(model_probabilities, model_outcomes),
            "live_enabled": bool(
                len(calibrated_probabilities) >= 500
                and mean(calibrated_briers) < mean(baseline_briers)
                and expected_calibration_error(calibrated_probabilities, baseline_outcomes)
                    < expected_calibration_error(baseline_probabilities, baseline_outcomes)
                and mean(calibrated_briers) < mean(briers)
                and expected_calibration_error(calibrated_probabilities, baseline_outcomes)
                    < expected_calibration_error(model_probabilities, model_outcomes)
            ),
        },
        "baseline_brier_score": round(mean(baseline_briers), 4),
        "baseline_log_loss": binary_log_loss(baseline_probabilities, baseline_outcomes),
        "baseline_calibration_error": expected_calibration_error(baseline_probabilities, baseline_outcomes),
        "production_baseline_confidence_buckets": probability_bucket_report(
            baseline_probabilities, baseline_outcomes
        ),
        "recent_windows": rolling_window_report(
            model_score_errors_by_game, baseline_score_errors_by_game,
            correct, baseline_correct, briers, baseline_briers,
            model_probabilities, baseline_probabilities, model_outcomes,
        ),
        "by_season": {
            season: {
                "games": values["games"],
                "model_score_mae": round(mean(values["model_score_errors"]), 3),
                "baseline_score_mae": round(mean(values["baseline_score_errors"]), 3),
                "model_winner_accuracy": round(mean(values["model_correct"]), 4),
                "baseline_winner_accuracy": round(mean(values["baseline_correct"]), 4),
                "model_brier_score": round(mean(values["model_briers"]), 4),
                "baseline_brier_score": round(mean(values["baseline_briers"]), 4),
            }
            for season, values in sorted(season_diagnostics.items())
        },
        "diagnostics_note": (
            "Season slices and confidence buckets are descriptive holdout diagnostics. "
            "Small slices are not sufficient to establish a predictive edge."
        ),
        "advanced_games_tested": len(advanced_correct),
        "advanced_score_mae": round(mean(advanced_errors), 3) if advanced_errors else None,
        "advanced_baseline_score_mae": round(mean(advanced_baseline_errors), 3) if advanced_baseline_errors else None,
        "advanced_winner_accuracy": round(mean(advanced_correct), 4) if advanced_correct else None,
        "advanced_baseline_winner_accuracy": round(mean(advanced_baseline_correct), 4) if advanced_baseline_correct else None,
        "advanced_brier_score": round(mean(advanced_briers), 4) if advanced_briers else None,
        "advanced_baseline_brier_score": round(mean(advanced_baseline_briers), 4) if advanced_baseline_briers else None,
        "advanced_log_loss": binary_log_loss(advanced_probabilities, advanced_outcomes),
        "advanced_baseline_log_loss": binary_log_loss(advanced_baseline_probabilities, advanced_baseline_outcomes),
        "advanced_calibration_error": expected_calibration_error(advanced_probabilities, advanced_outcomes),
        "advanced_baseline_calibration_error": expected_calibration_error(advanced_baseline_probabilities, advanced_baseline_outcomes),
        "advanced_recent_windows": rolling_window_report(
            advanced_score_errors_by_game, advanced_baseline_score_errors_by_game,
            advanced_correct, advanced_baseline_correct, advanced_briers,
            advanced_baseline_briers, advanced_probabilities,
            advanced_baseline_probabilities, advanced_outcomes,
        ),
        "advanced_by_season": {
            season: {
                "games": values["games"],
                "model_score_mae": round(mean(values["model_score_errors"]), 3),
                "baseline_score_mae": round(mean(values["baseline_score_errors"]), 3),
                "model_winner_accuracy": round(mean(values["model_correct"]), 4),
                "baseline_winner_accuracy": round(mean(values["baseline_correct"]), 4),
                "model_brier_score": round(mean(values["model_briers"]), 4),
                "baseline_brier_score": round(mean(values["baseline_briers"]), 4),
                "model_log_loss": binary_log_loss(values["model_probabilities"], values["outcomes"]),
                "baseline_log_loss": binary_log_loss(values["baseline_probabilities"], values["outcomes"]),
                "model_calibration_error": expected_calibration_error(values["model_probabilities"], values["outcomes"]),
                "baseline_calibration_error": expected_calibration_error(values["baseline_probabilities"], values["outcomes"]),
            }
            for season, values in sorted(advanced_season_diagnostics.items())
        },
        "note": "Chronological multi-season walk-forward results; each prediction uses only games dated earlier than the test game. The experimental pace/efficiency model also includes small capped rest and straight-line travel adjustments; it is not promoted unless it beats the same-game baseline.",
    }
    if include_predictions:
        result["predictions"] = prediction_records
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DATA_PATH)
    parser.add_argument("--min-prior-games", type=int, default=5)
    parser.add_argument("--output", type=Path, default=None, help="Optional path for a JSON metrics snapshot")
    parser.add_argument("--predictions-output", type=Path, default=None, help="Optional path for a compact pregame prediction ledger")
    parser.add_argument("--arenas", type=Path, default=ARENAS_PATH)
    args = parser.parse_args()
    payload = json.loads(args.data.read_text(encoding="utf-8"))
    arenas = json.loads(args.arenas.read_text(encoding="utf-8")) if args.arenas.exists() else {}
    result = run_backtest(payload, args.min_prior_games, arenas, include_predictions=bool(args.predictions_output))
    predictions = result.pop("predictions", [])
    generated_at = datetime.now(timezone.utc).isoformat()
    result["generated_at"] = generated_at
    rendered = json.dumps(result, indent=2) + "\n"
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if args.predictions_output:
        args.predictions_output.parent.mkdir(parents=True, exist_ok=True)
        ledger = {
            "generated_at": generated_at,
            "prediction_count": len(predictions),
            "method": "chronological walk-forward; pregame inputs only",
            "predictions": predictions,
        }
        args.predictions_output.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
