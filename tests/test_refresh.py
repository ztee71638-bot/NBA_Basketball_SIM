import importlib.util
from datetime import datetime, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "refresh_data.py"
spec = importlib.util.spec_from_file_location("refresh_data", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)



def test_parse_confirmed_lineups_requires_five_explicit_starters_per_team():
    game = {
        "id": "lineup-game", "date": "2026-11-21T23:00Z",
        "home": {"abbreviation": "MIA"}, "away": {"abbreviation": "BOS"},
    }
    players = []
    for team_id, code in (("14", "MIA"), ("2", "BOS")):
        group = {"team": {"id": team_id, "abbreviation": code}, "statistics": [{
            "athletes": [
                {"athlete": {"id": team_id + str(i), "displayName": code + " Starter " + str(i)},
                 "starter": True, "active": True}
                for i in range(5)
            ]
        }]}
        players.append(group)
    parsed = module.parse_confirmed_lineups({"boxscore": {"players": players}}, game)
    assert parsed["status"] == "confirmed"
    assert len(parsed["home_starters"]) == 5
    assert len(parsed["away_starters"]) == 5


def test_parse_confirmed_lineups_does_not_infer_missing_starters():
    game = {"id": "lineup-game", "home": {"abbreviation": "MIA"}, "away": {"abbreviation": "BOS"}}
    payload = {"boxscore": {"players": [{
        "team": {"abbreviation": "MIA"},
        "statistics": [{"athletes": [
            {"athlete": {"id": str(i), "displayName": "Starter"}, "starter": True}
            for i in range(4)
        ]}],
    }]}}
    parsed = module.parse_confirmed_lineups(payload, game)
    assert parsed["status"] == "not_available"
    assert parsed["home_starters"] == []



def test_get_json_retries_rate_limits_and_succeeds(monkeypatch):
    import requests
    class FakeResponse:
        def __init__(self, status, payload=None):
            self.status_code = status
            self.headers = {"Retry-After": "0"}
            self.payload = payload or {}
        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(response=self)
        def json(self):
            return self.payload
    responses = [FakeResponse(429), FakeResponse(200, {"ok": True})]
    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: responses.pop(0))
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    assert module.get_json("https://example.test/data") == {"ok": True}


def test_get_json_does_not_retry_permanent_client_errors(monkeypatch):
    import requests
    class FakeResponse:
        status_code = 404
        headers = {}
        def raise_for_status(self):
            raise requests.HTTPError(response=self)
    calls = []
    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: calls.append(1) or FakeResponse())
    try:
        module.get_json("https://example.test/missing")
    except requests.HTTPError:
        pass
    else:
        raise AssertionError("Expected permanent 404 to raise")
    assert len(calls) == 1

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


def test_fetch_injuries_flattens_team_groups(monkeypatch):
    payload = {"injuries": [{
        "team": {"abbreviation": "BOS", "displayName": "Boston Celtics"},
        "injuries": [{
            "athlete": {"id": "123", "displayName": "Player One", "position": {"abbreviation": "G"}},
            "status": "Out", "type": {"name": "ankle"}, "date": "2026-11-20T00:00Z",
            "details": {"side": "Left", "returnDate": "2026-11-25"},
            "shortComment": "Will miss next game",
        }],
    }]}
    monkeypatch.setattr(module, "get_json", lambda url, params=None: payload)
    rows = module.fetch_injuries()
    assert len(rows) == 1
    assert rows[0]["athlete_id"] == "123"
    assert rows[0]["team"] == "BOS"
    assert rows[0]["status"] == "Out"
    assert rows[0]["return_date"] == "2026-11-25"


def test_fetch_injuries_supports_flat_rows_and_player_ids_in_links(monkeypatch):
    payload = {"injuries": [{
        "athlete": {
            "displayName": "Player Two",
            "team": {"abbreviation": "ATL", "displayName": "Atlanta Hawks"},
            "position": {"abbreviation": "F"},
            "links": [{"href": "https://www.espn.com/nba/player/_/id/987654/player-two"}],
        },
        "status": "Day-To-Day", "type": {"name": "ankle"},
        "details": {"side": "Left"}, "date": "2026-11-21T00:00Z",
    }]}
    monkeypatch.setattr(module, "get_json", lambda url, params=None: payload)
    rows = module.fetch_injuries()
    assert len(rows) == 1
    assert rows[0]["athlete_id"] == "987654"
    assert rows[0]["team"] == "ATL"
    assert rows[0]["status"] == "Day-To-Day"


def test_polymarket_discovery_includes_flat_player_props(monkeypatch):
    event_payload = [{
        "id": "event-1", "title": "Lakers vs Celtics", "slug": "nba-lal-bos-test",
        "endDate": "2099-01-01T00:00:00Z", "active": True, "closed": False,
        "markets": [{
            "id": "market-1", "question": "Lakers vs Celtics", "groupItemTitle": "Lakers",
            "slug": "nba-lal-bos-moneyline", "active": True, "closed": False,
            "outcomes": ["Lakers", "Celtics"], "outcomePrices": ["0.51", "0.49"],
            "volume24hr": 1200, "liquidity": 500,
        }],
    }]
    flat_markets = [{
        "id": "prop-1", "question": "Jayson Tatum over 25.5 points",
        "slug": "jayson-tatum-points-25pt5", "active": True, "closed": False,
        "events": [{"id": "event-1"}], "groupItemTitle": "Jayson Tatum: Points O/U 25.5", "outcomes": ["Yes", "No"],
        "outcomePrices": ["0.55", "0.45"], "volume24hr": 80,
    }]
    calls = []
    def fake_get_json(url, params=None):
        calls.append((url, params))
        return event_payload if url == module.GAMMA_EVENTS_URL else flat_markets
    monkeypatch.setattr(module, "get_json", fake_get_json)
    rows = module.fetch_polymarket_markets()
    assert {row["id"] for row in rows} == {"market-1", "prop-1"}
    assert next(row for row in rows if row["id"] == "market-1")["market_type"] == "moneyline"
    prop = next(row for row in rows if row["id"] == "prop-1")
    assert prop["event_id"] == "event-1"
    assert prop["market_type"] == "player_prop"
    assert any(params.get("tag_id") == "745" for _, params in calls)
