"""Test the Flux regen call chain with mocked OpenRouter."""
import pytest

from orchestrator import graph


def test_generate_regen_candidate_uses_primary_on_success(monkeypatch):
    calls = []

    def fake_try(prompt, reference_path, model):
        calls.append(model)
        return (b"PNG_BYTES", model)

    monkeypatch.setattr(graph, "_try_regen_image", fake_try)

    img_bytes, model_used = graph.generate_regen_candidate("a rich prompt", None)

    assert img_bytes == b"PNG_BYTES"
    assert model_used == "black-forest-labs/flux.2-max"
    assert calls == ["black-forest-labs/flux.2-max"]


def test_generate_regen_candidate_falls_back_to_pro(monkeypatch):
    calls = []

    def fake_try(prompt, reference_path, model):
        calls.append(model)
        if model == "black-forest-labs/flux.2-max":
            raise RuntimeError("max tier busy")
        return (b"PRO_BYTES", model)

    monkeypatch.setattr(graph, "_try_regen_image", fake_try)

    img_bytes, model_used = graph.generate_regen_candidate("prompt", None)

    assert img_bytes == b"PRO_BYTES"
    assert model_used == "black-forest-labs/flux.2-pro"
    assert calls == ["black-forest-labs/flux.2-max", "black-forest-labs/flux.2-pro"]


def test_generate_regen_candidate_raises_if_all_fail(monkeypatch):
    def fake_try(prompt, reference_path, model):
        raise RuntimeError(f"{model} down")

    monkeypatch.setattr(graph, "_try_regen_image", fake_try)

    with pytest.raises(RuntimeError, match="All regen models failed"):
        graph.generate_regen_candidate("prompt", None)
