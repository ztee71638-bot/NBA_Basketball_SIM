"""Refresh public NBA schedule and Polymarket market snapshots."""
from __future__ import annotations

import json
import re
import time
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
    last_error = None
    for attempt in range(4):
        try:
            response = requests.get(url, params=params, timeout=TIMEOUT, headers={"User-Agent": "NBA-Simulator/0.1"})
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 3:
                    response.raise_for_status()
                wait = float(response.headers.get("Retry-After", 2 ** attempt))
                time.sleep(min(wait, 30))
                continue
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code and 400 <= status_code < 500 and status_code != 429:
                raise
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    if last_error:
        raise last_error
    raise RuntimeError("Unable to retrieve ESPN/Polymarket data")


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
            status = (event.get("status") or {}).get("type") or (competition.get("status") or {}).get("type") or {}
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




def _truthy(value: Any) -> bool:
    return value is True or str(value).strip().lower() in ("true", "1", "yes")


def parse_confirmed_lineups(payload: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    """Extract starters only when ESPN explicitly marks five for each team."""
    boxes = (payload.get("boxscore") or {}).get("players") or []
    collected: dict[str, dict[str, dict[str, Any]]] = {}

    def walk(node: Any, team_code: str | None = None) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child, team_code)
            return
        if not isinstance(node, dict):
            return
        team = node.get("team") or {}
        code = team.get("abbreviation") if isinstance(team, dict) else None
        if not code and isinstance(team, dict):
            code = {"1":"ATL","2":"BOS","3":"NOP","4":"CHI","5":"CLE","6":"DAL","7":"DEN","8":"DET","9":"GSW","10":"HOU","11":"IND","12":"LAC","13":"LAL","14":"MIA","15":"MIL","16":"MIN","17":"BKN","18":"NYK","19":"ORL","20":"PHI","21":"PHX","22":"POR","23":"SAC","24":"SAS","25":"OKC","26":"UTA","27":"WAS","28":"TOR","29":"MEM","30":"CHA"}.get(str(team.get("id") or ""))
        context = code or team_code
        athlete = node.get("athlete")
        if isinstance(athlete, dict) and context and ("starter" in node or "active" in node):
            name = athlete.get("displayName") or athlete.get("fullName")
            athlete_id = str(athlete.get("id") or "")
            if name and _truthy(node.get("starter")) and not _truthy(node.get("didNotPlay")):
                collected.setdefault(context, {})[athlete_id or str(name)] = {
                    "id": athlete_id, "name": name,
                    "position": (athlete.get("position") or {}).get("abbreviation") if isinstance(athlete.get("position"), dict) else athlete.get("position"),
                    "starter": True,
                }
        for key, value in node.items():
            if key not in ("team", "athlete"):
                walk(value, context)

    walk(boxes)
    home_code = (game.get("home") or {}).get("abbreviation")
    away_code = (game.get("away") or {}).get("abbreviation")
    home = list(collected.get(home_code, {}).values()) if home_code else []
    away = list(collected.get(away_code, {}).values()) if away_code else []
    confirmed = len(home) == 5 and len(away) == 5
    return {
        "game_id": str(game.get("id") or ""),
        "date": game.get("date"),
        "home_team": home_code,
        "away_team": away_code,
        "home_starters": home if confirmed else [],
        "away_starters": away if confirmed else [],
        "status": "confirmed" if confirmed else "not_available",
        "source": "ESPN game summary; starters explicitly flagged",
    }


def fetch_confirmed_lineups(games: list[dict[str, Any]], now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    rows = []
    for game in games:
        if game.get("completed") or not game.get("date") or not game.get("id"):
            continue
        try:
            start = datetime.fromisoformat(str(game["date"]).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        # Check close to tipoff to avoid repeatedly querying distant games.
        if start < now - timedelta(hours=2) or start > now + timedelta(hours=8):
            continue
        try:
            summary = get_json(
                "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary",
                {"event": str(game["id"])},
            )
            rows.append(parse_confirmed_lineups(summary, game))
        except requests.RequestException as exc:
            rows.append({
                "game_id": str(game["id"]), "date": game.get("date"),
                "status": "unavailable", "error": str(exc), "source": "ESPN",
            })
    return rows


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
        question = market.get("question") or market.get("title")
        group_title = market.get("groupItemTitle") or market.get("group_item_title")
        question_lower = str(question or "").lower()
        group_lower = str(group_title or "").lower()
        if question_lower == str(event_title).lower():
            market_type = "moneyline"
        elif question_lower.startswith("spread:"):
            market_type = "spread"
        elif group_title and ":" in str(group_title) and any(
            stat in group_lower for stat in ("points", "rebounds", "assists", "threes", "steals", "blocks")
        ):
            market_type = "player_prop"
        elif "o/u" in question_lower or "over/under" in question_lower:
            market_type = "total"
        else:
            market_type = "other"
        results[market_id] = {
            "id": str(market.get("id") or ""),
            "event_id": str(event.get("id") or ""),
            "event_title": event_title,
            "question": question,
            "market_type": market_type,
            "slug": market.get("slug"),
            "active": market.get("active", event.get("active")),
            "closed": market.get("closed", event.get("closed")),
            "outcomes": market.get("outcomes"),
            "outcome_prices": market.get("outcomePrices") or market.get("outcome_prices"),
            "volume": market.get("volume") or market.get("volumeNum"),
            "volume_24h": market.get("volume24hr") or market.get("volume_24h"),
            "liquidity": market.get("liquidity") or market.get("liquidityNum"),
            "end_date": end_value,
            "market_group": group_title,
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
    flat_seen = 0
    flat_matched = 0
    flat_slug_matched = 0
    for offset in range(0, 2001, 100):
        page_payload = get_json(GAMMA_URL, {
            "tag_id": "745",
            "active": "true",
            "closed": "false",
            "limit": 100,
            "offset": offset,
            "order": "endDate",
            "ascending": "true",
        })
        if isinstance(page_payload, dict):
            page = page_payload.get("markets") or []
        elif isinstance(page_payload, list):
            page = page_payload
        else:
            page = []
        flat_seen += len(page)
        if offset == 0 and page:
            sample = page[0]
            print("Polymarket flat-market sample:", {key: sample.get(key) for key in ("id", "slug", "question", "event_id", "eventId", "events", "groupItemTitle")})
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
                    if not candidate and association.get("slug"):
                        candidate = next((item for item in active_events.values() if item.get("slug") == association.get("slug")), None)
                    if candidate:
                        matched_event = candidate
                        break
            if not matched_event:
                market_slug = str(market.get("slug") or "")
                matched_event = next(
                    (item for item in active_events.values()
                     if item.get("slug") and market_slug.startswith(str(item["slug"]) + "-")),
                    None,
                )
                if matched_event:
                    flat_slug_matched += 1
            if matched_event:
                flat_matched += 1
                add_market(market, matched_event)
        if len(page) < 100:
            break

    print(f"Polymarket NBA discovery: {len(events)} active game events, {flat_seen} flat NBA markets scanned, {flat_matched} linked to active games ({flat_slug_matched} by event-slug prefix), {len(results)} unique markets.")
    ordered = sorted(results.values(), key=lambda item: float(item.get("volume_24h") or 0), reverse=True)
    return ordered[:1500]


def write_snapshot(filename: str, source: str, key: str, rows: list[dict[str, Any]]) -> None:
    target = DATA / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "source": source,
        key: rows,
    }
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def archive_market_snapshots(
    markets: list[dict[str, Any]],
    now: datetime | None = None,
    max_snapshots: int = 500,
) -> int:
    """Append price/line changes for active NBA game markets by Polymarket event."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for market in markets:
        if market.get("market_type") not in {"moneyline", "spread", "total"}:
            continue
        if not _truthy(market.get("active")) or _truthy(market.get("closed")):
            continue
        end_value = market.get("end_date")
        if end_value:
            try:
                end_time = datetime.fromisoformat(str(end_value).replace("Z", "+00:00"))
                if end_time.tzinfo is None:
                    end_time = end_time.replace(tzinfo=timezone.utc)
                if end_time <= now:
                    continue
            except ValueError:
                continue
        event_id = str(market.get("event_id") or "")
        market_id = str(market.get("id") or "")
        if not event_id or not market_id:
            continue
        grouped.setdefault(event_id, []).append({
            "market_id": market_id,
            "market_type": market.get("market_type"),
            "question": market.get("question"),
            "slug": market.get("slug"),
            "outcomes": market.get("outcomes"),
            "outcome_prices": market.get("outcome_prices"),
            "volume_24h": market.get("volume_24h"),
            "liquidity": market.get("liquidity"),
            "end_date": end_value,
            "url": market.get("url"),
        })

    root = DATA / "snapshots" / "markets"
    archived = 0
    for event_id, rows in grouped.items():
        rows.sort(key=lambda row: (str(row.get("market_type")), str(row.get("market_id"))))
        event_title = next((market.get("event_title") for market in markets
                            if str(market.get("event_id") or "") == event_id), None)
        signature_data = [{
            "market_id": row["market_id"],
            "market_type": row["market_type"],
            "question": row["question"],
            "outcomes": row["outcomes"],
            "outcome_prices": row["outcome_prices"],
        } for row in rows]
        signature = json.dumps(signature_data, sort_keys=True, separators=(",", ":"))
        safe_event_id = re.sub(r"[^A-Za-z0-9_-]", "", event_id)
        if not safe_event_id:
            continue
        target = root / f"{safe_event_id}.json"
        if target.exists():
            payload = json.loads(target.read_text(encoding="utf-8"))
        else:
            payload = {
                "event_id": event_id,
                "event_title": event_title,
                "source": "Polymarket public Gamma API",
                "snapshots": [],
            }
        snapshots = payload.setdefault("snapshots", [])
        if snapshots and snapshots[-1].get("signature") == signature:
            continue
        snapshots.append({
            "captured_at": now.isoformat(),
            "markets": rows,
            "signature": signature,
        })
        if len(snapshots) > max_snapshots:
            del snapshots[:-max_snapshots]
        payload["last_updated"] = now.isoformat()
        root.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(target)
        archived += 1
    return archived

def archive_pregame_availability(
    games: list[dict[str, Any]],
    injuries: list[dict[str, Any]],
    lineups: list[dict[str, Any]],
    now: datetime | None = None,
) -> int:
    """Archive meaningful availability changes for games within eight hours of tipoff.

    Snapshots are append-only per game and are written only when injury or
    confirmed-lineup information changes. Historical availability can later
    support point-in-time injury-impact research without pretending today's
    injury report was known before an old game.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    root = DATA / "snapshots" / "availability"
    root.mkdir(parents=True, exist_ok=True)
    lineup_by_game = {str(row.get("game_id")): row for row in lineups if row.get("game_id")}
    archived = 0
    for game in games:
        game_id = str(game.get("id") or "")
        if not game_id or game.get("completed") or not game.get("date"):
            continue
        try:
            start = datetime.fromisoformat(str(game["date"]).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        minutes_to_tipoff = (start - now).total_seconds() / 60
        if minutes_to_tipoff < 0 or minutes_to_tipoff > 8 * 60:
            continue
        home = (game.get("home") or {}).get("abbreviation")
        away = (game.get("away") or {}).get("abbreviation")
        team_codes = {code for code in (home, away) if code}
        if len(team_codes) != 2:
            continue
        game_injuries = sorted(
            [row for row in injuries if row.get("team") in team_codes],
            key=lambda row: (
                str(row.get("team") or ""),
                str(row.get("athlete_id") or ""),
                str(row.get("name") or ""),
            ),
        )
        lineup = lineup_by_game.get(game_id)
        signature = {"injuries": game_injuries, "lineup": lineup}
        safe_game_id = re.sub(r"[^A-Za-z0-9_-]", "", game_id)
        target = root / f"{safe_game_id}.json"
        if target.exists():
            payload = json.loads(target.read_text(encoding="utf-8"))
        else:
            payload = {
                "game_id": game_id,
                "game_date": game.get("date"),
                "home_team": home,
                "away_team": away,
                "source": "ESPN public injury report and game summaries",
                "snapshots": [],
            }
        snapshots = payload.setdefault("snapshots", [])
        if snapshots and snapshots[-1].get("signature") == signature:
            continue
        snapshots.append({
            "captured_at": now.isoformat(),
            "minutes_to_tipoff": round(minutes_to_tipoff, 1),
            "injuries": game_injuries,
            "lineup": lineup,
            "signature": signature,
        })
        payload["last_updated"] = now.isoformat()
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(target)
        archived += 1
    return archived


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    games = fetch_games()
    markets = fetch_polymarket_markets()
    injuries = fetch_injuries()
    lineups = fetch_confirmed_lineups(games)
    write_snapshot("games.json", "ESPN public scoreboard", "games", games)
    write_snapshot("polymarket.json", "Polymarket public Gamma API", "markets", markets)
    write_snapshot("injuries.json", "ESPN public injury report", "injuries", injuries)
    write_snapshot("lineups.json", "ESPN game summaries", "games", lineups)
    snapshot_time = datetime.now(timezone.utc)
    market_snapshots = archive_market_snapshots(markets, snapshot_time)
    availability_snapshots = archive_pregame_availability(games, injuries, lineups, snapshot_time)
    confirmed = sum(1 for item in lineups if item.get("status") == "confirmed")
    print(
        f"Saved {len(games)} NBA games, {len(markets)} likely NBA markets, "
        f"{len(injuries)} injury records, {confirmed} confirmed starting lineups, "
        f"{market_snapshots} changed market-price snapshots and "
        f"{availability_snapshots} changed pregame availability snapshots."
    )


if __name__ == "__main__":
    main()
