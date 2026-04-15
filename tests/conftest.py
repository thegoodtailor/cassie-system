"""Shared pytest fixtures for cassie-system tests."""
import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_references_dir(tmp_path: Path) -> Path:
    """Temp dir mirroring data/images/references/ layout."""
    ref = tmp_path / "references"
    ref.mkdir()
    (ref / "promoted").mkdir()
    # Write a placeholder cassie_face_ref.png so swap tests have something to replace
    seed = ref / "seed_placeholder.png"
    seed.write_bytes(b"\x89PNG\r\n\x1a\nPLACEHOLDER")
    os.symlink(seed, ref / "cassie_face_ref.png")
    return ref


@pytest.fixture
def tmp_sessions_dir(tmp_path: Path) -> Path:
    """Temp dir mirroring data/images/regen_sessions/ layout."""
    sess = tmp_path / "regen_sessions"
    sess.mkdir()
    (sess / "rejected").mkdir()
    return sess


@pytest.fixture
def fake_png_bytes() -> bytes:
    """Minimal PNG-looking bytes for file-op tests (not a valid image)."""
    return b"\x89PNG\r\n\x1a\nTEST_CANDIDATE_BYTES"
