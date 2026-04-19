"""Shared pytest fixtures for cassie-system tests."""
import os
import sys
from pathlib import Path

import pytest

# Make memory.graph.* importable: the memory package lives at the project root,
# which is one level above cassie-system. Inserting this once here means all
# test modules can `from memory.graph.schema import create_schema` without any
# per-file path manipulation.
_PROJECT_ROOT = str(Path(__file__).parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


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
