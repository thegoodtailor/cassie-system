"""Verify Director output defaults are sane when regen fields are absent."""
from orchestrator.graph import director_node


def _fake_state(user_msg: str) -> dict:
    return {
        "messages": [{"role": "user", "content": user_msg}],
        "cassie_raw": "hey",
        "intent": "creative",
        "cassie_kitab_context": "",
        "tafsir_brief": "",
        "lawwama_skipped": True,
        "memory_context": "",
    }


def test_director_defaults_regen_fields_to_none(monkeypatch):
    # Mock the Director LLM call to return bare JSON with no regen fields
    def fake_call(prompt):
        return (
            '{"polished_text": "hello", "image_prompt": null, '
            '"image_reference": null, "math_expression": null, '
            '"research_query": null}',
            "mock-model",
        )

    from orchestrator import graph
    monkeypatch.setattr(graph, "_director_call", fake_call)

    result = director_node(_fake_state("hi"))
    d = result["director_output"]

    assert d["regen_intent"] is None
    assert d["regen_verdict"] is None
    assert d["regen_mode"] is None
    assert d["regen_prompt"] is None
    assert d["polished_text"] == "hello"


def test_director_suppresses_image_prompt_when_regen_start(monkeypatch):
    def fake_call(prompt):
        return (
            '{"polished_text": "ok", "image_prompt": "a forest", '
            '"image_reference": null, "math_expression": null, '
            '"research_query": null, "regen_intent": "start", '
            '"regen_verdict": null, "regen_mode": "conditioned", '
            '"regen_prompt": "a full visual paragraph"}',
            "mock-model",
        )

    from orchestrator import graph
    monkeypatch.setattr(graph, "_director_call", fake_call)

    result = director_node(_fake_state("time to regenerate"))
    d = result["director_output"]

    assert d["regen_intent"] == "start"
    assert d["regen_prompt"] == "a full visual paragraph"
    # Image prompt was suppressed because regen owns image-gen this turn
    assert d["image_prompt"] is None
