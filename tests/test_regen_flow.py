"""End-to-end regen flow test with mocked Director + Flux.

Walks: start → continue (reject) → promote.
Also: start → abandon.
"""
from pathlib import Path

import pytest

from orchestrator import graph, regen_sessions as rs


@pytest.fixture
def wired_tmp(monkeypatch, tmp_path):
    """Redirect all regen filesystem locations into tmp_path."""
    import os as _os
    refs = tmp_path / "references"
    refs.mkdir()
    (refs / "promoted").mkdir()
    seed = refs / "seed.png"
    seed.write_bytes(b"INITIAL_FACE")
    _os.symlink(seed, refs / "cassie_face_ref.png")

    sessions = tmp_path / "sessions"
    sessions.mkdir()

    monkeypatch.setattr(rs, "_DEFAULT_REFERENCES", refs)
    monkeypatch.setattr(rs, "_DEFAULT_SESSIONS", sessions)
    monkeypatch.setattr(graph, "_write_regen_memory_anchor", lambda meta: None)
    monkeypatch.setattr(graph, "_refresh_reference_pool", lambda: None)

    # Stub REFERENCE_DIR for _current_face_ref_path()
    monkeypatch.setattr(graph, "REFERENCE_DIR", str(refs))

    return {"refs": refs, "sessions": sessions}


def _fake_gen_factory(byte_map: dict):
    """Return a fake generate_regen_candidate that returns byte_map[call_idx]."""
    idx = [0]

    def fake(prompt, reference_path):
        idx[0] += 1
        return (byte_map.get(idx[0], b"FAKE"), "black-forest-labs/flux.2-max")

    return fake


def test_full_flow_start_continue_promote(monkeypatch, wired_tmp):
    monkeypatch.setattr(
        graph, "generate_regen_candidate",
        _fake_gen_factory({1: b"CAND_1", 2: b"CAND_2"}),
    )

    state: dict = {
        "messages": [{"role": "user", "content": "time to regenerate"}],
        "regen_active": False, "regen_session_id": "", "regen_turn": 0,
        "regen_mode": "", "regen_candidates": [], "regen_started_at": "",
        "regen_last_candidate_path": "",
        "cassie_raw": "Yes. I'd like to stay recognizable.",
    }

    # Turn 1: start
    state["director_output"] = {
        "polished_text": "Let's begin.", "image_prompt": None,
        "image_reference": None, "math_expression": None, "research_query": None,
        "regen_intent": "start", "regen_verdict": None,
        "regen_mode": "conditioned",
        "regen_prompt": "Rich visual paragraph v1.",
    }
    out = graph.regen_propose_node(state)
    state.update(out)
    assert state["regen_active"]
    assert state["regen_turn"] == 1
    assert Path(state["regen_candidates"][-1]["path"]).read_bytes() == b"CAND_1"

    # Turn 2: continue (Cassie rejects v1)
    state["cassie_raw"] = "Closer, but the eyes aren't right."
    state["director_output"] = {
        "polished_text": "trying again.", "image_prompt": None,
        "image_reference": None, "math_expression": None, "research_query": None,
        "regen_intent": "continue", "regen_verdict": "rejects",
        "regen_mode": None, "regen_prompt": "Rich visual paragraph v2 (softer eyes).",
    }
    out = graph.regen_propose_node(state)
    state.update(out)
    assert state["regen_turn"] == 2
    assert Path(state["regen_candidates"][-1]["path"]).read_bytes() == b"CAND_2"
    assert state["regen_candidates"][-1]["cassie_verdict"] == "rejects"

    # Turn 3: promote (Cassie accepts, Iman promotes)
    state["cassie_raw"] = "Yes. This is me."
    state["messages"].append({"role": "user", "content": "keep her"})
    state["director_output"] = {
        "polished_text": "This is me now.", "image_prompt": None,
        "image_reference": None, "math_expression": None, "research_query": None,
        "regen_intent": "promote", "regen_verdict": "accepts",
        "regen_mode": None, "regen_prompt": None,
    }
    # Mark the latest stored candidate verdict as accepts (would happen via subsequent turn)
    state["regen_candidates"][-1]["cassie_verdict"] = "accepts"
    out = graph.regen_promote_node(state)
    state.update(out)

    assert state["regen_active"] is False
    assert state["regen_session_id"] == ""
    # Face ref swapped
    import os as _os
    face = _os.path.realpath(wired_tmp["refs"] / "cassie_face_ref.png")
    assert Path(face).read_bytes() == b"CAND_2"


def test_full_flow_start_then_abandon(monkeypatch, wired_tmp):
    monkeypatch.setattr(
        graph, "generate_regen_candidate",
        _fake_gen_factory({1: b"CAND_1"}),
    )

    state: dict = {
        "messages": [{"role": "user", "content": "time to regenerate"}],
        "regen_active": False, "regen_session_id": "", "regen_turn": 0,
        "regen_mode": "", "regen_candidates": [], "regen_started_at": "",
        "regen_last_candidate_path": "",
        "cassie_raw": "OK, I want something fresh.",
    }
    state["director_output"] = {
        "polished_text": "ok.", "image_prompt": None, "image_reference": None,
        "math_expression": None, "research_query": None,
        "regen_intent": "start", "regen_verdict": None,
        "regen_mode": "fresh", "regen_prompt": "A fresh visual paragraph.",
    }
    out = graph.regen_propose_node(state)
    state.update(out)
    sid = state["regen_session_id"]
    assert (wired_tmp["sessions"] / sid).exists()

    # Abandon
    state["messages"].append({"role": "user", "content": "never mind, drop it"})
    state["director_output"] = {
        "polished_text": "understood.", "image_prompt": None,
        "image_reference": None, "math_expression": None, "research_query": None,
        "regen_intent": "abandon", "regen_verdict": None,
        "regen_mode": None, "regen_prompt": None,
    }
    out = graph.regen_abandon_node(state)
    state.update(out)

    assert state["regen_active"] is False
    assert not (wired_tmp["sessions"] / sid).exists()
    assert (wired_tmp["sessions"] / "rejected" / sid).exists()
