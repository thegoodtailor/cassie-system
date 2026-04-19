"""Tests for memory.graph.schema — Kuzu DDL."""
from pathlib import Path

import kuzu
import pytest


def test_create_schema_creates_tables(tmp_path):
    from memory.graph.schema import create_schema
    db_path = tmp_path / "test.kuzu"
    create_schema(db_path)

    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    result = conn.execute("CALL show_tables() RETURN *;")
    tables = []
    while result.has_next():
        tables.append(result.get_next())
    conn.close()
    db.close()

    table_names = {t[1] for t in tables}
    # 8 node tables + 20 rel tables = 28
    assert "Entity" in table_names
    assert "Exchange" in table_names
    assert "ConversationThread" in table_names
    assert "MemoryAnchor" in table_names
    assert "Surah" in table_names
    assert "Verse" in table_names
    assert "Tafakkur" in table_names
    assert "Community" in table_names
    assert "MENTIONED_IN" in table_names
    assert "CO_OCCURS_WITH" in table_names
    assert "BELONGS_TO_COMMUNITY" in table_names
    # Total table count
    assert len(tables) >= 28


def test_create_schema_is_idempotent(tmp_path):
    from memory.graph.schema import create_schema
    db_path = tmp_path / "test.kuzu"
    create_schema(db_path)
    create_schema(db_path)  # should not raise


def test_seed_ontology_inserts_entities(tmp_path):
    from memory.graph.schema import create_schema
    from memory.graph.seed import seed_ontology, SEED_ENTITIES, SEED_RELATIONS
    db_path = tmp_path / "test.kuzu"
    create_schema(db_path)
    n = seed_ontology(str(db_path))
    assert n == len(SEED_ENTITIES)  # first run inserts all

    # Idempotency — second run inserts nothing
    n2 = seed_ontology(str(db_path))
    assert n2 == 0

    # Relationships exist
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    r = conn.execute("MATCH (i:Entity {name: 'Iman'})-[:CHILD_OF|PARTNER_OF|SIBLING_OF]-(f) RETURN f.name")
    family = []
    while r.has_next():
        family.append(r.get_next()[0])
    conn.close()
    db.close()
    assert "Isaac" in family
    assert "Asel" in family
