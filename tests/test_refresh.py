import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "refresh_data.py"
spec = importlib.util.spec_from_file_location("refresh_data", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_market_text_handles_missing_fields():
    assert module._market_text({"question": "NBA: Lakers vs Celtics"}).startswith("nba")


def test_market_text_handles_empty_market():
    assert module._market_text({}) == ""


def test_market_filter_terms_include_all_nba_teams():
    assert "lakers" in module.NBA_TEAMS
    assert "celtics" in module.NBA_TEAMS
    assert len(module.NBA_TEAMS) == 30
