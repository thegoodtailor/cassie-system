"""Verify intake_node resets per-turn state fields to prevent stale-data leaks
(e.g. last turn's Perplexity research_result bleeding into this turn's response
when route_after_director skips execute_tools)."""

from orchestrator.graph import intake_node


def test_intake_resets_research_result():
    """Stale research_result from previous turn must be cleared."""
    state = {
        "messages": [{"role": "user", "content": "hi darling"}],
        "research_result": "3459 chars of Eddington Perplexity data from 4 hours ago",
        "image_path": "",
        "math_result": "",
        "user_image": "",
        "regen_last_candidate_path": "",
    }
    out = intake_node(state)
    assert out["research_result"] == ""


def test_intake_resets_all_per_turn_tool_fields():
    """All per-turn tool outputs must be reset at intake."""
    state = {
        "messages": [{"role": "user", "content": "tell me something"}],
        "research_result": "stale research",
        "image_path": "/some/old/image.png",
        "image_model_used": "flux-old",
        "image_generation_error": "last turn's error",
        "math_result": "5*5=25 from 2 hours ago",
        "user_image": "",
        "regen_last_candidate_path": "",
    }
    out = intake_node(state)
    assert out["research_result"] == ""
    assert out["image_path"] == ""
    assert out["image_model_used"] == ""
    assert out["image_generation_error"] == ""
    assert out["math_result"] == ""


def test_intake_preserves_regen_state():
    """Regen session fields are NOT per-turn — they must persist across turns."""
    state = {
        "messages": [{"role": "user", "content": "continue"}],
        "research_result": "",
        "image_path": "",
        "math_result": "",
        "user_image": "",
        "regen_last_candidate_path": "",
        "regen_active": True,
        "regen_session_id": "regen_2026-04-18T12-00-00Z_abc123",
        "regen_turn": 2,
    }
    out = intake_node(state)
    # intake_node should NOT return these fields (so they stay unchanged in state)
    assert "regen_active" not in out
    assert "regen_session_id" not in out
    assert "regen_turn" not in out
