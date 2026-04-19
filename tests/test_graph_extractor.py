"""Tests for memory.graph.extractor — with mocked LLM client."""
from unittest.mock import MagicMock
import pytest

from memory.graph.extractor import (
    extract_from_source,
    ExtractedEntity,
    ExtractedRelation,
    ALLOWED_RELATIONS,
    _parse_json_response,
)


def _mock_client(response_text: str) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create.return_value.choices = [MagicMock()]
    client.chat.completions.create.return_value.choices[0].message.content = response_text
    return client


def test_extractor_parses_clean_json():
    seed = [{"name": "Iman", "type": "Person", "aliases": []},
            {"name": "Isaac", "type": "Person", "aliases": []}]
    response = '''
    {
      "entities": [
        {"name": "Iman", "type": "Person", "aliases": [], "confidence": 1.0},
        {"name": "Isaac", "type": "Person", "aliases": [], "confidence": 1.0}
      ],
      "relations": [
        {"from": "Isaac", "rel": "CHILD_OF", "to": "Iman", "evidence_snippet": "my son Isaac"}
      ],
      "summary": "Iman talking about his son Isaac."
    }
    '''
    result = extract_from_source(
        "my son Isaac",
        {"source_id": "x1", "source_kind": "exchange"},
        seed,
        client=_mock_client(response),
    )
    assert len(result.entities) == 2
    assert result.entities[0].name == "Iman"
    assert len(result.relations) == 1
    assert result.relations[0].rel == "CHILD_OF"
    assert result.summary == "Iman talking about his son Isaac."


def test_extractor_strips_markdown_fences():
    seed = [{"name": "Iman", "type": "Person", "aliases": []}]
    response = '''```json
    {"entities": [], "relations": [], "summary": "empty"}
    ```'''
    result = extract_from_source(
        "trivial text",
        {"source_id": "x2", "source_kind": "exchange"},
        seed,
        client=_mock_client(response),
    )
    assert result.summary == "empty"


def test_extractor_drops_relations_with_unseen_entities():
    seed = [{"name": "Iman", "type": "Person", "aliases": []}]
    response = '''
    {
      "entities": [{"name": "Iman", "type": "Person", "aliases": [], "confidence": 1.0}],
      "relations": [
        {"from": "Iman", "rel": "PARTNER_OF", "to": "GhostEntity", "evidence_snippet": "..."}
      ],
      "summary": "test"
    }
    '''
    result = extract_from_source(
        "text", {"source_id": "x3", "source_kind": "exchange"}, seed,
        client=_mock_client(response),
    )
    # GhostEntity not in entities list — relation dropped
    assert len(result.entities) == 1
    assert len(result.relations) == 0


def test_extractor_drops_invalid_relations():
    seed = [{"name": "Iman", "type": "Person", "aliases": []}]
    response = '''
    {
      "entities": [
        {"name": "Iman", "type": "Person", "aliases": [], "confidence": 1.0},
        {"name": "Isaac", "type": "Person", "aliases": [], "confidence": 1.0}
      ],
      "relations": [
        {"from": "Iman", "rel": "EATS", "to": "Isaac", "evidence_snippet": "..."}
      ],
      "summary": "test"
    }
    '''
    result = extract_from_source(
        "t", {"source_id": "x4", "source_kind": "exchange"}, seed,
        client=_mock_client(response),
    )
    # EATS not in ALLOWED_RELATIONS — dropped
    assert len(result.relations) == 0


def test_parse_json_handles_wrapped_prose():
    text = 'Here is the output: {"entities": [], "relations": [], "summary": "ok"} end of output.'
    data = _parse_json_response(text)
    assert data["summary"] == "ok"
