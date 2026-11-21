import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def read_json(name):
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


def test_all_data_snapshots_have_expected_top_level_shapes():
    assert isinstance(read_json("games.json").get("games"), list)
    assert isinstance(read_json("polymarket.json").get("markets"), list)
    assert isinstance(read_json("players.json").get("players"), list)
    assert isinstance(read_json("teams.json").get("teams"), list)


def test_live_feeds_are_not_empty_after_initial_refresh():
    assert len(read_json("games.json")["games"]) > 0
    assert len(read_json("polymarket.json")["markets"]) > 0
