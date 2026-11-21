"""Import independently published NBA Stats-derived CSVs as a supplemental archive.

BoxScore Lab publishes nightly CSV exports under CC BY 4.0. These records are
kept separately from ESPN's canonical game/player archives until keys and
field-level definitions have been reconciled. This prevents an unverified
third-party field mapping from silently changing production model inputs.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "supplemental" / "boxscorelab"
BASE_URL = "https://boxscorelab.com/downloads"
TIMEOUT = 30
DATASETS = {
    "2025-26": {
        "team_games": "2025-26-team-game-results.csv",
        "player_totals": "2025-26-player-season-totals.csv",
        "team_standings": "2025-26-team-standings.csv",
    },
    "2026-27": {
        "team_games": "2026-27-team-game-results.csv",
        "player_totals": "2026-27-player-season-totals.csv",
        "team_standings": "2026-27-team-standings.csv",
    },
}
MINIMUM_ROWS = {
    ("2025-26", "team_games"): 2000,
    ("2026-27", "team_games"): 100,
    ("2025-26", "player_totals"): 250,
    ("2026-27", "player_totals"): 100,
    ("2025-26", "team_standings"): 30,
    ("2026-27", "team_standings"): 30,
}


def fetch_csv(url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = requests.get(
                url, timeout=TIMEOUT,
                headers={"User-Agent": "NBA-Simulator/0.1", "Accept": "text/csv,*/*"},
            )
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 3:
                    response.raise_for_status()
                time.sleep(min(float(response.headers.get("Retry-After", 2 ** attempt)), 30))
                continue
            response.raise_for_status()
            if not response.text.strip():
                raise RuntimeError(f"Empty CSV response from {url}")
            return response.text.lstrip("\ufeff")
        except requests.RequestException as exc:
            last_error = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status and 400 <= status < 500 and status != 429:
                raise
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    if last_error:
        raise last_error
    raise RuntimeError(f"Could not download {url}")


def parse_and_validate_csv(text: str, season: str, kind: str) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(text))
    columns = [str(name).strip() for name in (reader.fieldnames or [])]
    if len(columns) < 5 or any(not name for name in columns):
        raise ValueError(f"{season} {kind}: missing or malformed CSV header: {columns}")
    rows = [
        {str(key).strip(): (value.strip() if isinstance(value, str) else value)
         for key, value in row.items() if key is not None}
        for row in reader
    ]
    minimum = MINIMUM_ROWS[(season, kind)]
    if len(rows) < minimum:
        raise ValueError(
            f"{season} {kind}: only {len(rows)} rows; expected at least {minimum}"
        )
    if any(not any(value not in (None, "") for value in row.values()) for row in rows):
        raise ValueError(f"{season} {kind}: contains an entirely blank row")

    # Record duplicate rows and recognizable entity coverage without assuming
    # provider-specific column names. The raw headers remain available for a
    # later exact, tested mapping into the canonical ESPN records.
    signatures = [tuple(row.get(column, "") for column in columns) for row in rows]
    duplicate_rows = len(signatures) - len(set(signatures))
    aliases = {
        "team": ("team", "team_abbreviation", "team_code", "team_abbr", "abbr"),
        "game": ("game_id", "gameid", "event_id", "eventid"),
        "player": ("player", "player_name", "name"),
    }
    lowered = {column.lower(): column for column in columns}
    detected = {
        label: next((lowered[name] for name in candidates if name in lowered), None)
        for label, candidates in aliases.items()
    }
    unique_teams = (
        len({row.get(detected["team"]) for row in rows if row.get(detected["team"])})
        if detected["team"] else None
    )
    unique_games = (
        len({row.get(detected["game"]) for row in rows if row.get(detected["game"])})
        if detected["game"] else None
    )
    unique_players = (
        len({row.get(detected["player"]) for row in rows if row.get(detected["player"])})
        if detected["player"] else None
    )
    if kind in ("team_games", "team_standings") and detected["team"] and unique_teams != 30:
        raise ValueError(
            f"{season} {kind}: expected 30 NBA teams, detected {unique_teams}"
        )
    if kind == "team_standings" and len(rows) != 30:
        raise ValueError(f"{season} standings: expected exactly 30 rows, got {len(rows)}")
    if kind == "team_games" and detected["game"] and unique_games < 50:
        raise ValueError(f"{season} team games: suspiciously few unique games ({unique_games})")

    return {
        "season": season,
        "dataset": kind,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "duplicate_full_rows": duplicate_rows,
        "detected_keys": detected,
        "unique_teams": unique_teams,
        "unique_games": unique_games,
        "unique_players": unique_players,
    }


def main(output_dir: Path = OUTPUT) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    manifest: dict[str, Any] = {
        "provider": "BoxScore Lab",
        "upstream_source": "NBA Stats public data, as described by provider",
        "license": "CC BY 4.0",
        "attribution": "BoxScore Lab, boxscorelab.com, downloaded by NBA Basketball Simulator",
        "retrieved_at": retrieved_at,
        "datasets": {},
    }
    for season, files in DATASETS.items():
        for kind, filename in files.items():
            url = f"{BASE_URL}/{filename}"
            print(f"Downloading {season} {kind}: {url}", flush=True)
            parsed = parse_and_validate_csv(fetch_csv(url), season, kind)
            parsed.update({
                "source_url": url,
                "provider_data_through": "2026-11-21",
                "retrieved_at": retrieved_at,
                "license": "CC BY 4.0",
                "attribution": "BoxScore Lab (boxscorelab.com); underlying source stated as NBA Stats",
            })
            destination = output_dir / f"{season.replace('-', '_')}_{kind}.json"
            destination.write_text(
                json.dumps(parsed, ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            manifest["datasets"][f"{season}:{kind}"] = {
                "file": destination.name,
                "rows": parsed["row_count"],
                "columns": parsed["columns"],
                "duplicate_full_rows": parsed["duplicate_full_rows"],
                "unique_teams": parsed["unique_teams"],
                "unique_games": parsed["unique_games"],
                "unique_players": parsed["unique_players"],
                "source_url": url,
            }
            print(
                f"Validated {season} {kind}: {parsed['row_count']} rows, "
                f"{len(parsed['columns'])} columns, {parsed['duplicate_full_rows']} "
                f"duplicate full rows; columns={parsed['columns']}",
                flush=True,
            )
            print(
                f"Sample {season} {kind} rows: "
                f"{json.dumps(parsed['rows'][:2], ensure_ascii=False)}",
                flush=True,
            )
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print("Supplemental NBA data archive imported and validated.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    main(parser.parse_args().output_dir)
