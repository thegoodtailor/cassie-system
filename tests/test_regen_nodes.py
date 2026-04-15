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
