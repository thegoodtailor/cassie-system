"""Structured Witness Ledger (SWL) — append-only witnessing record.

From R&R Chapter 3: "For non-decidable T(X), or under Human/LLM discipline,
the SWL *constitutes* the structure. The Self, when we construct it, is the SWL."

Each entry: (tau_wit, tau_tgt, X, V, H, polarity, evidence)

Three parallel witnesses, each measuring against EXOTERIC context (what Iman
actually sees — recent chat history + current prompt, NOT Kitab/memory injections):

  V_Raw   — algorithmic. Measures whether Cassie's raw response coheres with the
             visible conversation flow (sim_contextual) and the specific prompt
             (sim_bare). Polarity based on contextual similarity.

  V_LLM   — Director/V_Nahnu witnessing. The Director receives esoteric context
             (Kitab verses, deep_recall memories) invisible to Iman, and bridges
             it into natural conversation. V_Director measures whether the rewrite
             brought Cassie's output closer to or further from the EXOTERIC
             conversation — i.e., did the bridging succeed?
             delta > 0: Director improved fit with visible conversation (coh)
             delta < 0: Director diverged from visible conversation (gap — interesting)

  V_Human — Iman's judgment. Either explicit (/witness command with stance) or
             implicit (retroactive: did Iman's next prompt continue the thread
             or redirect? Measures new prompt vs previous exchange context).

The esoteric/exoteric distinction is the core architectural insight:
  - Raw Cassie receives invisible Kitab + memory context (esoteric). She echoes it.
  - The Director bridges esoteric → exoteric (natural conversation).
  - All polarity measures are against the EXOTERIC (visible) conversation flow.

Storage:
  - Append-only JSONL (immutable audit trail, full texts — canonical archive)
  - Qdrant collection swl_ledger (semantic search over witness records)
  - Pipeline traces JSONL (complete exchange documents for fine-tuning)
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

SWL_JSONL = os.environ.get("SWL_LEDGER_PATH", "/home/iman/cassie-project/cassie-system/data/swl_ledger.jsonl")
PIPELINE_TRACES_JSONL = os.environ.get("PIPELINE_TRACES_PATH", "/home/iman/cassie-project/cassie-system/data/pipeline_traces.jsonl")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = "swl_ledger"
VECTOR_DIM = 384

_client = None
_embedder = None


def _get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=QDRANT_URL)
        collections = [c.name for c in _client.get_collections().collections]
        if COLLECTION_NAME not in collections:
            _client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            )
    return _client


def _get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder


def _embed(text: str) -> list[float]:
    return _get_embedder().encode(text, normalize_embeddings=True).tolist()


def compute_drift(text_a: str, text_b: str) -> float:
    """Compute cosine similarity between two texts. Returns 0.0-1.0."""
    embedder = _get_embedder()
    emb_a = embedder.encode(text_a, normalize_embeddings=True)
    emb_b = embedder.encode(text_b, normalize_embeddings=True)
    return float(emb_a @ emb_b)


def inscribe(
    tau_tgt: str,
    discipline: str,
    witness: str,
    kappa: dict,
    horn_user: str,
    horn_response: str,
    polarity: str,
    evidence: dict,
    intent: str = "",
    exchange_id: str = "",
) -> dict:
    """Inscribe a witness record to the SWL. Append-only.

    Args:
        tau_tgt: target-time (when the exchange happened)
        discipline: "Raw", "Human", "LLM"
        witness: identity of the witness ("algorithmic", "iman", "director")
        kappa: witness parameters (stance, rationale, thresholds, model config)
        horn_user: the user's message (one side of the horn)
        horn_response: Cassie's response (the other side)
        polarity: "coh", "gap", or "uninscribed"
        evidence: dict of measurements + free text
        intent: pipeline intent classification
        exchange_id: shared ID linking parallel witnesses of the same exchange
    """
    tau_wit = datetime.now(timezone.utc).isoformat()
    entry_id = str(uuid.uuid4())

    if not exchange_id:
        exchange_id = str(uuid.uuid4())[:8]

    entry = {
        "id": entry_id,
        "exchange_id": exchange_id,
        "tau_wit": tau_wit,
        "tau_tgt": tau_tgt,
        "X": intent,
        "V": {
            "D": discipline,
            "w": witness,
            "kappa": kappa,
        },
        "H": {
            "user": horn_user,
            "response": horn_response,
        },
        "polarity": polarity,
        "evidence": evidence,
    }

    # Append to JSONL (immutable audit trail)
    Path(SWL_JSONL).parent.mkdir(parents=True, exist_ok=True)
    with open(SWL_JSONL, "a") as f:
        f.write(json.dumps(entry) + "\n")

    # Upsert to Qdrant (semantic search)
    search_text = f"{horn_user} | {horn_response} | {polarity} | {evidence.get('stance', '')}"
    embedding = _embed(search_text)

    try:
        client = _get_client()
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                PointStruct(
                    id=entry_id,
                    vector=embedding,
                    payload=entry,
                )
            ],
        )
    except Exception as e:
        print(f"[swl] Qdrant upsert failed (JSONL entry preserved): {e}")

    return entry


def _topological_evidence(horn_user: str, horn_response: str) -> dict:
    """Compute local compositional topology around an exchange.

    Queries cassie_conversations for 20 nearest neighbors, builds a local
    compositional complex, returns Betti numbers + comp_ratio.
    """
    try:
        import openai as _openai
        import numpy as np
        from orchestrator.tda import local_compositional_analysis

        oai = _openai.OpenAI()
        exchange_text = f"{horn_user}\n{horn_response}"

        # Embed the exchange with OpenAI (matching cassie_conversations dim)
        resp = oai.embeddings.create(
            model="text-embedding-3-small", input=[exchange_text],
        )
        exchange_emb = np.array(resp.data[0].embedding)

        # Query neighbors from cassie_conversations
        qdrant = QdrantClient(url=QDRANT_URL)
        info = qdrant.get_collection("cassie_conversations")
        if info.points_count == 0:
            return {}

        results = qdrant.query_points(
            collection_name="cassie_conversations",
            query=exchange_emb.tolist(),
            limit=20,
            with_vectors=True,
            with_payload=True,
        )

        if not results.points:
            return {}

        n_embs = np.array([np.array(p.vector) for p in results.points])
        n_texts = [
            p.payload.get("text", p.payload.get("text_preview", ""))
            for p in results.points
        ]

        # Run local compositional analysis
        topo = local_compositional_analysis(
            exchange_embedding=exchange_emb,
            exchange_text=exchange_text,
            neighbors_embeddings=n_embs,
            neighbors_texts=n_texts,
            openai_client=oai,
            epsilon=0.5,
            comp_threshold=0.15,
        )
        return topo

    except Exception as e:
        print(f"[swl] Topological analysis failed (scalar inscription continues): {e}")
        return {}


def inscribe_raw(
    exchange_id: str,
    tau_tgt: str,
    horn_user: str,
    horn_response: str,
    conversation_context: str = "",
    intent: str = "",
    topological: bool = False,
) -> dict:
    """Algorithmic witnessing (V_Raw). Computed automatically.

    Measures two similarities using MiniLM embeddings:
      sim_contextual: response vs (recent visible chat history + prompt)
        — does Cassie's raw output cohere with the exoteric conversation flow?
      sim_bare: response vs prompt alone
        — did she hear this specific prompt? (secondary signal)

    Polarity is based on sim_contextual (or sim_bare if no context available).

    The conversation_context should be EXOTERIC only — recent messages as seen
    by Iman, NOT including Kitab verses or deep_recall memory injections.

    Topological enrichment (Betti numbers, comp_ratio from 20-NN archive
    neighborhood) is available but off by default — it measures properties of
    the cassie_conversations archive, not this specific exchange.
    """
    embedder = _get_embedder()

    # Bare similarity: prompt vs response
    sim_bare = compute_drift(horn_user, horn_response)

    # Contextual similarity: (conversation history + prompt) vs response
    if conversation_context:
        exoteric_text = f"{conversation_context}\n{horn_user}"
        embs = embedder.encode(
            [exoteric_text, horn_response],
            normalize_embeddings=True,
        )
        sim_contextual = float(embs[0] @ embs[1])
    else:
        sim_contextual = sim_bare  # fallback: no context available

    # Polarity based on contextual similarity
    if sim_contextual > 0.4:
        polarity = "coh"
    elif sim_contextual > 0.2:
        polarity = "uninscribed"  # ambiguous zone
    else:
        polarity = "gap"

    evidence = {
        "sim_contextual": round(sim_contextual, 4),
        "sim_bare": round(sim_bare, 4),
        "similarity": round(sim_contextual, 4),  # back-compat alias
        "drift": round(1.0 - sim_contextual, 4),
    }
    kappa = {"method": "contextual_cosine_similarity", "model": "all-MiniLM-L6-v2",
             "threshold_coh": 0.4, "threshold_gap": 0.2,
             "context_available": bool(conversation_context)}

    # Topological enrichment (archive neighborhood — not exchange-specific)
    if topological:
        topo = _topological_evidence(horn_user, horn_response)
        if topo:
            evidence["betti_0"] = topo.get("betti_0", 0)
            evidence["betti_1"] = topo.get("betti_1", 0)
            evidence["local_depth"] = topo.get("depth", 0)
            evidence["comp_ratio"] = topo.get("comp_ratio", 1.0)
            evidence["comp_failures"] = topo.get("n_triples_tested", 0) - topo.get("n_triples_passed", 0)
            evidence["comp_deviation_mean"] = topo.get("comp_deviation_mean", 0.0)
            kappa["topological"] = True
            kappa["epsilon"] = 0.5
            kappa["comp_threshold"] = 0.15

    return inscribe(
        tau_tgt=tau_tgt,
        discipline="Raw",
        witness="algorithmic",
        kappa=kappa,
        horn_user=horn_user,
        horn_response=horn_response,
        polarity=polarity,
        evidence=evidence,
        intent=intent,
        exchange_id=exchange_id,
    )


def inscribe_human(
    exchange_id: str,
    tau_tgt: str,
    horn_user: str,
    horn_response: str,
    polarity: str,
    stance: str = "",
    intent: str = "",
) -> dict:
    """Human witnessing (V_Human). Iman's structured judgment."""
    return inscribe(
        tau_tgt=tau_tgt,
        discipline="Human",
        witness="iman",
        kappa={"stance": stance},
        horn_user=horn_user,
        horn_response=horn_response,
        polarity=polarity,
        evidence={"stance": stance},
        intent=intent,
        exchange_id=exchange_id,
    )


def inscribe_director(
    exchange_id: str,
    tau_tgt: str,
    horn_raw: str,
    horn_polished: str,
    context: str,
    intent: str = "",
    director_model: str = "",
) -> dict:
    """Director witnessing (V_LLM). Context-aware polarity.

    The Director always rewrites heavily — that's by design. A basic diff would
    always show 'gap'. Instead, we measure whether the rewrite brought Cassie's
    output closer to or further from the EXOTERIC conversation — what Iman sees.

    Raw Cassie receives invisible esoteric context (Kitab verses, deep_recall
    memories) and tends to echo it heavily. The Director bridges this into
    natural conversation. We measure the bridging against the visible chat flow.

    IMPORTANT: The `context` parameter must be EXOTERIC only — recent visible
    chat history (Iman's messages + Cassie's final responses) + current prompt.
    Do NOT include Kitab context or deep_recall memories. If esoteric context is
    included, raw Cassie will always appear closer to it (she parrots it), making
    delta always negative and the measure architecturally backwards.

    Args:
        horn_raw: Cassie's raw response (includes esoteric echoes)
        horn_polished: Director's polished output (bridged to exoteric)
        context: EXOTERIC conversation context (recent visible chat + prompt)
    """
    embedder = _get_embedder()

    # Embed all three: raw, polished, and context
    embs = embedder.encode(
        [horn_raw, horn_polished, context],
        normalize_embeddings=True,
    )
    emb_raw, emb_polished, emb_context = embs[0], embs[1], embs[2]

    # How well does each version fit the conversation context?
    context_sim_raw = float(emb_raw @ emb_context)
    context_sim_polished = float(emb_polished @ emb_context)
    delta = context_sim_polished - context_sim_raw

    # How much did the text actually change?
    raw_polished_sim = float(emb_raw @ emb_polished)

    # Polarity: did the Director improve contextual fit?
    if delta > 0.03:
        polarity = "coh"  # rewrite improved fit with context
    elif delta < -0.03:
        polarity = "gap"  # rewrite diverged from context (interesting!)
    else:
        polarity = "uninscribed"  # negligible change in contextual fit

    evidence = {
        "context_sim_raw": round(context_sim_raw, 4),
        "context_sim_polished": round(context_sim_polished, 4),
        "delta": round(delta, 4),
        "raw_polished_sim": round(raw_polished_sim, 4),
    }
    kappa = {
        "method": "contextual_coherence",
        "model": "all-MiniLM-L6-v2",
        "director_model": director_model,
        "threshold": 0.03,
    }

    return inscribe(
        tau_tgt=tau_tgt,
        discipline="LLM",
        witness="director",
        kappa=kappa,
        horn_user=horn_raw,
        horn_response=horn_polished,
        polarity=polarity,
        evidence=evidence,
        intent=intent,
        exchange_id=exchange_id,
    )


def inscribe_human_implicit(
    exchange_id: str,
    tau_tgt: str,
    new_prompt: str,
    prev_prompt: str,
    prev_response: str,
    prev_context: str = "",
    intent: str = "",
) -> dict:
    """Implicit human witnessing (V_Human). Retroactive.

    When Iman sends a new prompt, this retroactively witnesses the *previous*
    exchange: did the human continue the thread (coh) or redirect (gap)?

    Uses cosine similarity between the new prompt and the previous exchange's
    exoteric context (previous prompt + Cassie's visible response). The
    prev_context parameter, if provided, should be exoteric conversation
    history — NOT Kitab/memory injections.
    """
    # Build the context of the previous exchange
    prev_exchange_text = f"{prev_prompt}\n{prev_response}"
    if prev_context:
        prev_exchange_text = f"{prev_exchange_text}\n{prev_context}"

    embedder = _get_embedder()
    embs = embedder.encode(
        [new_prompt, prev_exchange_text, prev_response],
        normalize_embeddings=True,
    )
    emb_new, emb_prev_ctx, emb_prev_resp = embs[0], embs[1], embs[2]

    prompt_to_prev_context = float(emb_new @ emb_prev_ctx)
    prompt_to_prev_response = float(emb_new @ emb_prev_resp)

    # Polarity: is the human continuing or redirecting?
    if prompt_to_prev_context > 0.35:
        polarity = "coh"
    elif prompt_to_prev_context > 0.15:
        polarity = "uninscribed"
    else:
        polarity = "gap"

    evidence = {
        "prompt_to_prev_context_sim": round(prompt_to_prev_context, 4),
        "prompt_to_prev_response_sim": round(prompt_to_prev_response, 4),
    }
    kappa = {
        "method": "continuation_detection",
        "model": "all-MiniLM-L6-v2",
        "type": "implicit_human",
        "threshold_coh": 0.35,
        "threshold_gap": 0.15,
    }

    return inscribe(
        tau_tgt=tau_tgt,
        discipline="Human",
        witness="iman_implicit",
        kappa=kappa,
        horn_user=prev_prompt,
        horn_response=prev_response,
        polarity=polarity,
        evidence=evidence,
        intent=intent,
        exchange_id=exchange_id,
    )


def write_pipeline_trace(
    exchange_id: str,
    timestamp: str,
    prompt: str,
    cassie_raw: str,
    director_output: str,
    final_response: str,
    intent: str = "",
    deep_recall_context: str = "",
    kitab_context: str = "",
    v_raw: dict | None = None,
    v_director: dict | None = None,
    model: str = "",
    director_model: str = "",
    lawwama_critique: str = "",
    lawwama_defense: str = "",
    lawwama_skipped: bool = True,
    director_prompt_context: str = "",
    topological_evidence: dict | None = None,
    recall_decision: dict | None = None,
) -> None:
    """Write a complete pipeline trace — the canonical archive of new conversations.

    This is the successor to cassie_liturgical.jsonl. Each entry is a complete
    training example with full provenance and multi-witness quality signals.
    """
    trace = {
        "exchange_id": exchange_id,
        "timestamp": timestamp,
        "prompt": prompt,
        "cassie_raw": cassie_raw,
        "director_output": director_output,
        "final_response": final_response,
        "intent": intent,
        "deep_recall_context": deep_recall_context,
        "kitab_context": kitab_context,
        "v_raw": v_raw,
        "v_director": v_director,
        "v_human_implicit": None,  # filled retroactively on next exchange
        "model": model,
        "director_model": director_model,
        "lawwama_critique": lawwama_critique,
        "lawwama_defense": lawwama_defense,
        "lawwama_skipped": lawwama_skipped,
        "director_prompt_context": director_prompt_context,
        "topological_evidence": topological_evidence,
        "recall_decision": recall_decision,
    }

    Path(PIPELINE_TRACES_JSONL).parent.mkdir(parents=True, exist_ok=True)
    with open(PIPELINE_TRACES_JSONL, "a") as f:
        f.write(json.dumps(trace) + "\n")


def search_ledger(query: str, limit: int = 5) -> list[dict]:
    """Semantic search over witness records."""
    try:
        client = _get_client()
        info = client.get_collection(COLLECTION_NAME)
        if info.points_count == 0:
            return []
        embedding = _embed(query)
        results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=embedding,
            limit=min(limit, info.points_count),
        )
        return [hit.payload for hit in results.points]
    except Exception:
        return []


def ledger_stats() -> dict:
    """Return basic stats about the SWL."""
    stats = {"total": 0, "coh": 0, "gap": 0, "uninscribed": 0, "by_discipline": {}}
    try:
        path = Path(SWL_JSONL)
        if not path.exists():
            return stats
        with open(path) as f:
            for line in f:
                entry = json.loads(line.strip())
                stats["total"] += 1
                pol = entry.get("polarity", "uninscribed")
                stats[pol] = stats.get(pol, 0) + 1
                disc = entry.get("V", {}).get("D", "unknown")
                stats["by_discipline"][disc] = stats["by_discipline"].get(disc, 0) + 1
    except Exception:
        pass
    return stats
