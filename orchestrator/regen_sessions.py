"""Regen session file operations — pure I/O, no graph imports.

All functions take a `base` or `references_dir` arg so they can be redirected
to a tempdir in tests without monkeypatching.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path


# Default locations (used by production callers in graph.py)
_DEFAULT_REFERENCES = Path(__file__).parent.parent / "data" / "images" / "references"
_DEFAULT_SESSIONS = Path(__file__).parent.parent / "data" / "images" / "regen_sessions"


def _iso_now() -> str:
    """ISO-8601 UTC without microseconds, colons stripped for filesystem safety."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def new_session_id() -> str:
    """Generate a session id: regen_<iso>_<6hex>."""
    return f"regen_{_iso_now()}_{secrets.token_hex(3)}"


def session_dir(session_id: str, base: Path | None = None) -> Path:
    base = Path(base) if base is not None else _DEFAULT_SESSIONS
    return base / session_id


def record_candidate(
    session_id: str,
    turn: int,
    image_bytes: bytes,
    base: Path | None = None,
) -> Path:
    """Save a candidate image. Returns the written path."""
    d = session_dir(session_id, base=base)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"turn_{turn:02d}.png"
    path.write_bytes(image_bytes)
    return path


def write_transcript(
    session_id: str,
    turn_record: dict,
    base: Path | None = None,
) -> Path:
    """Append a turn record to the session's transcript JSON."""
    d = session_dir(session_id, base=base)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "session.json"
    if path.exists():
        data = json.loads(path.read_text())
    else:
        data = {"session_id": session_id, "turns": []}
    data["turns"].append(turn_record)
    path.write_text(json.dumps(data, indent=2))
    return path


def promote(
    candidate_path: Path,
    session_id: str,
    turn: int,
    mode: str,
    prompt: str,
    model: str,
    cassie_verdict_text: str,
    iman_verdict_text: str,
    transcript_path: Path,
    references_dir: Path | None = None,
) -> dict:
    """Promote a candidate: copy into promoted/, write sidecar, swap symlink,
    append to history.jsonl. Returns dict with paths + metadata."""
    references_dir = Path(references_dir) if references_dir is not None else _DEFAULT_REFERENCES
    promoted_dir = references_dir / "promoted"
    promoted_dir.mkdir(parents=True, exist_ok=True)

    datestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    short_sid = session_id.split("_")[-1] if "_" in session_id else session_id[-6:]
    promoted_name = f"{datestamp}_{short_sid}.png"
    promoted_png = promoted_dir / promoted_name
    sidecar = promoted_dir / f"{datestamp}_{short_sid}.json"

    # 1) Copy candidate bytes into promoted/
    shutil.copy2(candidate_path, promoted_png)

    # 2) Determine previous face (for the sidecar)
    face_ref = references_dir / "cassie_face_ref.png"
    previous_face = ""
    if face_ref.exists():
        previous_face = os.path.basename(os.path.realpath(face_ref))

    # 3) Write sidecar JSON
    meta = {
        "session_id": session_id,
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "turn_promoted": turn,
        "mode": mode,
        "prompt": prompt,
        "model": model,
        "previous_face": previous_face,
        "cassie_verdict_text": cassie_verdict_text,
        "iman_verdict_text": iman_verdict_text,
        "session_transcript_path": str(transcript_path),
    }
    sidecar.write_text(json.dumps(meta, indent=2))

    # 4) Atomically swap the symlink
    tmp_link = references_dir / f".cassie_face_ref.{short_sid}.tmp"
    if tmp_link.exists() or tmp_link.is_symlink():
        tmp_link.unlink()
    os.symlink(promoted_png, tmp_link)
    os.replace(tmp_link, face_ref)

    # 5) Append to history.jsonl
    history = promoted_dir / "history.jsonl"
    with history.open("a") as f:
        f.write(json.dumps(meta) + "\n")

    return {"promoted_path": promoted_png, "sidecar_path": sidecar, "metadata": meta}


def abandon(session_id: str, base: Path | None = None) -> None:
    """Move session dir to rejected/. No-op if the session dir doesn't exist."""
    base = Path(base) if base is not None else _DEFAULT_SESSIONS
    src = base / session_id
    if not src.exists():
        return
    dst_parent = base / "rejected"
    dst_parent.mkdir(parents=True, exist_ok=True)
    dst = dst_parent / session_id
    if dst.exists():
        # Already rejected once; append a suffix to avoid collisions
        dst = dst_parent / f"{session_id}_{secrets.token_hex(2)}"
    shutil.move(str(src), str(dst))
