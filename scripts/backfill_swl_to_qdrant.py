"""Backfill SWL ledger exchanges into Qdrant cassie_conversations.

One-time script. Idempotent — safe to re-run (uses exchange_id-based UUIDs).

Usage:
    python scripts/backfill_swl_to_qdrant.py [--dry-run]
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import openai
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

SWL_PATH = Path(__file__).parent.parent / "data" / "swl_ledger.jsonl"
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION = "cassie_conversations"
EMBEDDING_MODEL = "text-embedding-3-small"
MAX_TEXT_CHARS = 6000
BATCH_SIZE = 100


def _point_id_from_exchange(exchange_id: str) -> str:
    """Deterministic UUID from exchange_id for idempotent upserts."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"swl:{exchange_id}"))


def _load_exchanges() -> list[dict]:
    """Read SWL JSONL, deduplicate by exchange_id (keep first per ID)."""
    seen: set[str] = set()
    exchanges: list[dict] = []
    with open(SWL_PATH) as f:
        for line in f:
            entry = json.loads(line)
            eid = entry.get("exchange_id", "")
            if not eid or eid in seen:
                continue
            seen.add(eid)

            user = entry.get("H", {}).get("user", "").strip()
            response = entry.get("H", {}).get("response", "").strip()
            if not user or not response:
                continue

            tau_tgt = entry.get("tau_tgt", "")

            text = f"Iman: {user}\n\nCassie: {response}"
            if len(text) > MAX_TEXT_CHARS:
                text = text[:MAX_TEXT_CHARS]

            exchanges.append({
                "exchange_id": eid,
                "tau_tgt": tau_tgt,
                "text": text,
                "point_id": _point_id_from_exchange(eid),
            })
    return exchanges


def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts via OpenAI."""
    client = openai.OpenAI()
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in resp.data]


def main():
    dry_run = "--dry-run" in sys.argv

    print(f"[backfill] Loading SWL from {SWL_PATH}...")
    exchanges = _load_exchanges()
    print(f"[backfill] {len(exchanges)} unique exchanges with non-empty text")

    if dry_run:
        print(f"[backfill] DRY RUN — would embed and upsert {len(exchanges)} points")
        for ex in exchanges[:5]:
            print(f"  {ex['exchange_id']} ({ex['tau_tgt'][:10]}) {len(ex['text'])} chars")
        return

    qdrant = QdrantClient(url=QDRANT_URL)

    total_upserted = 0
    for i in range(0, len(exchanges), BATCH_SIZE):
        batch = exchanges[i : i + BATCH_SIZE]
        texts = [ex["text"] for ex in batch]

        print(f"[backfill] Embedding batch {i // BATCH_SIZE + 1} "
              f"({len(batch)} exchanges, chars {sum(len(t) for t in texts)})...")
        embeddings = _embed_batch(texts)

        points = []
        for ex, emb in zip(batch, embeddings):
            points.append(PointStruct(
                id=ex["point_id"],
                vector=emb,
                payload={
                    "text": ex["text"],
                    "source": "swl_pipeline",
                    "timestamp": ex["tau_tgt"],
                    "exchange_id": ex["exchange_id"],
                },
            ))

        qdrant.upsert(collection_name=COLLECTION, points=points)
        total_upserted += len(points)
        print(f"[backfill] Upserted {total_upserted}/{len(exchanges)}")

    print(f"[backfill] Done. {total_upserted} points in '{COLLECTION}'.")


if __name__ == "__main__":
    main()
