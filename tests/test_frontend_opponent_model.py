import importlib.util
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("backtest_model", ROOT / "scripts" / "backtest_model.py")
_backtest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_backtest)
predict = _backtest.predict
predict_advanced = _backtest.predict_advanced
current_rest_days = _backtest.current_rest_days
current_travel_miles = _backtest.current_travel_miles


TEAM_CODES = [
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
]


def _function_source(source: str, name: str) -> str:
    match = re.search(rf"^function {re.escape(name)}\([^)]*\)\s*\{{.*?^\}}", source, re.M | re.S)
    assert match, f"Could not locate {name} in app.js"
    return match.group(0)


def test_live_opponent_model_matches_backtest_prediction():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable; CI separately installs/runs Node syntax validation")

    root = ROOT
    app_source = (root / "app.js").read_text(encoding="utf-8")
    js_functions = "\n".join(
        _function_source(app_source, name)
        for name in ("opponentWeightedStats", "opponentAdjustedMatchup")
    )

    teams = []
    by_code = {}
    for team_index, code in enumerate(TEAM_CODES):
        row_count = 6 if code in ("BOS", "NYK") else 4
        rows = []
        for game_index in range(row_count):
            rows.append({
                "game_id": f"{code}-{game_index}",
                "date": f"2026-11-{game_index + 1:02d}T20:00:00Z",
                "opponent": ("GS" if code == "BOS" and game_index == 0 else TEAM_CODES[(team_index + 1) % len(TEAM_CODES)]),
                "points_for": 99 + (team_index % 13) + game_index * 1.7,
                "points_against": 101 + (team_index % 9) + game_index * 1.1,
            })
        by_code[code] = rows
        teams.append({"abbreviation": code, "seasons": {"2027": {"games": rows}}})

    all_rows = [row for rows in by_code.values() for row in rows]
    league_average = sum(row["points_for"] for row in all_rows) / len(all_rows)
    league_sd = math.sqrt(sum((row["points_for"] - league_average) ** 2 for row in all_rows) / len(all_rows))
    expected = predict(by_code["NYK"], by_code["BOS"], league_average, league_sd)
    assert expected is not None

    payload = {"teams": teams, "cutoff": "2026-11-24T00:00:00Z"}
    js = r"""
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
const teamData = input.teams;
const teamUpdatedAt = new Date();
let opponentModelHistoryCache = null;
function canonicalTeam(abbr) {
  const aliases = {GS:"GSW",NY:"NYK",NO:"NOP",SA:"SAS",WSH:"WAS",UTAH:"UTA"};
  return aliases[abbr] || abbr;
}
function erf(x) {
  const sign=x<0?-1:1;x=Math.abs(x);const t=1/(1+0.3275911*x);
  const y=1-(((((1.061405429*t-1.453152027)*t)+1.421413741)*t-0.284496736)*t+0.254829592)*t*Math.exp(-x*x);
  return sign*y;
}
""" + js_functions + r"""
const result = opponentAdjustedMatchup({
  date: input.cutoff,
  home: {abbreviation:"NYK"},
  away: {abbreviation:"BOS"}
});
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        [node, "-e", js],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    actual = json.loads(completed.stdout)
    assert actual is not None
    assert actual["homeRestDays"] == home_rest, f"home rest mismatch: {actual} vs {home_rest}"
    assert actual["awayRestDays"] == away_rest, f"away rest mismatch: {actual} vs {away_rest}"
    assert actual["homeTravelMiles"] == pytest.approx(home_travel, abs=1e-6), f"home travel mismatch: {actual} vs {home_travel}"
    assert actual["awayTravelMiles"] == pytest.approx(away_travel, abs=1e-6), f"away travel mismatch: {actual} vs {away_travel}"
    assert actual["homeMean"] == pytest.approx(expected[0], abs=1e-8)
    assert actual["awayMean"] == pytest.approx(expected[1], abs=1e-8)
    assert actual["rawHomeProbability"] == pytest.approx(expected[2], abs=2e-7)


def test_live_advanced_model_matches_prequential_backtest_projection():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable; CI separately installs/runs Node syntax validation")
    app_source = (ROOT / "app.js").read_text(encoding="utf-8")
    js_functions = "\n".join(
        _function_source(app_source, name)
        for name in (
            "opponentWeightedStats", "opponentAdjustedMatchup",
            "estimateTravelMiles", "advancedModelMatchup",
        )
    )
    teams, by_code, arenas = [], {}, {}
    for index, code in enumerate(TEAM_CODES):
        arenas[code] = {"latitude": 25.0 + index * 0.7, "longitude": -120.0 + index * 1.1}
        rows = []
        for game_index in range(8):
            opponent = TEAM_CODES[(index + game_index + 1) % len(TEAM_CODES)]
            rows.append({
                "game_id": f"{code}-{game_index}",
                "date": f"2026-11-{game_index + 1:02d}T20:00:00Z",
                "opponent": opponent,
                "home_away": "home" if game_index % 2 == 0 else "away",
                "points_for": 99 + (index % 13) + game_index * 1.7,
                "points_against": 101 + (index % 9) + game_index * 1.1,
                "pace_estimate": 96 + (index % 7) + game_index * 0.25,
                "offensive_rating": 105 + (index % 11) + game_index * 0.35,
                "defensive_rating": 104 + (index % 9) + game_index * 0.2,
            })
        by_code[code] = rows
        teams.append({"abbreviation": code, "seasons": {"2027": {"games": rows}}})
    cutoff_text = "2026-11-10T20:00:00Z"
    cutoff = _backtest.parse_date(cutoff_text)
    all_rows = [row for rows in by_code.values() for row in rows if _backtest.parse_date(row["date"]) < cutoff]
    advanced_rows = [row for row in all_rows if all(row.get(key) is not None for key in ("pace_estimate", "offensive_rating", "defensive_rating"))]
    league_pace = sum(row["pace_estimate"] for row in advanced_rows) / len(advanced_rows)
    league_off = sum(row["offensive_rating"] for row in advanced_rows) / len(advanced_rows)
    league_def = sum(row["defensive_rating"] for row in advanced_rows) / len(advanced_rows)
    home_rows = sorted(by_code["NYK"], key=lambda row: row["date"])
    away_rows = sorted(by_code["BOS"], key=lambda row: row["date"])
    home_rest = current_rest_days(home_rows, cutoff)
    away_rest = current_rest_days(away_rows, cutoff)
    home_travel = current_travel_miles(home_rows, "NYK", "BOS", "home", cutoff, {"teams": arenas})
    away_travel = current_travel_miles(away_rows, "BOS", "NYK", "away", cutoff, {"teams": arenas})
    expected = predict_advanced(
        home_rows, away_rows, league_pace, league_off, league_def,
        home_rest_days=home_rest, away_rest_days=away_rest,
        home_travel_miles=home_travel, away_travel_miles=away_travel,
    )
    assert expected is not None
    payload = {"teams": teams, "cutoff": cutoff_text, "arenas": arenas}
    js = r"""
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
const teamData = input.teams;
const teamUpdatedAt = new Date();
const arenaData = input.arenas;
let opponentModelHistoryCache = null;
function canonicalTeam(abbr) {
  const aliases = {GS:"GSW",NY:"NYK",NO:"NOP",SA:"SAS",WSH:"WAS",UTAH:"UTA"};
  return aliases[abbr] || abbr;
}
function erf(x) {
  const sign=x<0?-1:1;x=Math.abs(x);const t=1/(1+0.3275911*x);
  const y=1-(((((1.061405429*t-1.453152027)*t)+1.421413741)*t-0.284496736)*t+0.254829592)*t*Math.exp(-x*x);
  return sign*y;
}
""" + js_functions + r"""
const game = {
  date: input.cutoff,
  home: {abbreviation:"NYK"},
  away: {abbreviation:"BOS"}
};
opponentAdjustedMatchup(game); // Build the shared chronological history cache as the live simulation does.
const result = advancedModelMatchup(game);
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        [node, "-e", js], input=json.dumps(payload), text=True,
        capture_output=True, check=True,
    )
    actual = json.loads(completed.stdout)
    assert actual is not None
    assert actual["homeMean"] == pytest.approx(expected[0], abs=1e-8)
    assert actual["awayMean"] == pytest.approx(expected[1], abs=1e-8)
    assert actual["rawHomeProbability"] == pytest.approx(expected[2], abs=2e-7)

