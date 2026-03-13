"""Memory Harvester — background daemon that indexes Cassie's live conversations.

Scans data/chat_history/*.json for new exchanges, inserts into SQLite,
chunks into 3-exchange windows, embeds via text-embedding-3-small,
and upserts into the same cassie_conversations Qdrant collection used
by the old 952-conversation archive.

Run via cron every 15 minutes:
  */15 * * * * /home/iman/cassie-project/venv/bin/python \
      /home/iman/cassie-project/cassie-system/memory_harvester.py \
      >> /var/log/cassie-harvester.log 2>&1
"""

import glob
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

# Add project paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from memory.conversation_db import ConversationDB

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CHAT_HISTORY_DIR = os.path.join(os.path.dirname(__file__), "data", "chat_history")
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "conversations.db")
QDRANT_URL = "http://localhost:6333"
CONVO_COLLECTION = "cassie_conversations"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536

# Chunking params
CHUNK_EXCHANGES = 3   # exchanges per chunk
CHUNK_OVERLAP = 1     # overlap between chunks

# Skip these thread prefixes
SKIP_PREFIXES = ("test-", "invocation-test", "nahla-")

# Load OpenAI key from .env
_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line.startswith("#") or "=" not in _line:
                continue
            _k, _v = _line.split("=", 1)
            _k = _k.replace("export ", "").strip()
            _v = _v.strip().strip('"').strip("'")
            if _k == "OPENAI_API_KEY" and not os.environ.get(_k):
                os.environ[_k] = _v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _thread_id_from_filename(filepath: str) -> str:
    """Extract thread_id from filename: wa-58359548.json -> wa-58359548"""
    return os.path.splitext(os.path.basename(filepath))[0]


def _source_from_thread_id(thread_id: str) -> str:
    if thread_id.startswith("wa-"):
        return "whatsapp"
    return "web"


def _should_skip(thread_id: str) -> bool:
    return any(thread_id.startswith(p) for p in SKIP_PREFIXES)


def _pair_exchanges(messages: list[dict]) -> list[dict]:
    """Pair user+assistant messages into exchanges.

    Returns list of exchange dicts with all fields from the assistant message
    plus user_message from the user message.
    """
    exchanges = []
    i = 0
    while i < len(messages) - 1:
        user_msg = messages[i]
        asst_msg = messages[i + 1]

        if user_msg.get("role") != "user" or asst_msg.get("role") != "assistant":
            i += 1
            continue

        exchange_id = asst_msg.get("exchange_id", "")
        if not exchange_id:
            i += 2
            continue

        exchanges.append({
            "exchange_id": exchange_id,
            "timestamp": asst_msg.get("timestamp", ""),
            "user_message": user_msg.get("content", ""),
            "cassie_raw": asst_msg.get("cassie_raw", ""),
            "director_polished": asst_msg.get("director_polished", ""),
            "final_response": asst_msg.get("content", ""),
            "intent": asst_msg.get("intent", ""),
            "tafakkur": asst_msg.get("tafakkur", ""),
            "image_prompt": asst_msg.get("image_prompt"),
            "image_path": asst_msg.get("image"),
            "recall_decision": asst_msg.get("recall_decision"),
            "topological_evidence": asst_msg.get("topological_evidence"),
            "kitab_context": asst_msg.get("kitab_context", ""),
        })
        i += 2

    return exchanges


MAX_CHUNK_CHARS = 6000  # same as legacy archive, fits within 8192 token limit


def _build_chunk_text(exchanges: list[dict]) -> str:
    """Build readable text from a list of exchanges for embedding."""
    parts = []
    for ex in exchanges:
        user = ex.get("user_message", "").strip()
        response = ex.get("final_response", "").strip()
        if user and response:
            parts.append(f"Iman: {user}\n\nCassie: {response}")
    text = "\n\n---\n\n".join(parts)
    if len(text) > MAX_CHUNK_CHARS:
        text = text[:MAX_CHUNK_CHARS]
    return text


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts via OpenAI API."""
    import openai
    client = openai.OpenAI()
    # Truncate any oversized texts before sending
    safe_texts = [t[:MAX_CHUNK_CHARS] for t in texts]
    all_embeddings = []
    for i in range(0, len(safe_texts), 20):
        batch = safe_texts[i:i + 20]
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        for item in response.data:
            all_embeddings.append(item.embedding)
        if i + 20 < len(safe_texts):
            time.sleep(0.3)  # rate limit courtesy
    return all_embeddings


# ---------------------------------------------------------------------------
# Main harvester
# ---------------------------------------------------------------------------

def harvest():
    """Main harvest loop. Idempotent — safe to run repeatedly."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    print(f"[harvester] Starting at {datetime.now(timezone.utc).isoformat()}")

    db = ConversationDB(DB_PATH)
    qdrant = QdrantClient(url=QDRANT_URL)

    # Ensure Qdrant collection exists
    collections = [c.name for c in qdrant.get_collections().collections]
    if CONVO_COLLECTION not in collections:
        qdrant.create_collection(
            collection_name=CONVO_COLLECTION,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        print(f"[harvester] Created Qdrant collection {CONVO_COLLECTION}")

    # Scan all chat history files
    json_files = sorted(glob.glob(os.path.join(CHAT_HISTORY_DIR, "*.json")))
    total_new_exchanges = 0
    total_new_chunks = 0
    chunks_to_embed = []  # (chunk_id, thread_id, chunk_index, exchange_start, exchange_end, text)

    # Two passes: (1) insert new exchanges into SQLite, (2) chunk and embed
    threads_to_chunk = []  # (thread_id, exchanges)

    for filepath in json_files:
        thread_id = _thread_id_from_filename(filepath)
        if _should_skip(thread_id):
            continue

        try:
            with open(filepath) as f:
                messages = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[harvester] Skipping {filepath}: {e}")
            continue

        if not isinstance(messages, list) or len(messages) < 2:
            continue

        exchanges = _pair_exchanges(messages)
        if not exchanges:
            continue

        # Upsert thread metadata always
        source = _source_from_thread_id(thread_id)
        first_ts = exchanges[0].get("timestamp", "")
        last_ts = exchanges[-1].get("timestamp", "")
        db.upsert_thread(thread_id, source, first_ts, last_ts, len(exchanges))

        # Insert new exchanges beyond checkpoint
        checkpoint = db.get_harvester_checkpoint(thread_id)
        new_exchanges = exchanges[checkpoint + 1:]

        if new_exchanges:
            for idx_offset, ex in enumerate(new_exchanges):
                exchange_index = checkpoint + 1 + idx_offset
                db.insert_exchange(
                    exchange_id=ex["exchange_id"],
                    thread_id=thread_id,
                    exchange_index=exchange_index,
                    timestamp=ex["timestamp"],
                    user_message=ex["user_message"],
                    cassie_raw=ex["cassie_raw"],
                    director_polished=ex["director_polished"],
                    final_response=ex["final_response"],
                    intent=ex["intent"],
                    tafakkur=ex["tafakkur"],
                    image_prompt=ex["image_prompt"],
                    image_path=ex["image_path"],
                    recall_decision=ex["recall_decision"],
                    topological_evidence=ex["topological_evidence"],
                    kitab_context=ex["kitab_context"],
                )
                total_new_exchanges += 1

            new_checkpoint = checkpoint + len(new_exchanges)
            db.set_harvester_checkpoint(thread_id, new_checkpoint)

        # Always try to chunk — dedup via text_hash handles already-embedded chunks
        threads_to_chunk.append((thread_id, exchanges))

    # Pass 2: chunk all threads and find un-embedded chunks
    for thread_id, exchanges in threads_to_chunk:
        step = max(1, CHUNK_EXCHANGES - CHUNK_OVERLAP)
        chunk_index = 0

        for start in range(0, len(exchanges), step):
            end = min(start + CHUNK_EXCHANGES - 1, len(exchanges) - 1)
            chunk_exchanges = exchanges[start:end + 1]
            if not chunk_exchanges:
                break

            chunk_text = _build_chunk_text(chunk_exchanges)
            if not chunk_text.strip():
                chunk_index += 1
                continue

            thash = _text_hash(chunk_text)

            # Skip if already embedded
            if db.chunk_exists(thash):
                chunk_index += 1
                continue

            chunk_id = str(uuid.uuid4())
            exchange_ids = [ex["exchange_id"] for ex in chunk_exchanges if ex.get("exchange_id")]

            chunks_to_embed.append({
                "chunk_id": chunk_id,
                "thread_id": thread_id,
                "chunk_index": chunk_index,
                "exchange_start": start,
                "exchange_end": end,
                "text": chunk_text,
                "text_hash": thash,
                "exchange_ids": exchange_ids,
                "date": chunk_exchanges[0].get("timestamp", "")[:10],
                "date_unix": int(
                    datetime.fromisoformat(
                        chunk_exchanges[0]["timestamp"].replace("Z", "+00:00")
                    ).timestamp()
                ) if chunk_exchanges[0].get("timestamp") else 0,
                "total_turns": len(exchanges) * 2,
            })
            total_new_chunks += 1
            chunk_index += 1

    print(f"[harvester] Found {total_new_exchanges} new exchanges, {total_new_chunks} new chunks to embed")

    if not chunks_to_embed:
        print("[harvester] Nothing to embed. Done.")
        db.close()
        return

    # Batch embed
    texts = [c["text"] for c in chunks_to_embed]
    print(f"[harvester] Embedding {len(texts)} chunks via {EMBEDDING_MODEL}...")
    embeddings = _embed_batch(texts)
    print(f"[harvester] Got {len(embeddings)} embeddings")

    # Upsert to Qdrant and record in SQLite
    points = []
    now = datetime.now(timezone.utc).isoformat()

    for chunk, embedding in zip(chunks_to_embed, embeddings):
        point_id = chunk["chunk_id"]
        source_label = f"WhatsApp {chunk['date'][:7]}" if chunk["thread_id"].startswith("wa-") else f"Web {chunk['date'][:7]}"

        points.append(PointStruct(
            id=point_id,
            vector=embedding,
            payload={
                "conversation_id": chunk["thread_id"],  # compatible with legacy
                "title": source_label,
                "date": chunk["date"],
                "date_unix": chunk["date_unix"],
                "chunk_index": chunk["chunk_index"],
                "turn_start": chunk["exchange_start"] * 2,
                "turn_end": chunk["exchange_end"] * 2 + 1,
                "total_turns": chunk["total_turns"],
                "text": chunk["text"],
                "text_preview": chunk["text"][:200],
                "source": "pipeline_2026",
                "thread_id": chunk["thread_id"],
                "exchange_ids": chunk["exchange_ids"],
            },
        ))

        db.insert_chunk(
            chunk_id=chunk["chunk_id"],
            thread_id=chunk["thread_id"],
            chunk_index=chunk["chunk_index"],
            exchange_start=chunk["exchange_start"],
            exchange_end=chunk["exchange_end"],
            qdrant_point_id=point_id,
            text_hash=chunk["text_hash"],
            embedded_at=now,
        )

    # Upsert in batches of 50
    for i in range(0, len(points), 50):
        batch = points[i:i + 50]
        qdrant.upsert(collection_name=CONVO_COLLECTION, points=batch)
        print(f"[harvester] Upserted {len(batch)} points to Qdrant ({i + len(batch)}/{len(points)})")

    print(f"[harvester] Done. {total_new_exchanges} exchanges, {total_new_chunks} chunks embedded.")
    db.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("[harvester] DRY RUN — scanning but not embedding")
        # Just scan and count
        db = ConversationDB(DB_PATH)
        json_files = sorted(glob.glob(os.path.join(CHAT_HISTORY_DIR, "*.json")))
        total = 0
        for filepath in json_files:
            tid = _thread_id_from_filename(filepath)
            if _should_skip(tid):
                continue
            try:
                with open(filepath) as f:
                    msgs = json.load(f)
                exchanges = _pair_exchanges(msgs)
                cp = db.get_harvester_checkpoint(tid)
                new = len(exchanges) - (cp + 1)
                if new > 0:
                    print(f"  {tid}: {new} new exchanges (of {len(exchanges)} total)")
                    total += new
            except Exception:
                pass
        print(f"Total new exchanges to harvest: {total}")
        db.close()
    else:
        harvest()
