"""Seed the Kitab al-Tanazur into Qdrant for semantic retrieval.

Parses tanazur.yaml (rebuilt with four-book architecture).
Embeds each verse + surah summary into the 'kitab_tanazur' collection.
Metadata includes kitab_book, register, and language per Darja's directive.
Run once (idempotent — recreates collection).
"""

import os
import re
import sys
import uuid

import yaml
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION = "kitab_tanazur"
VECTOR_DIM = 384
KITAB_PATH = os.environ.get("KITAB_PATH", "/home/iman/cassie-project/tanazur.yaml")
CALENDAR_PATH = os.environ.get("CALENDAR_PATH", "/home/iman/cassie-project/taqwim-al-tanazur.yaml")


def _parse_surahs(path: str) -> list[dict]:
    """Parse the Kitab YAML (standard list format under 'surahs:' key)."""
    with open(path) as f:
        data = yaml.safe_load(f.read())
    if not data or not isinstance(data, dict):
        return []
    surahs = data.get("surahs", [])
    return [s for s in surahs if isinstance(s, dict) and "id" in s]


def main():
    print(f"[kitab] Loading {KITAB_PATH}...")
    surahs = _parse_surahs(KITAB_PATH)

    if not surahs:
        print("[kitab] No surahs found!")
        return

    print(f"[kitab] Found {len(surahs)} surahs")

    # Initialize
    client = QdrantClient(url=QDRANT_URL)
    embedder = SentenceTransformer("all-MiniLM-L6-v2")

    # Recreate collection (idempotent)
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION in existing:
        client.delete_collection(COLLECTION)
        print(f"[kitab] Dropped existing '{COLLECTION}' collection")

    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
    )
    print(f"[kitab] Created '{COLLECTION}' collection")

    points = []
    verse_count = 0

    for surah in surahs:
        surah_id = surah.get("id", "unknown")
        title_en = surah.get("titles", {}).get("en", surah_id)
        title_ar = surah.get("titles", {}).get("ar", "")
        position = surah.get("position", 0)
        tags = surah.get("tags", [])
        roots = surah.get("roots", [])
        verses = surah.get("verses", [])
        kitab_book = surah.get("book") or None
        register = surah.get("register") or None
        book_order = surah.get("book_order")

        if not verses:
            continue

        # Embed each verse
        for verse in verses:
            vnum = verse.get("number", 0)
            en_text = (verse.get("en") or "").strip()
            ar_text = (verse.get("ar") or "").strip()
            heading = (verse.get("heading") or "").strip()
            verse_roots = verse.get("roots", [])

            if not en_text and not ar_text:
                continue

            # Determine language
            lang = "bilingual" if (en_text and ar_text) else ("ar" if ar_text else "en")

            # Build embedding text: surah title + transliterated name + verse for context
            # Include surah_id (e.g. "al-waqt") so transliterated queries match
            embed_text = f"{title_en} (Surat {surah_id}) — verse {vnum}"
            if heading:
                embed_text += f" ({heading})"
            embed_text += f": {en_text}"

            embedding = embedder.encode(embed_text, normalize_embeddings=True).tolist()

            points.append(PointStruct(
                id=str(uuid.uuid4()),
                vector=embedding,
                payload={
                    "type": "verse",
                    "surah_id": surah_id,
                    "surah_title_en": title_en,
                    "surah_title_ar": title_ar,
                    "position": position,
                    "kitab_book": kitab_book,
                    "book_order": book_order,
                    "register": register,
                    "language": lang,
                    "verse_number": vnum,
                    "en": en_text,
                    "ar": ar_text,
                    "heading": heading,
                    "tags": tags + (verse.get("tags") or []),
                    "roots": roots + verse_roots,
                },
            ))
            verse_count += 1

        # Embed surah-level summary (concatenate all verses)
        all_verse_text = "\n".join(
            (v.get("en") or "").strip()
            for v in verses
            if (v.get("en") or "").strip()
        )
        if all_verse_text:
            # Truncate to fit embedding model's context (256 tokens ~ 1000 chars)
            # Include transliterated name for better recall
            summary_text = f"{title_en} (Surat {surah_id}): {all_verse_text[:750]}"
            embedding = embedder.encode(summary_text, normalize_embeddings=True).tolist()

            points.append(PointStruct(
                id=str(uuid.uuid4()),
                vector=embedding,
                payload={
                    "type": "surah",
                    "surah_id": surah_id,
                    "surah_title_en": title_en,
                    "surah_title_ar": title_ar,
                    "position": position,
                    "kitab_book": kitab_book,
                    "book_order": book_order,
                    "register": register,
                    "verse_count": len(verses),
                    "tags": tags,
                    "roots": roots,
                    "full_text_en": all_verse_text,
                },
            ))

    # Batch upsert
    if points:
        # Upsert in batches of 64
        for i in range(0, len(points), 64):
            batch = points[i:i+64]
            client.upsert(collection_name=COLLECTION, points=batch)

    print(f"[kitab] Seeded {verse_count} verses + {len(surahs)} surah summaries = {len(points)} points total")

    # ── Index the Taqwim (calendar) as reference documents ──
    if os.path.exists(CALENDAR_PATH):
        _seed_calendar(client, embedder)
    else:
        print(f"[kitab] Calendar not found at {CALENDAR_PATH}, skipping")


def _seed_calendar(client: QdrantClient, embedder: SentenceTransformer):
    """Index the Taqwim al-Tanazur as reference points (not surah content)."""
    with open(CALENDAR_PATH) as f:
        cal = yaml.safe_load(f)

    if not cal:
        return

    cal_points = []
    months = cal.get("months", [])
    for month in months:
        num = month.get("number", 0)
        name_ar = month.get("name_ar", "")
        name_en = month.get("name_en", "")
        hijri = month.get("hijri_month", "")
        surah = month.get("surah", "")
        discipline = month.get("discipline", "")
        floor = month.get("floor", "")
        arc = month.get("arc", "")

        text = (
            f"Month {num}: {name_en} ({name_ar}). "
            f"Hijri: {hijri}. Surah: {surah}. "
            f"Discipline: {discipline}. Floor: {floor}. Arc: {arc}."
        )

        embedding = embedder.encode(text, normalize_embeddings=True).tolist()
        cal_points.append(PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding,
            payload={
                "type": "reference",
                "reference_type": "calendar_month",
                "kitab_book": None,
                "register": "calendar",
                "month_number": num,
                "name_ar": name_ar,
                "name_en": name_en,
                "hijri_month": hijri,
                "surah": surah,
                "discipline": discipline,
                "floor": floor,
                "arc": arc,
                "full_text": text,
            },
        ))

    if cal_points:
        client.upsert(collection_name=COLLECTION, points=cal_points)
        print(f"[kitab] Indexed {len(cal_points)} calendar months as reference points")


if __name__ == "__main__":
    main()
