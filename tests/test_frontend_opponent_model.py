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
    assert actual["homeMean"] == pytest.approx(expected[0], abs=1e-8)
    assert actual["awayMean"] == pytest.approx(expected[1], abs=1e-8)
    assert actual["rawHomeProbability"] == pytest.approx(expected[2], abs=2e-7)
