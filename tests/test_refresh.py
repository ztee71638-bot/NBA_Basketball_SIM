import importlib.util
from datetime import datetime, timezone
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


def test_nba_market_filter_avoids_partial_team_name_matches():
    assert module.is_nba_market({"question": "Miami Heat to win"})
    assert not module.is_nba_market({"question": "Theater opening this weekend"})


def test_fetch_games_parses_espn_competitors(monkeypatch):
    calls = []
    payload = {
        "events": [{
            "id": "game-1",
            "date": "2026-11-21T00:00Z",
            "name": "Boston Celtics at Miami Heat",
            "shortName": "BOS @ MIA",
            "status": {"type": {"name": "STATUS_SCHEDULED", "shortDetail": "7:30 PM", "completed": False}},
            "competitions": [{
                "venue": {"fullName": "Kaseya Center"},
                "competitors": [
                    {"homeAway": "away", "team": {"id": "2", "displayName": "Boston Celtics", "abbreviation": "BOS"}, "score": "0"},
                    {"homeAway": "home", "team": {"id": "3", "displayName": "Miami Heat", "abbreviation": "MIA"}, "score": "0"},
                ],
            }],
        }]
    }
    def fake_get_json(url, params=None):
        calls.append(params["dates"])
        return payload
    monkeypatch.setattr(module, "get_json", fake_get_json)
    games = module.fetch_games(datetime(2026, 11, 21, tzinfo=timezone.utc))
    assert len(games) == 3
    assert games[0]["home"]["abbreviation"] == "MIA"
    assert games[0]["away"]["abbreviation"] == "BOS"
    assert len(calls) == 3

def test_nba_market_filter_ignores_unrelated_description_text():
    market = {
        "question": "Will the Riemann Hypothesis be solved?",
        "slug": "riemann-hypothesis-before-next-millennium",
        "description": "A long description with unrelated league references.",
    }
    assert not module.is_nba_market(market)
