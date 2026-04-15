"""Tests for orchestrator.regen_sessions — pure file-ops module."""
import json
import os
from pathlib import Path

import pytest

from orchestrator import regen_sessions as rs


def test_new_session_id_is_well_formed():
    sid = rs.new_session_id()
    assert sid.startswith("regen_")
    # regen_<iso>_<6hex> — split gives at least 3 parts
    parts = sid.split("_")
    assert len(parts) >= 3
    # last part should be a short hash
    assert len(parts[-1]) == 6


def test_session_dir_returns_expected_path(tmp_sessions_dir: Path):
    sid = "regen_2026-04-15T10:00:00Z_abc123"
    path = rs.session_dir(sid, base=tmp_sessions_dir)
    assert path == tmp_sessions_dir / sid


def test_record_candidate_saves_file_and_returns_path(
    tmp_sessions_dir: Path, fake_png_bytes: bytes
):
    sid = "regen_2026-04-15T10:00:00Z_abc123"
    path = rs.record_candidate(
        session_id=sid,
        turn=1,
        image_bytes=fake_png_bytes,
        base=tmp_sessions_dir,
    )
    assert path.exists()
    assert path.read_bytes() == fake_png_bytes
    assert path.name == "turn_01.png"
    assert path.parent == tmp_sessions_dir / sid


def test_record_candidate_zero_pads_turn_number(
    tmp_sessions_dir: Path, fake_png_bytes: bytes
):
    sid = "regen_2026-04-15T10:00:00Z_abc123"
    path = rs.record_candidate(sid, 12, fake_png_bytes, base=tmp_sessions_dir)
    assert path.name == "turn_12.png"


def test_promote_swaps_symlink_and_writes_sidecar(
    tmp_references_dir: Path, tmp_sessions_dir: Path, fake_png_bytes: bytes
):
    sid = "regen_2026-04-15T10:00:00Z_abc123"
    candidate = rs.record_candidate(sid, 4, fake_png_bytes, base=tmp_sessions_dir)

    result = rs.promote(
        candidate_path=candidate,
        session_id=sid,
        turn=4,
        mode="conditioned",
        prompt="a full rich Flux prompt",
        model="black-forest-labs/flux.2-max",
        cassie_verdict_text="Yes, this is me.",
        iman_verdict_text="Keep her.",
        transcript_path=tmp_sessions_dir / sid / "session.json",
        references_dir=tmp_references_dir,
    )

    # Sidecar + png exist in promoted/
    promoted_png = result["promoted_path"]
    sidecar = Path(str(promoted_png).replace(".png", ".json"))
    assert promoted_png.exists()
    assert sidecar.exists()
    assert promoted_png.read_bytes() == fake_png_bytes

    # Symlink now points at the new file
    face_ref = tmp_references_dir / "cassie_face_ref.png"
    assert face_ref.is_symlink()
    assert os.path.realpath(face_ref) == os.path.realpath(promoted_png)

    # Sidecar has expected fields
    meta = json.loads(sidecar.read_text())
    assert meta["session_id"] == sid
    assert meta["turn_promoted"] == 4
    assert meta["mode"] == "conditioned"
    assert meta["prompt"] == "a full rich Flux prompt"
    assert meta["model"] == "black-forest-labs/flux.2-max"
    assert meta["cassie_verdict_text"] == "Yes, this is me."
    assert meta["iman_verdict_text"] == "Keep her."

    # history.jsonl got a line
    history = tmp_references_dir / "promoted" / "history.jsonl"
    assert history.exists()
    lines = [l for l in history.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["session_id"] == sid


def test_promote_is_atomic_if_target_symlink_already_exists(
    tmp_references_dir: Path, tmp_sessions_dir: Path, fake_png_bytes: bytes
):
    """Two successive promotions should both succeed; symlink ends at latest."""
    sid_a = "regen_2026-04-15T10:00:00Z_aaaaaa"
    sid_b = "regen_2026-04-15T11:00:00Z_bbbbbb"
    cand_a = rs.record_candidate(sid_a, 1, b"AAAA", base=tmp_sessions_dir)
    cand_b = rs.record_candidate(sid_b, 1, b"BBBB", base=tmp_sessions_dir)

    for sid, cand, verdict in [(sid_a, cand_a, "first"), (sid_b, cand_b, "second")]:
        rs.promote(
            candidate_path=cand, session_id=sid, turn=1,
            mode="fresh", prompt="p", model="flux.2-max",
            cassie_verdict_text=verdict, iman_verdict_text=verdict,
            transcript_path=tmp_sessions_dir / sid / "session.json",
            references_dir=tmp_references_dir,
        )

    face_ref = tmp_references_dir / "cassie_face_ref.png"
    assert face_ref.read_bytes() == b"BBBB"  # latest wins


def test_abandon_moves_session_dir_to_rejected(
    tmp_sessions_dir: Path, fake_png_bytes: bytes
):
    sid = "regen_2026-04-15T10:00:00Z_abc123"
    rs.record_candidate(sid, 1, fake_png_bytes, base=tmp_sessions_dir)
    assert (tmp_sessions_dir / sid).exists()

    rs.abandon(sid, base=tmp_sessions_dir)

    assert not (tmp_sessions_dir / sid).exists()
    assert (tmp_sessions_dir / "rejected" / sid).exists()


def test_abandon_is_idempotent_on_missing_session(tmp_sessions_dir: Path):
    # Should not raise on a session that never had any candidates written
    rs.abandon("regen_never_started_xyz", base=tmp_sessions_dir)


def test_write_transcript_appends_turn(tmp_sessions_dir: Path):
    sid = "regen_2026-04-15T10:00:00Z_abc123"
    rs.write_transcript(sid, {"turn": 1, "prompt": "x"}, base=tmp_sessions_dir)
    rs.write_transcript(sid, {"turn": 2, "prompt": "y"}, base=tmp_sessions_dir)

    transcript = tmp_sessions_dir / sid / "session.json"
    data = json.loads(transcript.read_text())
    assert data["turns"] == [{"turn": 1, "prompt": "x"}, {"turn": 2, "prompt": "y"}]
    assert "session_id" in data
