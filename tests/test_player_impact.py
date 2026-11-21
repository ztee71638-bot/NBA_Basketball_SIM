import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from refresh_player_impact import build_payload, parse_hapm_csv


HEADER = "pid,name,team,pos,season,version,poss,net,O,D,young_teammates"
ROWS = [
    "1,Player One,BOS,G,2025-26,3/3,900,3.2,2.0,1.2,",
    "2,Player Two,LAL,F,2026-27,3/3,500,-1.5,-0.5,-1.0,1",
    "3,Player Three,NYK,G,2026-27,2/3,700,4.0,2.0,2.0,",
    "4,Player Four,MIA,C,2026-27,3/3,100,9.0,5.0,4.0,",
]


def test_parser_keeps_only_two_seasons_version_and_minimum_sample():
    rows = parse_hapm_csv(HEADER + "\n" + "\n".join(ROWS))
    assert len(rows) == 2
    assert {row["name"] for row in rows} == {"Player One", "Player Two"}
    assert rows[1]["young_teammates"] == "1"


def test_payload_has_source_credit_and_season_counts():
    # The production safety gate requires a realistic number of records.
    content = HEADER + "\n" + "\n".join(
        [f"{i},Player {i},BOS,G,2025-26,3/3,500,1.0,0.5,0.5," for i in range(300)] +
        [f"{i+300},Player {i+300},LAL,G,2026-27,3/3,500,1.0,0.5,0.5," for i in range(100)]
    )
    payload = build_payload(content, "2026-11-21T00:00:00+00:00")
    assert payload["record_count"] == 400
    assert payload["counts_by_season"] == {"2025-26": 300, "2026-27": 100}
    assert payload["license"] == "CC BY 4.0"



def test_player_impact_snapshot_is_immutable_per_utc_day(tmp_path):
    from refresh_player_impact import write_immutable_snapshot
    payload = {
        "last_updated": "2026-11-21T23:30:00+00:00",
        "record_count": 400,
        "players": [{"player_id": "1", "net": 3.2}],
    }
    path = write_immutable_snapshot(payload, tmp_path)
    original = path.read_text(encoding="utf-8")
    assert path.name == "player-impact-20261121.json"

    changed = {**payload, "record_count": 999}
    second_path = write_immutable_snapshot(changed, tmp_path)
    assert second_path == path
    assert path.read_text(encoding="utf-8") == original
