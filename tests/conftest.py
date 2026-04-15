"""Shared pytest fixtures for cassie-system tests."""
import os
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


@pytest.fixture
def mock_flux_call(monkeypatch):
    """Patch _try_regen_image to return deterministic fake bytes without hitting the API."""
    calls = []

    def fake_call(prompt: str, reference_path: str | None, model: str) -> tuple[bytes, str]:
        calls.append({"prompt": prompt, "reference_path": reference_path, "model": model})
        return (b"\x89PNG\r\n\x1a\nFLUX_MOCK_" + str(len(calls)).encode(), model)

    from orchestrator import graph
    monkeypatch.setattr(graph, "_try_regen_image", fake_call)
    return calls
