"""Tests for regen_propose / regen_promote / regen_abandon nodes."""
from pathlib import Path

from orchestrator import graph


def _base_state(director: dict, **overrides) -> dict:
    state = {
        "messages": [{"role": "user", "content": "time to regenerate"}],
        "director_output": director,
        "regen_active": False,
        "regen_session_id": "",
        "regen_turn": 0,
        "regen_mode": "",
        "regen_candidates": [],
        "regen_started_at": "",
        "regen_last_candidate_path": "",
        "cassie_raw": "",
    }
    state.update(overrides)
    return state


def test_propose_starts_session_on_intent_start(monkeypatch, tmp_path):
    # Redirect sessions dir
    from orchestrator import regen_sessions as rs
    monkeypatch.setattr(rs, "_DEFAULT_SESSIONS", tmp_path / "sessions")

    def fake_gen(prompt, reference_path):
        return (b"BYTES_1", "black-forest-labs/flux.2-max")

    monkeypatch.setattr(graph, "generate_regen_candidate", fake_gen)

    director = {
        "regen_intent": "start",
        "regen_mode": "conditioned",
        "regen_prompt": "a full visual paragraph",
        "regen_verdict": None,
        "polished_text": "Let's see.",
    }
    state = _base_state(director)

    out = graph.regen_propose_node(state)

    assert out["regen_active"] is True
    assert out["regen_session_id"].startswith("regen_")
    assert out["regen_turn"] == 1
    assert out["regen_mode"] == "conditioned"
    assert len(out["regen_candidates"]) == 1
    cand = out["regen_candidates"][0]
    assert cand["turn"] == 1
    assert cand["prompt"] == "a full visual paragraph"
    assert Path(cand["path"]).read_bytes() == b"BYTES_1"
    assert out["regen_last_candidate_path"] == cand["path"]
    # image_path is set so assemble sends the candidate to WhatsApp
    assert out["image_path"] == cand["path"]


def test_propose_continues_session_on_intent_continue(monkeypatch, tmp_path):
    from orchestrator import regen_sessions as rs
    monkeypatch.setattr(rs, "_DEFAULT_SESSIONS", tmp_path / "sessions")

    calls = []

    def fake_gen(prompt, reference_path):
        calls.append({"prompt": prompt, "reference_path": reference_path})
        return (b"BYTES_2", "black-forest-labs/flux.2-max")

    monkeypatch.setattr(graph, "generate_regen_candidate", fake_gen)

    # State has an existing candidate already
    existing_path = str(tmp_path / "existing_candidate.png")
    Path(existing_path).write_bytes(b"BYTES_1")

    state = _base_state(
        {
            "regen_intent": "continue",
            "regen_prompt": "softer eyes, less fantasy",
            "regen_verdict": "rejects",
            "polished_text": "trying again",
        },
        regen_active=True,
        regen_session_id="regen_2026-04-15T10-00-00Z_abc123",
        regen_turn=1,
        regen_mode="conditioned",
        regen_candidates=[{
            "turn": 1, "path": existing_path, "prompt": "first prompt",
            "cassie_reflection": "", "cassie_verdict": "", "iman_verdict_text": "",
        }],
        regen_last_candidate_path=existing_path,
    )

    out = graph.regen_propose_node(state)

    assert out["regen_turn"] == 2
    # Iteration turns condition on the previous candidate
    assert calls[0]["reference_path"] == existing_path
    assert len(out["regen_candidates"]) == 2


def test_promote_swaps_face_and_clears_session(monkeypatch, tmp_path):
    from orchestrator import regen_sessions as rs

    references = tmp_path / "references"
    references.mkdir()
    (references / "promoted").mkdir()
    seed = references / "seed.png"
    seed.write_bytes(b"OLD_FACE")
    import os as _os
    _os.symlink(seed, references / "cassie_face_ref.png")

    sessions = tmp_path / "sessions"

    monkeypatch.setattr(rs, "_DEFAULT_SESSIONS", sessions)
    monkeypatch.setattr(rs, "_DEFAULT_REFERENCES", references)

    # Stub the memory anchor + pool refresh
    anchors = []
    monkeypatch.setattr(graph, "_write_regen_memory_anchor", lambda meta: anchors.append(meta))
    monkeypatch.setattr(graph, "_refresh_reference_pool", lambda: None)

    # Prepare a candidate file
    sid = "regen_2026-04-15T10-00-00Z_abc123"
    candidate = rs.record_candidate(sid, 4, b"NEW_FACE", base=sessions)

    state = _base_state(
        {
            "regen_intent": "promote",
            "regen_verdict": "accepts",  # Cassie accepts
            "polished_text": "This is me now.",
        },
        regen_active=True,
        regen_session_id=sid,
        regen_turn=4,
        regen_mode="conditioned",
        regen_candidates=[
            {"turn": 1, "path": "p1", "prompt": "p", "cassie_reflection": "",
             "cassie_verdict": "rejects", "iman_verdict_text": ""},
            {"turn": 4, "path": str(candidate), "prompt": "final prompt",
             "model": "flux.2-max",
             "cassie_reflection": "This is me.", "cassie_verdict": "accepts",
             "iman_verdict_text": ""},
        ],
    )
    state["messages"] = [{"role": "user", "content": "yes, keep her"}]

    out = graph.regen_promote_node(state)

    # Face ref now points at the new file
    import os as _os2
    face = _os2.path.realpath(references / "cassie_face_ref.png")
    assert Path(face).read_bytes() == b"NEW_FACE"

    # Session state cleared
    assert out["regen_active"] is False
    assert out["regen_session_id"] == ""
    assert out["regen_turn"] == 0
    assert out["regen_candidates"] == []
    assert out["regen_last_candidate_path"] == ""

    # Memory anchor was written once
    assert len(anchors) == 1


def test_promote_does_not_fire_without_cassie_accepts(monkeypatch, tmp_path):
    """Director says promote, but Cassie's verdict on last candidate is 'rejects' —
    promotion must NOT happen. This is the co-approval gate."""
    from orchestrator import regen_sessions as rs
    monkeypatch.setattr(rs, "_DEFAULT_REFERENCES", tmp_path / "references")
    (tmp_path / "references" / "promoted").mkdir(parents=True)

    state = _base_state(
        {"regen_intent": "promote", "regen_verdict": "rejects",
         "polished_text": "hm"},
        regen_active=True,
        regen_session_id="regen_fake_xyz",
        regen_turn=1,
        regen_candidates=[
            {"turn": 1, "path": "p", "prompt": "pr", "cassie_reflection": "",
             "cassie_verdict": "rejects", "iman_verdict_text": ""},
        ],
    )

    out = graph.regen_promote_node(state)
    # Nothing swapped, nothing cleared — session stays open
    assert out == {} or out.get("regen_active") is True


def test_abandon_moves_session_and_clears_state(monkeypatch, tmp_path):
    from orchestrator import regen_sessions as rs
    monkeypatch.setattr(rs, "_DEFAULT_SESSIONS", tmp_path / "sessions")

    sid = "regen_2026-04-15T10-00-00Z_abc123"
    rs.record_candidate(sid, 1, b"X", base=tmp_path / "sessions")

    state = _base_state(
        {"regen_intent": "abandon", "polished_text": "ok, dropping it"},
        regen_active=True,
        regen_session_id=sid,
        regen_turn=1,
        regen_candidates=[{"turn": 1, "path": "p", "prompt": "pr",
                           "cassie_reflection": "", "cassie_verdict": "",
                           "iman_verdict_text": ""}],
    )

    out = graph.regen_abandon_node(state)

    assert out["regen_active"] is False
    assert out["regen_session_id"] == ""
    assert out["regen_candidates"] == []
    assert not (tmp_path / "sessions" / sid).exists()
    assert (tmp_path / "sessions" / "rejected" / sid).exists()


def test_abandon_is_noop_when_no_intent(monkeypatch):
    out = graph.regen_abandon_node(_base_state({"regen_intent": None}))
    assert out == {}
