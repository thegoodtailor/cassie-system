"""Tests for graph_recall_node in orchestrator/graph.py."""
from unittest.mock import patch

import pytest

from orchestrator.graph import graph_recall_node, PIPELINE_CONFIG


def _state(user_msg: str) -> dict:
    return {
        "messages": [{"role": "user", "content": user_msg}],
    }


def test_graph_recall_node_returns_empty_when_flag_off(monkeypatch):
    monkeypatch.setitem(PIPELINE_CONFIG, "graph_recall_enabled", False)
    out = graph_recall_node(_state("what about Romain?"))
    assert out == {}


def test_graph_recall_node_returns_empty_on_blank_message(monkeypatch):
    monkeypatch.setitem(PIPELINE_CONFIG, "graph_recall_enabled", True)
    out = graph_recall_node({"messages": [{"role": "user", "content": ""}]})
    # Either returns {} for blank message or falls through to missing-DB no-op
    assert out == {} or out.get("graph_context", "") == ""


def test_graph_recall_node_calls_graph_brief_when_flag_on(monkeypatch):
    monkeypatch.setitem(PIPELINE_CONFIG, "graph_recall_enabled", True)
    calls = []

    def fake_brief(query, **kwargs):
        calls.append(query)
        return {"mode": "local", "entities": [], "communities": [], "drill_downs": [],
                "serialized": "MOCK BRIEF"}

    with patch("memory.graph.query.graph_brief", fake_brief):
        out = graph_recall_node(_state("tell me about Iman"))

    assert calls == ["tell me about Iman"]
    assert out.get("graph_context") == "MOCK BRIEF"


def test_graph_recall_node_survives_exceptions(monkeypatch):
    monkeypatch.setitem(PIPELINE_CONFIG, "graph_recall_enabled", True)

    def fake_brief(query, **kwargs):
        raise RuntimeError("simulated failure")

    with patch("memory.graph.query.graph_brief", fake_brief):
        out = graph_recall_node(_state("hello"))

    # Must not propagate — returns empty dict, doesn't crash pipeline
    assert out == {}
