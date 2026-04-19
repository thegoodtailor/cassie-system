"""Tests for memory.graph.query — end-to-end with synthetic graph."""
from pathlib import Path

import pytest

from memory.graph.schema import create_schema
from memory.graph.seed import seed_ontology
from memory.graph.client import GraphClient
from memory.graph.query import graph_brief, _seeded_name_hits, _decide_mode


def test_seeded_name_hits_detects_canonical():
    hits = _seeded_name_hits("tell me about Isaac and the trains")
    assert "Isaac" in hits


def test_seeded_name_hits_detects_aliases():
    hits = _seeded_name_hits("how's Monya doing?")  # Monya is Iman's alias
    assert "Iman" in hits


def test_seeded_name_hits_handles_multi_word():
    hits = _seeded_name_hits("we were working on rupture and return")
    assert "Rupture and Return" in hits


def test_decide_mode_local_when_entity_hit():
    assert _decide_mode("tell me about Isaac", ["Isaac"]) == "local"


def test_decide_mode_global_when_temporal():
    assert _decide_mode("what were we doing in October 2025?", []) == "global"


def test_decide_mode_hybrid_default():
    assert _decide_mode("tell me a story", []) == "hybrid"


def test_graph_brief_returns_empty_when_db_missing(tmp_path):
    brief = graph_brief("test query", db_path=tmp_path / "nonexistent.kuzu")
    assert brief["mode"] == "none"
    assert brief["entities"] == []
    assert brief["serialized"] == ""


def test_graph_brief_local_mode_with_seeded_data(tmp_path):
    db_path = tmp_path / "test.kuzu"
    create_schema(db_path)
    seed_ontology(str(db_path))

    # Add a synthetic Exchange linked to Romain
    with GraphClient(db_path=db_path, write=True) as gc:
        gc.execute('''
            CREATE (:Exchange {
                exchange_id: 'ex_r1', thread_id: 't1', timestamp: '2025-06-15',
                date_unix: 1750000000, user_message: 'Should I fire Romain?',
                cassie_response: 'Yes.', intent: 'creative', model: 'claude'
            })
        ''')
        gc.execute('''
            MATCH (e:Entity {name: 'Romain'}), (x:Exchange {exchange_id: 'ex_r1'})
            CREATE (e)-[:MENTIONED_IN {evidence_snippet: 'Should I fire Romain?', weight: 1.0, created_at_unix: 12345}]->(x)
        ''')

    brief = graph_brief("what happened with Romain?", db_path=db_path)
    assert brief["mode"] == "local"
    entity_names = [e["name"] for e in brief["entities"]]
    assert "Romain" in entity_names
    assert "Romain" in brief["serialized"]
    assert "2025-06-15" in brief["serialized"]
    assert len(brief["drill_downs"]) >= 1


def test_graph_brief_serialization_under_cap(tmp_path):
    db_path = tmp_path / "test.kuzu"
    create_schema(db_path)
    seed_ontology(str(db_path))
    brief = graph_brief("what about Iman and Isaac", db_path=db_path)
    # Brief should always be under the hard cap
    assert len(brief["serialized"]) < 5000
