"""Refresh public NBA schedule and Polymarket market snapshots."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
GAMMA_URL = "https://gamma-api.polymarket.com/markets"
GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events"
NBA_SERIES_ID = "10345"
INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
TIMEOUT = 25
NBA_TEAMS = {
    "hawks", "celtics", "nets", "hornets", "bulls", "cavaliers", "mavericks",
    "nuggets", "pistons", "warriors", "rockets", "pacers", "clippers", "lakers",
    "grizzlies", "heat", "bucks", "timberwolves", "pelicans", "knicks", "thunder",
    "magic", "76ers", "suns", "trail blazers", "kings", "spurs", "raptors", "jazz",
    "wizards",
}


def get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    response = requests.get(url, params=params, timeout=TIMEOUT, headers={"User-Agent": "NBA-Simulator/0.1"})
    response.raise_for_status()
    return response.json()


def fetch_games(today: datetime | None = None) -> list[dict[str, Any]]:
    today = today or datetime.now(timezone.utc)
    games: list[dict[str, Any]] = []
    for offset in range(3):
        date = (today + timedelta(days=offset)).strftime("%Y%m%d")
        payload = get_json(ESPN_URL, {"dates": date, "limit": 100})
        for event in payload.get("events", []):
            competitions = event.get("competitions") or []
            if not competitions:
                continue
            competition = competitions[0]
            competitors = competition.get("competitors") or []
            teams = {}
            for item in competitors:
                team = item.get("team") or {}
                side = item.get("homeAway")
                teams[side] = {
                    "id": team.get("id"),
                    "name": team.get("displayName") or team.get("name"),
                    "abbreviation": team.get("abbreviation"),
                    "score": item.get("score"),
                    "winner": item.get("winner"),
                }
            status = (event.get("status") or {}).get("type") or {}
            games.append({
                "id": str(event.get("id")),
                "date": event.get("date"),
                "name": event.get("name"),
                "short_name": event.get("shortName"),
                "status": status.get("name"),
                "status_detail": status.get("shortDetail"),
                "completed": bool(status.get("completed", False)),
                "home": teams.get("home"),
                "away": teams.get("away"),
                "venue": (competition.get("venue") or {}).get("fullName"),
                "source": "ESPN",
            })
    return games



def fetch_injuries() -> list[dict[str, Any]]:
    payload = get_json(INJURIES_URL)
    entries = payload.get("injuries") or []
    rows = []

    def flatten_links(value: Any) -> str:
        if isinstance(value, dict):
            return " ".join(flatten_links(v) for v in value.values())
        if isinstance(value, list):
            return " ".join(flatten_links(v) for v in value)
        return str(value or "")

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        nested = entry.get("injuries")
        if isinstance(nested, list):
            injury_rows = nested
        else:
            injury_rows = [entry]
        for injury in injury_rows:
            if not isinstance(injury, dict):
                continue
            athlete = injury.get("athlete") or {}
            if not isinstance(athlete, dict):
                athlete = {}
            team = injury.get("team") or entry.get("team") or athlete.get("team") or {}
            if not isinstance(team, dict):
                team = {}
            details = injury.get("details") or {}
            if not isinstance(details, dict):
                details = {}
            injury_type = injury.get("type") or {}
            if not isinstance(injury_type, dict):
                injury_type = {"name": injury_type}
            athlete_links = flatten_links(athlete.get("links") or athlete.get("link") or athlete.get("href"))
            athlete_id = str(athlete.get("id") or "")
            if not athlete_id:
                match = re.search(r"/id/(\d+)(?:/|$)", athlete_links)
                if match:
                    athlete_id = match.group(1)
            rows.append({
                "athlete_id": athlete_id,
                "name": athlete.get("displayName") or athlete.get("fullName") or injury.get("displayName"),
                "team": team.get("abbreviation") or athlete.get("teamAbbreviation"),
                "team_name": team.get("displayName") or team.get("name"),
                "position": (athlete.get("position") or {}).get("abbreviation") if isinstance(athlete.get("position"), dict) else athlete.get("position"),
                "status": injury.get("status") or details.get("status"),
                "type": injury_type.get("name") or details.get("type"),
                "side": details.get("side"),
                "date": injury.get("date"),
                "return_date": details.get("returnDate") or injury.get("returnDate"),
                "short_comment": injury.get("shortComment"),
                "long_comment": injury.get("longComment"),
                "source": "ESPN",
            })
    return rows


def _market_text(market: dict[str, Any]) -> str:
    return " ".join(
        str(market.get(key) or "")
        for key in ("question", "title", "slug")
    ).lower().strip()


def is_nba_market(market: dict[str, Any]) -> bool:
    text = _market_text(market)
    if re.search(r"\b(nba|basketball)\b", text):
        return True
    return any(re.search(r"\b" + re.escape(team) + r"\b", text) for team in NBA_TEAMS)


def fetch_polymarket_markets() -> list[dict[str, Any]]:
    # First discover active NBA game events, then supplement their nested
    # markets with the flat NBA-tag market feed so player props are not missed.
    events_payload = get_json(GAMMA_EVENTS_URL, {
        "series_id": NBA_SERIES_ID,
        "tag_id": "100639",
        "active": "true",
        "closed": "false",
        "limit": 500,
        "order": "volume24hr",
        "ascending": "false",
    })
    if isinstance(events_payload, dict):
        events = events_payload.get("events") or []
    elif isinstance(events_payload, list):
        events = events_payload
    else:
        events = []

    active_events = {}
    for event in events:
        if isinstance(event, dict) and event.get("id") is not None:
            active_events[str(event["id"])] = event
    results: dict[str, dict[str, Any]] = {}
    now = datetime.now(timezone.utc)

    def add_market(market: dict[str, Any], event: dict[str, Any]) -> None:
        event_title = event.get("title") or event.get("name") or ""
        combined = dict(market)
        combined["title"] = event_title
        if not is_nba_market(combined):
            return
        end_value = market.get("endDate") or market.get("end_date") or event.get("endDate") or event.get("end_date")
        if end_value:
            try:
                end_time = datetime.fromisoformat(str(end_value).replace("Z", "+00:00"))
                if end_time.tzinfo is None:
                    end_time = end_time.replace(tzinfo=timezone.utc)
                if end_time < now:
                    return
            except ValueError:
                pass
        market_id = str(market.get("id") or market.get("slug") or market.get("question") or "")
        if not market_id:
            return
        results[market_id] = {
            "id": str(market.get("id") or ""),
            "event_id": str(event.get("id") or ""),
            "event_title": event_title,
            "question": market.get("question") or market.get("title"),
            "slug": market.get("slug"),
            "active": market.get("active", event.get("active")),
            "closed": market.get("closed", event.get("closed")),
            "outcomes": market.get("outcomes"),
            "outcome_prices": market.get("outcomePrices") or market.get("outcome_prices"),
            "volume": market.get("volume") or market.get("volumeNum"),
            "volume_24h": market.get("volume24hr") or market.get("volume_24h"),
            "liquidity": market.get("liquidity") or market.get("liquidityNum"),
            "end_date": end_value,
            "market_group": market.get("groupItemTitle") or market.get("group_item_title"),
            "url": ("https://polymarket.com/event/" + str(event.get("slug"))) if event.get("slug") else (
                "https://polymarket.com/event/" + str(market.get("slug")) if market.get("slug") else None
            ),
            "source": "Polymarket Gamma NBA series",
        }

    for event in events:
        if not isinstance(event, dict):
            continue
        for market in event.get("markets") or []:
            if isinstance(market, dict):
                add_market(market, event)

    # Player props are sometimes exposed on the flat markets endpoint rather
    # than in the event's nested markets array. Keep only markets attached to
    # the currently active NBA game events found above.
    for offset in range(0, 5000, 500):
        page_payload = get_json(GAMMA_URL, {
            "tag_id": "745",
            "active": "true",
            "closed": "false",
            "limit": 500,
            "offset": offset,
        })
        if isinstance(page_payload, dict):
            page = page_payload.get("markets") or []
        elif isinstance(page_payload, list):
            page = page_payload
        else:
            page = []
        for market in page:
            if not isinstance(market, dict):
                continue
            associations = market.get("events") or []
            if isinstance(associations, dict):
                associations = [associations]
            event_id = str(market.get("event_id") or market.get("eventId") or "")
            matched_event = active_events.get(event_id)
            if not matched_event:
                for association in associations:
                    if not isinstance(association, dict):
                        continue
                    candidate = active_events.get(str(association.get("id") or ""))
                    if candidate:
                        matched_event = candidate
                        break
            if matched_event:
                add_market(market, matched_event)
        if len(page) < 500:
            break

    ordered = sorted(results.values(), key=lambda item: float(item.get("volume_24h") or 0), reverse=True)
    return ordered[:1200]


def write_snapshot(filename: str, source: str, key: str, rows: list[dict[str, Any]]) -> None:
    target = DATA / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "source": source,
        key: rows,
    }
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    games = fetch_games()
    markets = fetch_polymarket_markets()
    injuries = fetch_injuries()
    write_snapshot("games.json", "ESPN public scoreboard", "games", games)
    write_snapshot("polymarket.json", "Polymarket public Gamma API", "markets", markets)
    write_snapshot("injuries.json", "ESPN public injury report", "injuries", injuries)
    print(f"Saved {len(games)} NBA games, {len(markets)} likely NBA markets and {len(injuries)} injury records.")


if __name__ == "__main__":
    main()
