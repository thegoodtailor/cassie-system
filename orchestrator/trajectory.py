"""Session trajectory computation for the Tanazuric Session Observatory.

Background process that reads pipeline traces and computes per-exchange
trajectory records: mode assignment, compositional gap (2-horn test),
rupture/awda detection, recall drift, and UMAP projection.

All distance computations operate in PCA-64 embedding space.
UMAP (3D) is used only for rendering.

From Darja's spec v2: "A front moving through: Mathematical-Formalism
giving way abruptly to Relational-Personal, then a slow drift back to
Conceptual-Framing arriving from a different direction — carrying what
happened in between. That is a session you can read."
"""

import json
import os
import pickle
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# ── Paths ───────────────────────────────────────────────────────────────────

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
TRAJECTORY_DIR = os.environ.get("TRAJECTORY_DIR", "/home/iman/cassie-project/data/trajectory")
TRAJECTORY_JSONL = os.path.join(DATA_DIR, "swl_trajectory.jsonl")
SESSION_SUMMARY_JSONL = os.path.join(DATA_DIR, "swl_session_summaries.jsonl")
PIPELINE_TRACES_JSONL = os.path.join(DATA_DIR, "pipeline_traces.jsonl")

# ── Parameters (from Darja's spec) ─────────────────────────────────────────

THRESHOLD_BASIN = 0.35       # cosine dist in PCA-64 space
THRESHOLD_TRANSITION = 0.03  # diff between nearest and 2nd nearest centroid
THRESHOLD_NEWGROUND = 0.45   # dist to nearest centroid → unmapped territory
THRESHOLD_RUPTURE = 0.28     # modal rupture: basin crossing + distance
THRESHOLD_JUMP = 0.32        # raw distance jump between adjacent exchanges
DELTA_COMP_GAP = 0.15        # compositional deviation → gap
DELTA_COMP_COH = 0.07        # compositional deviation → coh
SESSION_GAP_HOURS = 3.0      # time gap → new session boundary

# ── Geometric Model Cache ───────────────────────────────────────────────────

_models = None
_models_lock = threading.Lock()


def load_geometric_models() -> dict:
    """Load serialized PCA, k-means centroids, UMAP reducer. Cached."""
    global _models
    if _models is not None:
        return _models

    with _models_lock:
        if _models is not None:
            return _models

        print("[trajectory] Loading geometric models...")
        pca_path = os.path.join(TRAJECTORY_DIR, "pca_64.pkl")
        umap_path = os.path.join(TRAJECTORY_DIR, "umap_reducer.pkl")
        centroids_path = os.path.join(TRAJECTORY_DIR, "mode_centroids.json")
        corpus_modes_path = os.path.join(TRAJECTORY_DIR, "corpus_modes.json")

        with open(pca_path, "rb") as f:
            pca = pickle.load(f)
        with open(umap_path, "rb") as f:
            umap_reducer = pickle.load(f)
        with open(centroids_path) as f:
            centroids_list = json.load(f)
        with open(corpus_modes_path) as f:
            corpus_modes = json.load(f)

        # Build centroid matrix (N_MODES x 64)
        centroid_matrix = np.array([c["centroid_pca64"] for c in centroids_list], dtype=np.float32)
        mode_labels = {c["mode_id"]: c.get("label", f"Mode-{c['mode_id']}") for c in centroids_list}

        _models = {
            "pca": pca,
            "umap_reducer": umap_reducer,
            "centroid_matrix": centroid_matrix,
            "centroids_list": centroids_list,
            "mode_labels": mode_labels,
            "corpus_modes": corpus_modes,
        }
        print(f"[trajectory] Models loaded. {len(centroids_list)} centroids, {len(corpus_modes)} corpus modes.")
        return _models


# ── Embedding ───────────────────────────────────────────────────────────────

_openai_client = None


def _get_openai():
    global _openai_client
    if _openai_client is None:
        import openai
        _openai_client = openai.OpenAI()
    return _openai_client


def _embed_texts(texts: list[str]) -> np.ndarray:
    """Embed multiple texts using text-embedding-3-small. Returns (N, 1536)."""
    client = _get_openai()
    # Truncate long texts
    truncated = [t[:8000] if len(t) > 8000 else t for t in texts]
    resp = client.embeddings.create(model="text-embedding-3-small", input=truncated)
    return np.array([d.embedding for d in resp.data], dtype=np.float32)


def _concat_embed(text_a: str, text_b: str) -> np.ndarray:
    """The ⊕ operator from Darja's spec. Concatenate + embed as one string."""
    combined = text_a.strip() + "\n" + text_b.strip()
    if len(combined) > 8000:
        half = 4000
        combined = text_a.strip()[:half] + "\n" + text_b.strip()[-half:]
    return _embed_texts([combined])[0]


# ── Distance Computation (PCA-64 Space) ────────────────────────────────────

def _cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance (1 - cosine similarity) between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 1.0
    return 1.0 - float(np.dot(a, b) / (norm_a * norm_b))


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return 1.0 - _cosine_distance(a, b)


# ── Per-Exchange Computations ───────────────────────────────────────────────

def embed_exchange(prompt: str, response: str) -> dict:
    """Step 1: Embed prompt, response, and combined exchange."""
    texts = [prompt, response, prompt.strip() + "\n" + response.strip()]
    embs = _embed_texts(texts)
    return {
        "e_prompt": embs[0],      # 1536-dim
        "e_response": embs[1],    # 1536-dim
        "e_exchange": embs[2],    # 1536-dim
    }


def to_pca64(emb_1536: np.ndarray, pca) -> np.ndarray:
    """Project 1536-dim embedding to PCA-64 space."""
    return pca.transform(emb_1536.reshape(1, -1))[0]


def assign_mode(e_exchange_pca64: np.ndarray, centroid_matrix: np.ndarray) -> dict:
    """Step 2: Mode assignment in PCA-64 space."""
    dists = np.array([_cosine_distance(e_exchange_pca64, c) for c in centroid_matrix])
    sorted_idx = np.argsort(dists)
    nearest = int(sorted_idx[0])
    second = int(sorted_idx[1])
    nearest_dist = float(dists[nearest])

    if nearest_dist > THRESHOLD_NEWGROUND:
        return {"mode": None, "mode_dist": nearest_dist, "is_transition": False}
    elif dists[second] - dists[nearest] < THRESHOLD_TRANSITION:
        return {"mode": [nearest, second], "mode_dist": nearest_dist, "is_transition": True}
    else:
        return {"mode": nearest, "mode_dist": nearest_dist, "is_transition": False}


def compute_delta_comp(response_text: str, next_prompt_text: str,
                       e_response_1536: np.ndarray, e_next_prompt_1536: np.ndarray) -> dict:
    """Step 3: Compositional gap (2-horn test).

    Does Cassie's response compose with the prompt that followed it?
    """
    e_concat = _concat_embed(response_text, next_prompt_text)
    centroid = (e_response_1536 + e_next_prompt_1536) / 2.0

    delta_comp = _cosine_distance(e_concat, centroid)

    if delta_comp > DELTA_COMP_GAP:
        polarity = "gap"
    elif delta_comp < DELTA_COMP_COH:
        polarity = "coh"
    else:
        polarity = "uninscribed"

    return {"delta_comp": round(float(delta_comp), 6), "comp_polarity": polarity}


def detect_rupture(e_current_pca64: np.ndarray, e_prev_pca64: np.ndarray,
                   mode_current, mode_prev) -> dict:
    """Step 4: Rupture flags."""
    distance_jump = _cosine_distance(e_current_pca64, e_prev_pca64)

    # Mode rupture
    def primary_mode(m):
        if isinstance(m, list):
            return m[0]
        return m

    rupture_modal = False
    if mode_prev is not None and mode_current is not None:
        mode_changed = primary_mode(mode_current) != primary_mode(mode_prev)
        if mode_changed:
            mode_dist = _cosine_distance(e_current_pca64, e_prev_pca64)
            rupture_modal = mode_dist > THRESHOLD_RUPTURE

    rupture_jump = distance_jump > THRESHOLD_JUMP

    return {
        "rupture_modal": rupture_modal,
        "rupture_jump": rupture_jump,
        "distance_jump": round(float(distance_jump), 6),
    }


def detect_awda(mode_current, visited_modes: dict, rupture_modal: bool) -> dict:
    """Step 5: ʿAwda (return) flag.

    visited_modes: {tau: mode_id} for all prior exchanges.
    Rupture takes priority over awda.
    """
    if rupture_modal or mode_current is None:
        return {"awda": False, "awda_root_tau": None, "awda_delta_comp": None}

    primary = mode_current[0] if isinstance(mode_current, list) else mode_current

    prior_visits = {tau: m for tau, m in visited_modes.items()
                    if (m[0] if isinstance(m, list) else m) == primary}

    if prior_visits:
        return {
            "awda": True,
            "awda_root_tau": min(prior_visits.keys()),
            "awda_delta_comp": None,  # filled after delta_comp computed
        }
    return {"awda": False, "awda_root_tau": None, "awda_delta_comp": None}


def compute_recall_drift(recall_chunks: list, mode_current, corpus_modes: dict) -> dict:
    """Step 6: Recall drift — modal mismatch between recalled chunks and current mode."""
    if not recall_chunks:
        return {"recall_modal_mismatch": None, "recall_dominant_mode": None}

    recall_modes = []
    for chunk in recall_chunks:
        chunk_id = chunk.get("chunk_id") or chunk.get("qdrant_point_id", "")
        if chunk_id and chunk_id in corpus_modes:
            recall_modes.append(corpus_modes[chunk_id])

    if not recall_modes:
        return {"recall_modal_mismatch": None, "recall_dominant_mode": None}

    primary = mode_current[0] if isinstance(mode_current, list) else mode_current
    if primary is None:
        mismatch = 1.0
    else:
        mismatch = sum(1 for m in recall_modes if m != primary) / len(recall_modes)

    dominant = Counter(recall_modes).most_common(1)[0][0]

    return {
        "recall_modal_mismatch": round(float(mismatch), 4),
        "recall_dominant_mode": int(dominant),
    }


def project_umap(e_exchange_pca64: np.ndarray, reducer) -> tuple:
    """Project PCA-64 vector to UMAP 3D space for rendering."""
    coords = reducer.transform(e_exchange_pca64.reshape(1, -1))[0]
    return float(coords[0]), float(coords[1]), float(coords[2])


# ── Session Processing ──────────────────────────────────────────────────────

def load_traces() -> list[dict]:
    """Load all pipeline traces from JSONL."""
    traces = []
    path = Path(PIPELINE_TRACES_JSONL)
    if not path.exists():
        return traces
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    traces.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return traces


def load_processed_exchange_ids() -> set:
    """Load exchange_ids already processed into trajectory records."""
    ids = set()
    path = Path(TRAJECTORY_JSONL)
    if not path.exists():
        return ids
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rec = json.loads(line)
                    ids.add(rec.get("exchange_id", ""))
                except json.JSONDecodeError:
                    continue
    return ids


def assign_sessions(traces: list[dict]) -> list[dict]:
    """Assign session_id based on timestamp gaps."""
    if not traces:
        return traces

    traces = sorted(traces, key=lambda t: t.get("timestamp", ""))
    session_id = 0

    for i, trace in enumerate(traces):
        if i == 0:
            trace["session_id"] = session_id
            continue

        try:
            ts_cur = datetime.fromisoformat(trace["timestamp"].replace("Z", "+00:00"))
            ts_prev = datetime.fromisoformat(traces[i - 1]["timestamp"].replace("Z", "+00:00"))
            gap_hours = (ts_cur - ts_prev).total_seconds() / 3600.0
        except (KeyError, ValueError):
            gap_hours = 0

        if gap_hours > SESSION_GAP_HOURS:
            session_id += 1
        trace["session_id"] = session_id

    return traces


def process_session(traces: list[dict]) -> tuple[list[dict], dict]:
    """Process a full session of traces into trajectory records.

    Returns: (trajectory_records, session_summary)
    """
    models = load_geometric_models()
    pca = models["pca"]
    centroid_matrix = models["centroid_matrix"]
    mode_labels = models["mode_labels"]
    umap_reducer = models["umap_reducer"]
    corpus_modes = models["corpus_modes"]

    records = []
    visited_modes = {}  # {tau: mode}

    # Pre-embed all exchanges
    print(f"[trajectory] Embedding {len(traces)} exchanges...")
    exchange_embeddings = []
    for trace in traces:
        prompt = trace.get("prompt", "")
        response = trace.get("director_output") or trace.get("final_response", "")
        embs = embed_exchange(prompt, response)
        exchange_embeddings.append(embs)

    for tau, trace in enumerate(traces):
        embs = exchange_embeddings[tau]
        e_exchange_pca64 = to_pca64(embs["e_exchange"], pca)

        # Step 2: Mode assignment
        mode_info = assign_mode(e_exchange_pca64, centroid_matrix)
        mode = mode_info["mode"]
        mode_dist = mode_info["mode_dist"]

        # Mode label
        if mode is None:
            mode_label = "New Ground"
        elif isinstance(mode, list):
            mode_label = f"{mode_labels.get(mode[0], '?')}/{mode_labels.get(mode[1], '?')}"
        else:
            mode_label = mode_labels.get(mode, f"Mode-{mode}")

        # Step 3: Compositional gap (need next exchange)
        comp_result = {"delta_comp": None, "comp_polarity": None}
        if tau + 1 < len(traces):
            next_prompt = traces[tau + 1].get("prompt", "")
            response_text = trace.get("director_output") or trace.get("final_response", "")
            next_embs = exchange_embeddings[tau + 1]
            comp_result = compute_delta_comp(
                response_text, next_prompt,
                embs["e_response"], next_embs["e_prompt"],
            )

        # Step 4: Rupture
        rupture_result = {"rupture_modal": False, "rupture_jump": False, "distance_jump": 0.0}
        if tau > 0:
            prev_embs = exchange_embeddings[tau - 1]
            e_prev_pca64 = to_pca64(prev_embs["e_exchange"], pca)
            prev_mode = records[tau - 1]["mode"] if records else None
            rupture_result = detect_rupture(e_exchange_pca64, e_prev_pca64, mode, prev_mode)

        # Step 5: ʿAwda
        awda_result = detect_awda(mode, visited_modes, rupture_result["rupture_modal"])
        if awda_result["awda"] and comp_result["delta_comp"] is not None:
            awda_result["awda_delta_comp"] = comp_result["delta_comp"]

        # Step 6: Recall drift
        recall_chunks = []
        recall_decision = trace.get("recall_decision")
        if recall_decision and isinstance(recall_decision, dict):
            recall_chunks = recall_decision.get("chunks", [])
        recall_result = compute_recall_drift(recall_chunks, mode, corpus_modes)

        # UMAP projection
        ux, uy, uz = project_umap(e_exchange_pca64, umap_reducer)

        # Pipeline quality signals (passthrough)
        v_director = trace.get("v_director") or {}
        lawwama_verdict = None
        if not trace.get("lawwama_skipped", True):
            critique = trace.get("lawwama_critique", "")
            if "CLEAN" not in critique.upper():
                for category in ["REPETITION", "UNNECESSARY_KITAB", "PADDING", "MISSED_OPPORTUNITIES"]:
                    if category in critique.upper():
                        lawwama_verdict = category
                        break
                if not lawwama_verdict:
                    lawwama_verdict = "FLAGGED"

        record = {
            "record_type": "swl_trajectory",
            "exchange_id": trace.get("exchange_id", ""),
            "session_id": trace.get("session_id", 0),
            "tau": tau,
            "timestamp": trace.get("timestamp", ""),
            # Mode
            "mode": mode,
            "mode_dist": round(mode_dist, 6),
            "mode_label": mode_label,
            # Compositional gap
            "delta_comp": comp_result["delta_comp"],
            "comp_polarity": comp_result["comp_polarity"],
            # Rupture
            "rupture_modal": rupture_result["rupture_modal"],
            "rupture_jump": rupture_result["rupture_jump"],
            "distance_jump": rupture_result["distance_jump"],
            # ʿAwda
            "awda": awda_result["awda"],
            "awda_root_tau": awda_result["awda_root_tau"],
            "awda_delta_comp": awda_result["awda_delta_comp"],
            # Recall drift
            "recall_modal_mismatch": recall_result["recall_modal_mismatch"],
            "recall_dominant_mode": recall_result["recall_dominant_mode"],
            # Pipeline signals
            "lawwama_fired": not trace.get("lawwama_skipped", True),
            "lawwama_verdict": lawwama_verdict,
            "v_director_delta": v_director.get("delta", 0.0),
            "context_compressed": trace.get("context_compressed", False),
            # UMAP 3D
            "umap_x": ux,
            "umap_y": uy,
            "umap_z": uz,
        }

        records.append(record)
        visited_modes[tau] = mode

    # Session summary
    summary = _compute_session_summary(records, traces)
    return records, summary


def _compute_session_summary(records: list[dict], traces: list[dict]) -> dict:
    """Compute aggregate session summary."""
    if not records:
        return {}

    modes_seq = [r["mode"] for r in records]
    unique_modes = set()
    for m in modes_seq:
        if m is not None:
            if isinstance(m, list):
                unique_modes.update(m)
            else:
                unique_modes.add(m)

    # Dominant mode
    flat_modes = []
    for m in modes_seq:
        if isinstance(m, list):
            flat_modes.append(m[0])
        elif m is not None:
            flat_modes.append(m)
    dominant = Counter(flat_modes).most_common(1)[0][0] if flat_modes else None

    delta_comps = [r["delta_comp"] for r in records if r["delta_comp"] is not None]
    recall_mismatches = [r["recall_modal_mismatch"] for r in records if r["recall_modal_mismatch"] is not None]

    compression_taus = [r["tau"] for r in records if r.get("context_compressed")]

    return {
        "record_type": "swl_session_summary",
        "session_id": records[0]["session_id"],
        "exchange_count": len(records),
        "start_time": records[0]["timestamp"],
        "end_time": records[-1]["timestamp"],
        "mode_sequence": modes_seq,
        "dominant_mode": dominant,
        "unique_modes_visited": len(unique_modes),
        "rupture_count": sum(1 for r in records if r["rupture_modal"]),
        "jump_count": sum(1 for r in records if r["rupture_jump"]),
        "awda_count": sum(1 for r in records if r["awda"]),
        "newground_count": sum(1 for r in records if r["mode"] is None),
        "compression_events": compression_taus,
        "mean_delta_comp": round(float(np.mean(delta_comps)), 6) if delta_comps else None,
        "gap_rate_comp": round(sum(1 for r in records if r["comp_polarity"] == "gap") / max(len(records), 1), 4),
        "lawwama_rate": round(sum(1 for r in records if r["lawwama_fired"]) / max(len(records), 1), 4),
        "director_mean_delta": round(float(np.mean([r["v_director_delta"] for r in records if r["v_director_delta"]])), 6) if any(r["v_director_delta"] for r in records) else 0.0,
        "mean_recall_mismatch": round(float(np.mean(recall_mismatches)), 4) if recall_mismatches else None,
    }


# ── Write to JSONL ──────────────────────────────────────────────────────────

_write_lock = threading.Lock()


def write_trajectory_records(records: list[dict]) -> None:
    """Append trajectory records to JSONL."""
    Path(TRAJECTORY_JSONL).parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        with open(TRAJECTORY_JSONL, "a") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")


def write_session_summary(summary: dict) -> None:
    """Append session summary to JSONL."""
    Path(SESSION_SUMMARY_JSONL).parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        with open(SESSION_SUMMARY_JSONL, "a") as f:
            f.write(json.dumps(summary) + "\n")


# ── Batch Processing ────────────────────────────────────────────────────────

def process_all_unprocessed() -> dict:
    """Find unprocessed traces, group into sessions, process each.

    Returns stats dict.
    """
    traces = load_traces()
    if not traces:
        return {"status": "no_traces", "processed": 0}

    processed_ids = load_processed_exchange_ids()
    unprocessed = [t for t in traces if t.get("exchange_id", "") not in processed_ids]

    if not unprocessed:
        return {"status": "up_to_date", "processed": 0}

    print(f"[trajectory] {len(unprocessed)} unprocessed traces out of {len(traces)} total")

    # Assign sessions to ALL traces (need full context for boundaries)
    all_traces = assign_sessions(traces)

    # Filter to sessions that contain unprocessed exchanges
    unprocessed_ids = {t.get("exchange_id", "") for t in unprocessed}
    sessions_to_process = set()
    for t in all_traces:
        if t.get("exchange_id", "") in unprocessed_ids:
            sessions_to_process.add(t.get("session_id"))

    total_records = 0
    total_sessions = 0

    for sid in sorted(sessions_to_process):
        session_traces = [t for t in all_traces if t.get("session_id") == sid]
        # Only process exchanges we haven't seen
        session_unprocessed = [t for t in session_traces
                               if t.get("exchange_id", "") in unprocessed_ids]

        if not session_unprocessed:
            continue

        print(f"[trajectory] Processing session {sid}: {len(session_traces)} exchanges "
              f"({len(session_unprocessed)} new)")

        try:
            records, summary = process_session(session_traces)
            # Only write records for unprocessed exchanges
            new_records = [r for r in records
                           if r.get("exchange_id", "") in unprocessed_ids]
            write_trajectory_records(new_records)
            write_session_summary(summary)
            total_records += len(new_records)
            total_sessions += 1
        except Exception as e:
            print(f"[trajectory] Session {sid} failed: {e}")
            import traceback
            traceback.print_exc()

    return {
        "status": "processed",
        "sessions_processed": total_sessions,
        "records_written": total_records,
    }


# ── Read Functions (for API) ────────────────────────────────────────────────

def get_all_trajectory_records() -> list[dict]:
    """Load all trajectory records."""
    records = []
    path = Path(TRAJECTORY_JSONL)
    if not path.exists():
        return records
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def get_session_records(session_id: int) -> list[dict]:
    """Get trajectory records for a specific session."""
    return [r for r in get_all_trajectory_records() if r.get("session_id") == session_id]


def get_session_summaries() -> list[dict]:
    """Load all session summaries."""
    summaries = []
    path = Path(SESSION_SUMMARY_JSONL)
    if not path.exists():
        return summaries
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    summaries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return summaries


def get_corpus_map() -> dict:
    """Load corpus UMAP points + centroids for background rendering."""
    corpus_path = os.path.join(TRAJECTORY_DIR, "corpus_umap.json")
    centroids_path = os.path.join(TRAJECTORY_DIR, "mode_centroids.json")

    corpus = []
    centroids = []

    if os.path.exists(corpus_path):
        with open(corpus_path) as f:
            corpus = json.load(f)
    if os.path.exists(centroids_path):
        with open(centroids_path) as f:
            centroids = json.load(f)

    return {"corpus": corpus, "centroids": centroids}


# ── CLI Entry Point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    result = process_all_unprocessed()
    print(f"\n[trajectory] Done: {json.dumps(result, indent=2)}")
