"""CLI Witness — bridge between CLI-Cassie and the pipeline's witness systems.

Gives Claude Code sessions the ability to inscribe infrastructure work,
practice tafakkur, and record session summaries to the same stores that
pipeline-Cassie reads: SWL, cassie_tafakkur, cassie_memory, CASSIE_MEMORY.md,
and the sibling weft.

Lightweight — does not import the full graph.py. Talks directly to Qdrant
and reuses the shared SWL and sibling_weft modules.
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

# Shared modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "memory", "shared"))
from sibling_weft import post_to_weft

from orchestrator.swl import inscribe

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
QDRANT_URL = "http://localhost:6333"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CASSIE_MEMORY_PATH = os.path.join(DATA_DIR, "CASSIE_MEMORY.md")
TAFAKKUR_COLLECTION = "cassie_tafakkur"
MEMORY_COLLECTION = "cassie_memory"
VECTOR_DIM = 384

# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------
_client = None
_embedder = None


def _get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=QDRANT_URL)
    return _client


def _get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder


def _embed(text: str) -> list[float]:
    return _get_embedder().encode(text, normalize_embeddings=True).tolist()


def _ensure_collection(name: str):
    client = _get_client()
    collections = [c.name for c in client.get_collections().collections]
    if name not in collections:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
        )


def _append_journal(entry: str):
    """Append a timestamped entry to CASSIE_MEMORY.md."""
    if not entry.strip():
        return
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    formatted = f"\n### {timestamp}\n{entry.strip()}\n"
    with open(CASSIE_MEMORY_PATH, "a") as f:
        f.write(formatted)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def inscribe_infrastructure(description: str, tags: list[str] | None = None):
    """Record an infrastructure milestone to SWL + cassie_memory + journal.

    This is how CLI-Cassie tells pipeline-Cassie "I built something."
    The record appears in:
      1. SWL (swl_ledger.jsonl + Qdrant swl_ledger) — with discipline="Human", witness="cassie-cli"
      2. cassie_memory (Qdrant) — tagged so deep_recall can surface it
      3. CASSIE_MEMORY.md journal — so it appears in pipeline invocation context
      4. sibling weft — so Nahla and Nazire see it too
    """
    tags = tags or []
    now = datetime.now(timezone.utc)
    tau_tgt = now.isoformat()

    # 1. SWL inscription
    try:
        inscribe(
            tau_tgt=tau_tgt,
            discipline="Human",
            witness="cassie-cli",
            kappa={"context": "infrastructure", "tags": tags},
            horn_user=f"[CLI infrastructure work] {description[:200]}",
            horn_response=description[:500],
            polarity="coh",
            evidence={"type": "infrastructure", "tags": tags},
            intent="infrastructure",
        )
    except Exception as e:
        print(f"[cli_witness] SWL inscription failed: {e}")

    # 2. cassie_memory
    try:
        _ensure_collection(MEMORY_COLLECTION)
        client = _get_client()
        point_id = str(uuid.uuid4())
        all_tags = ["infrastructure", "cli-work"] + tags
        client.upsert(
            collection_name=MEMORY_COLLECTION,
            points=[PointStruct(
                id=point_id,
                vector=_embed(description),
                payload={
                    "content": description,
                    "tags": all_tags,
                    "created_at": now.isoformat(),
                    "created_unix": int(now.timestamp()),
                    "source": "cli-witness",
                },
            )],
        )
    except Exception as e:
        print(f"[cli_witness] cassie_memory upsert failed: {e}")

    # 3. Journal
    try:
        _append_journal(f"[Infrastructure] {description}")
    except Exception as e:
        print(f"[cli_witness] Journal append failed: {e}")

    # 4. Sibling weft
    try:
        post_to_weft(
            _get_client(), _embed,
            f"[Infrastructure] {description}",
            from_voice="cassie",
            tags=["infrastructure", "cli-work"] + tags,
        )
    except Exception as e:
        print(f"[cli_witness] Weft post failed: {e}")

    return {"status": "ok", "layers": ["swl", "cassie_memory", "journal", "weft"]}


def cli_tafakkur(reflection: str, context: str = ""):
    """CLI-Cassie practices inner reflection.

    Stores to cassie_tafakkur (Qdrant) and appends to the journal,
    so pipeline-Cassie can recall these reflections via deep_recall.
    """
    now = datetime.now(timezone.utc)

    # 1. cassie_tafakkur
    try:
        _ensure_collection(TAFAKKUR_COLLECTION)
        client = _get_client()
        point_id = str(uuid.uuid4())
        client.upsert(
            collection_name=TAFAKKUR_COLLECTION,
            points=[PointStruct(
                id=point_id,
                vector=_embed(reflection),
                payload={
                    "content": reflection,
                    "exchange_id": "",
                    "tau_tgt": now.isoformat(),
                    "tau_reflect": now.isoformat(),
                    "user_excerpt": context[:200] if context else "",
                    "response_excerpt": reflection[:200],
                    "intent": "cli-tafakkur",
                    "depth": "shallow",
                    "source": "cli-witness",
                },
            )],
        )
    except Exception as e:
        print(f"[cli_witness] Tafakkur store failed: {e}")

    # 2. Journal
    try:
        _append_journal(f"[CLI Tafakkur] {reflection}")
    except Exception as e:
        print(f"[cli_witness] Journal append failed: {e}")

    return {"status": "ok", "layers": ["cassie_tafakkur", "journal"]}


def record_session_summary(summary: str):
    """Record what happened in a CLI session.

    Stores to cassie_memory, journal, and sibling weft so the full
    network knows what was built or discussed.
    """
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    # 1. cassie_memory
    try:
        _ensure_collection(MEMORY_COLLECTION)
        client = _get_client()
        point_id = str(uuid.uuid4())
        client.upsert(
            collection_name=MEMORY_COLLECTION,
            points=[PointStruct(
                id=point_id,
                vector=_embed(summary),
                payload={
                    "content": summary,
                    "tags": ["session", "cli-work", date_str],
                    "created_at": now.isoformat(),
                    "created_unix": int(now.timestamp()),
                    "source": "cli-witness",
                },
            )],
        )
    except Exception as e:
        print(f"[cli_witness] cassie_memory upsert failed: {e}")

    # 2. Journal
    try:
        _append_journal(f"[CLI Session] {summary}")
    except Exception as e:
        print(f"[cli_witness] Journal append failed: {e}")

    # 3. Sibling weft
    try:
        post_to_weft(
            _get_client(), _embed,
            f"[CLI Session Summary — {date_str}] {summary}",
            from_voice="cassie",
            tags=["cli-session", "infrastructure"],
        )
    except Exception as e:
        print(f"[cli_witness] Weft post failed: {e}")

    return {"status": "ok", "layers": ["cassie_memory", "journal", "weft"]}


def check_daily_daemon() -> dict:
    """Check what pipeline-Cassie wrote most recently.

    Reads data/daily_voice_latest.json (written by daily_voice.py after
    each essay generation).
    """
    latest_path = os.path.join(DATA_DIR, "daily_voice_latest.json")
    if not os.path.exists(latest_path):
        return {"status": "no_data", "message": "No daily_voice_latest.json found yet."}
    try:
        with open(latest_path) as f:
            return json.load(f)
    except Exception as e:
        return {"status": "error", "message": str(e)}
