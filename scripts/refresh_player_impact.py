"""Refresh LUMA held-out adjusted plus-minus player impact ratings.

The upstream CSV is published under CC BY 4.0. We keep only the two latest
NBA seasons and the 3/3 HAPM blend, then publish a compact JSON snapshot.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "player_impact.json"
SNAPSHOT_DIR = ROOT / "data" / "snapshots" / "player-impact"
SOURCE_URL = "https://raw.githubusercontent.com/lumahoops/NBA/main/hapm/v1/hapm_season_boards.csv"
SEASONS = ("2025-26", "2026-27")
VERSION = "3/3"
MIN_POSSESSIONS = 250


def number(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_hapm_csv(content: str) -> list[dict]:
    rows = []
    reader = csv.DictReader(io.StringIO(content))
    required = {"pid", "name", "team", "season", "version", "poss", "net", "O", "D"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("LUMA HAPM CSV is missing required columns")
    for row in reader:
        if row.get("season") not in SEASONS or row.get("version") != VERSION:
            continue
        possessions = number(row.get("poss"))
        net = number(row.get("net"))
        offense = number(row.get("O"))
        defense = number(row.get("D"))
        if possessions is None or possessions < MIN_POSSESSIONS or net is None:
            continue
        rows.append({
            "player_id": row.get("pid"),
            "name": row.get("name"),
            "team": row.get("team"),
            "position": row.get("pos"),
            "season": row.get("season"),
            "version": row.get("version"),
            "possessions": int(possessions),
            "net": net,
            "offense": offense,
            "defense": defense,
            "young_teammates": (row.get("young_teammates") or "").strip() or None,
        })
    return rows


def build_payload(content: str, updated_at: str | None = None) -> dict:
    rows = parse_hapm_csv(content)
    counts = {season: sum(row["season"] == season for row in rows) for season in SEASONS}
    # Protect the published file from a truncated or incomplete upstream export.
    if counts["2025-26"] < 300 or counts["2026-27"] < 100:
        raise RuntimeError(f"Incomplete LUMA HAPM snapshot; row counts: {counts}")
    return {
        "last_updated": updated_at or datetime.now(timezone.utc).isoformat(),
        "source": "LUMA Basketball Research HAPM v1, 3/3 blend",
        "source_url": SOURCE_URL,
        "license": "CC BY 4.0",
        "credit": "LUMA Basketball Research / CourtShare — https://lumahoops.org/luma",
        "metric": "Held-out adjusted plus-minus, points per 100 possessions relative to the average rated player",
        "minimum_possessions": MIN_POSSESSIONS,
        "seasons": list(SEASONS),
        "version": VERSION,
        "record_count": len(rows),
        "counts_by_season": counts,
        "players": rows,
    }


def write_immutable_snapshot(payload: dict, snapshot_dir: Path = SNAPSHOT_DIR) -> Path:
    """Archive one immutable, UTC-date-stamped point-in-time impact snapshot."""
    updated = datetime.fromisoformat(str(payload["last_updated"]).replace("Z", "+00:00"))
    stamp = updated.astimezone(timezone.utc).strftime("%Y%m%d")
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_dir / f"player-impact-{stamp}.json"
    if path.exists():
        print(f"Immutable player-impact snapshot already exists: {path.name}")
        return path
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def fetch_source() -> str:
    request = Request(SOURCE_URL, headers={"User-Agent": "NBA-Simulator/1.0"})
    with urlopen(request, timeout=60) as response:
        if response.status != 200:
            raise RuntimeError(f"LUMA returned HTTP {response.status}")
        return response.read().decode("utf-8-sig")


def main() -> None:
    payload = build_payload(fetch_source())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    snapshot = write_immutable_snapshot(payload)
    print(f"Saved {payload['record_count']} HAPM records: {payload['counts_by_season']}; archived {snapshot.name}")


if __name__ == "__main__":
    main()
