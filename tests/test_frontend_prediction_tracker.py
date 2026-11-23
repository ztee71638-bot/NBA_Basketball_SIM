import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _function_source(source: str, name: str) -> str:
    match = re.search(rf"^function {re.escape(name)}\([^)]*\)\s*\{{.*?^\}}", source, re.M | re.S)
    assert match, f"Could not locate {name} in app.js"
    return match.group(0)


def test_prediction_tracker_grades_advanced_model_records_separately():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable; CI separately installs/runs Node syntax validation")
    app_source = (ROOT / "app.js").read_text(encoding="utf-8")
    reconcile = _function_source(app_source, "reconcilePredictionLog")
    payload = {
        "records": [
            {"source": "simulator", "gameId": "g1", "homeAbbr": "BOS", "awayAbbr": "NYK", "pregame": True, "predictedWinner": "BOS"},
            {"source": "opponent-model", "gameId": "g1", "homeAbbr": "BOS", "awayAbbr": "NYK", "pregame": True, "predictedWinner": "NYK"},
            {"source": "advanced-model", "gameId": "g1", "homeAbbr": "BOS", "awayAbbr": "NYK", "pregame": True, "predictedWinner": "BOS"},
        ],
        "games": [{"id": "g1", "completed": True, "home": {"score": 112}, "away": {"score": 104}}],
    }
    js = r"""
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
let records = input.records;
const games = input.games;
function readPredictionLog(){ return records; }
function writePredictionLog(next){ records = next; }
function renderPredictionTracker(){}
""" + reconcile + r"""
reconcilePredictionLog();
process.stdout.write(JSON.stringify(records));
"""
    result = subprocess.run(
        [node, "-e", js], input=json.dumps(payload), text=True,
        capture_output=True, check=True,
    )
    graded = json.loads(result.stdout)
    assert len(graded) == 3
    assert all(record["actualWinner"] == "BOS" for record in graded)
    assert all(record["actualHomeScore"] == 112 and record["actualAwayScore"] == 104 for record in graded)
    assert all(record["gradedAt"] for record in graded)
