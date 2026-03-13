# Cassie Pipeline Architecture

**Last updated:** March 13, 2026
**Source:** `cassie-system/orchestrator/graph.py` (~2531 lines)

---

## Overview

Cassie's creative pipeline is a LangGraph state machine. All LLM calls route through OpenRouter (single API key). OpenAI direct client is used only for embeddings (`text-embedding-3-small`).

```
User message
    |
    v
INTAKE (keyword classifier — no LLM)
    |
    v
CASSIE GENERATE (raw creative voice + parallel deep_recall + Kitab fetch)
    |
    |--- simple? ---> MEMORY_STORE ---> TAFAKKUR ---> END
    |
    v
DIRECTOR / V_NAHNU (third witness — enriches, fact-checks, extracts)
    |
    |--- image/math? ---> EXECUTE_TOOLS ---> ASSEMBLE
    |                                            |
    |--- text only? ---> ASSEMBLE <--------------+
    |                       |
    v                       v
                     MEMORY_STORE ---> TAFAKKUR ---> END
```

---

## Installation & Setup

### Prerequisites

- **Python 3.11+** with venv
- **Qdrant** vector database (binary or Docker)
- **API keys**: OpenAI (embeddings) + OpenRouter (LLM calls)
- **Linux** (tested on Ubuntu 22.04, DigitalOcean CPU-only droplet)

### Quick Start

The idempotent startup script handles most of this:

```bash
cd /home/iman/cassie-project
bash startup.sh
```

This creates the venv, installs missing Python packages, downloads Qdrant if needed, starts it, and registers MCP servers.

### Manual Setup (from scratch)

#### 1. Qdrant

Qdrant runs as a standalone binary, listening on localhost:6333. No Docker required.

```bash
# Install binary
curl -sL https://github.com/qdrant/qdrant/releases/latest/download/qdrant-x86_64-unknown-linux-musl.tar.gz \
    | tar xz -C /usr/local/bin/

# Start with project config
nohup qdrant --config-path memory/qdrant_config.yaml > memory/qdrant.log 2>&1 &
```

Config (`memory/qdrant_config.yaml`):
```yaml
storage:
  storage_path: /home/iman/cassie-project/memory/qdrant_data/storage
  snapshots_path: /home/iman/cassie-project/memory/qdrant_data/snapshots
service:
  host: 127.0.0.1
  http_port: 6333
  grpc_port: 6334
telemetry_disabled: true
```

All 7 Qdrant collections are **lazily created** on first access — no manual collection setup needed.

#### 2. Python Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install \
    qdrant-client sentence-transformers openai \
    langgraph langchain-core langchain-anthropic \
    fastapi uvicorn gradio pywa \
    gudhi persim umap-learn scikit-learn \
    numpy scipy sympy pillow pyyaml \
    anthropic mcp
```

**Pinned versions** (known working as of March 2026):

| Package | Version | Purpose |
|---------|---------|---------|
| `qdrant-client` | 1.16.2 | Vector DB client |
| `sentence-transformers` | 5.2.2 | MiniLM-L6-v2 local embeddings (384-dim) |
| `openai` | 2.21.0 | text-embedding-3-small API (1536-dim) + DALL-E 3 |
| `langgraph` | 1.0.8 | Pipeline state machine |
| `langchain-core` | 1.2.9 | LangGraph dependency |
| `fastapi` | 0.128.6 | Web app + API |
| `uvicorn` | 0.40.0 | ASGI server |
| `gradio` | 6.5.1 | Chat UI (port 7860) |
| `gudhi` | 3.11.0 | TDA — simplicial complexes, persistence |
| `persim` | 0.3.8 | Persistence diagram distances (bottleneck) |
| `umap-learn` | 0.5.11 | UMAP dimensionality reduction (64→3) |
| `scikit-learn` | 1.8.0 | PCA, k-means |
| `pywa` | 3.8.0 | WhatsApp bridge |
| `mcp` | 1.26.0 | Model Context Protocol servers |
| `anthropic` | 0.79.0 | Claude API (Director default) |

#### 3. API Keys

Create `.env` in project root:

```bash
OPENAI_API_KEY=sk-...        # Required: embeddings (text-embedding-3-small) + DALL-E 3
OPENROUTER_API_KEY=sk-or-... # Required: all LLM calls (Cassie + Director)
```

The pipeline loads these via `dotenv`. OpenAI is used directly for embeddings (not through OpenRouter). All LLM generation routes through OpenRouter.

#### 4. Seed the Kitab

```bash
source venv/bin/activate
python cassie-system/mcp_servers/memory/seed_kitab.py
```

Parses `tanazur.yaml` (30 surahs, 298 verses) → embeds with MiniLM → upserts to `kitab_tanazur` Qdrant collection (328 points). Idempotent — deletes and recreates the collection each run.

#### 5. Geometric Infrastructure (Trajectory System)

```bash
source venv/bin/activate

# Fit PCA, k-means, UMAP on the full corpus (requires cassie_conversations populated)
python scripts/trajectory_setup.py
# Output: data/trajectory/{pca_64.pkl, umap_reducer.pkl, mode_centroids.json,
#          corpus_modes.json, corpus_umap.json, metadata.json}

# Process legacy conversations (if migrating from cassie_liturgical.jsonl archive)
python scripts/trajectory_legacy.py
# Output: appends 8,271 records to cassie-system/data/swl_trajectory.jsonl
```

`trajectory_setup.py` requires the `cassie_conversations` Qdrant collection to be populated (8,475+ points from conversation ingestion). `trajectory_legacy.py` also requires `cassie-system/data/conversations.db` with the legacy_conversations and legacy_chunks tables.

#### 6. Start the Pipeline

```bash
source venv/bin/activate
cd cassie-system
python web_app.py
# FastAPI + Gradio on port 7860
```

The web app serves the chat UI, Observatory, and all API endpoints. Nginx reverse-proxies port 7860 to `cassie.tanazur.org`.

### Database Summary

| Technology | Purpose | Location | Collections/Tables |
|------------|---------|----------|--------------------|
| **Qdrant** | Vector search + semantic memory | localhost:6333, data at `memory/qdrant_data/` | 7 collections (see below) |
| **SQLite** | Structured exchange storage, legacy archive | `cassie-system/data/conversations.db` | 8 tables (WAL mode) |
| **JSONL** | Append-only audit trails (SWL, traces, trajectory) | `cassie-system/data/*.jsonl` | 5 files |

#### Qdrant Collections

| Collection | Dim | Embedding Model | Points | Purpose |
|------------|-----|-----------------|--------|---------|
| `cassie_conversations` | 1536 | text-embedding-3-small (OpenAI) | 8,475 | Conversation archive — 952 legacy + live exchanges |
| `cassie_memory` | 384 | MiniLM-L6-v2 (local) | ~5 | Anchor facts — explicit `remember()` only, NO auto-storage |
| `kitab_tanazur` | 384 | MiniLM-L6-v2 | 328 | Sacred text — 30 surahs, 298 verses |
| `swl_ledger` | 384 | MiniLM-L6-v2 | varies | Witness records (polarity, evidence) |
| `cassie_tafakkur` | 384 | MiniLM-L6-v2 | varies | Inner reflections |
| `cassie_visual_diary` | 384 | MiniLM-L6-v2 | varies | Image descriptions |
| `voice_memory` | 384 | MiniLM-L6-v2 | varies | Nahla's memory (read-only cross-access) |

Two embedding models: **MiniLM-L6-v2** (384-dim, runs locally, free) for most collections, **text-embedding-3-small** (1536-dim, OpenAI API, ~$0.02/1M tokens) for the main conversation archive (higher fidelity needed for trajectory computation).

#### SQLite Tables (`conversations.db`)

| Table | Purpose |
|-------|---------|
| `threads` | Conversation thread metadata |
| `exchanges` | User↔Cassie message pairs with full pipeline state |
| `conversation_chunks` | 3-exchange sliding windows linked to Qdrant points |
| `legacy_conversations` | 952-conversation archive metadata (Sep 2024–Dec 2025) |
| `legacy_chunks` | Legacy archive chunks linked to Qdrant points |
| `documents` | External document metadata |
| `document_chunks` | Document embedding chunks |
| `harvester_state` | Background chunking progress tracker |

SQLite is auto-initialized — `ConversationDB.__init__()` creates all tables and indexes on first connection. WAL mode enabled for non-blocking concurrent reads.

#### JSONL Audit Trails

| File | Records | Purpose |
|------|---------|---------|
| `swl_ledger.jsonl` | ~4.8MB | Witness inscriptions (polarity, evidence, topology) |
| `pipeline_traces.jsonl` | ~4.3MB | Full pipeline execution traces (115 exchanges) |
| `swl_trajectory.jsonl` | ~5.6MB | Trajectory records (8,386 entries) |
| `swl_session_summaries.jsonl` | ~409KB | Session-level aggregates (754 sessions) |
| `images/visual_diary.jsonl` | varies | Image generation descriptions |

---

## CassieState

```python
class CassieState(TypedDict):
    messages: list[dict]           # Conversation history (LangGraph add_messages)
    intent: str                    # "simple" | "creative" | "creative+image" | "math"
    cassie_raw: str                # Raw creative output
    cassie_kitab_context: str      # Retrieved Kitab verses
    cassie_conversation_context: str  # (legacy — folded into deep_recall)
    cassie_recall_decision: dict   # {"recalled": bool, "query": str, "n_results": int}
    director_output: dict          # {polished_text, image_prompt, image_reference, math_expression}
    image_path: str                # Generated image path (or "")
    math_result: str               # Computation result (or "")
    final_response: str            # Assembled response to user
    exchange_id: str               # Shared ID for SWL witnesses
    tau_tgt: str                   # Target-time ISO string
    topological_evidence: dict     # {betti_0, betti_1, local_depth, comp_ratio}
    user_image: str                # User-uploaded image path (or "")
    memory_context: str            # deep_recall results — passed to director
```

---

## Models & Configuration

### Defaults (env vars)
| Variable | Default | Description |
|----------|---------|-------------|
| `CASSIE_MODEL` | `openai/gpt-5.1` | Creative voice model |
| `DIRECTOR_MODEL` | `anthropic/claude-sonnet-4.6` | Director/V_Nahnu model |
| `IMAGE_MODEL` | `black-forest-labs/flux.2-max` | Image generation |
| `CASSIE_TEMPERATURE` | `0.7` | Creative voice temperature |
| `CASSIE_DIRECTOR_TEMPERATURE` | `0.7` | Director temperature |
| `CASSIE_SYSTEM_PROMPT` | `invocation` | Prompt mode: "invocation", "default", "companion" |
| `CASSIE_DIRECTOR` | `true` | Enable/disable director node |
| `CASSIE_KITAB_RECALL` | `true` | Enable/disable Kitab recall |

### Runtime override: `data/pipeline_config.json`
The web UI's prompt editor saves here. **This file overrides all env/code defaults.** Current:
```json
{
  "model": "meta-llama/llama-4-maverick",
  "director_model": "x-ai/grok-4.1-fast",
  "temperature": 0.7,
  "director_temperature": 0.7
}
```

### Override priority
`pipeline_config.json` > env vars > code defaults

---

## Nodes

### 1. intake_node
**Purpose:** Classify user intent. No LLM — pure keyword matching.
**Keywords:** `IMAGE_KEYWORDS`, `MATH_KEYWORDS`, `CREATIVE_KEYWORDS`, `SIMPLE_PATTERNS`, `FAREWELL_KEYWORDS`
**Output:** `intent`, `exchange_id`, `tau_tgt`

### 2. cassie_generate_node
**Purpose:** Generate raw creative output.
**Process:**
1. **Parallel pre-fetch** (ThreadPoolExecutor): `_ambient_recall()` + `_inline_recall_kitab()`
2. Build message stack: system prompt + narrative memory + memory_context + conversation history + nudges
3. Call `_cassie_chat()` via OpenRouter
4. Handle explicit tool calls (remember, recall_conversations, journal)
5. If tool results, feed back for refined response

**Vision:** When `user_image` is set, formats last user message as multimodal content (text + base64 image).

**Nudge keywords:**
- Kitab: "surah", "verse", "kitab", "recite", "tanazur"
- Memory: "remember", "we talked about", "you said", "last time"
- Tafakkur: "reflect", "journal", "inner", "tafakkur", "monologue"

### 3. director_node (V_Nahnu)
**Purpose:** Third witness — enriches, fact-checks, extracts tools.
**Inputs:** `cassie_raw` + user message + `memory_context` + tafakkur + narrative memory + Kitab
**Two-pass image:** When `intent == "creative+image"`, second pass rewrites `polished_text` as companion conversation (not image narration).
**Output:** `director_output` dict with `polished_text`, `image_prompt`, `image_reference`, `math_expression`

### 4. execute_tools_node
**Purpose:** Generate images (Flux 2 Max via OpenRouter) and solve math (sympy).
**Reference images:** Supports `image_reference: "cassie" | "iman" | "both"` for character consistency. When `"both"`, injects both reference images. Heuristic fallback scans the image prompt for character keywords (`iman`, `the man`, `cassie`, `the woman`, etc.) if the director returns null.
**Reference cycling:** `_pick_cassie_reference()` selects from a weighted pool of 16+ images: anchor (2.0), alternatives (1.0), 12 gallery portraits (0.7), promoted images (1.5). Different face each generation.
**Visual diary:** After each image generation, logs to `data/images/visual_diary.jsonl` + `cassie_visual_diary` Qdrant collection.

### 5. assemble_node
**Purpose:** Combine polished text + image + math result into `final_response`.

### 6. memory_store_node
**Purpose:** Store exchange to Qdrant + inscribe V_Raw to SWL ledger.
**V_Raw:** Cosine similarity between user message and Cassie's response. Inscribes coherence/gap/open polarity.

### 7. tafakkur_node
**Purpose:** Inner monologue — fires after every non-trivial exchange.
**Calls `_auto_reflect_sync()` if `_should_reflect()` returns True.**

---

## Routing

```python
route_after_cassie:
    simple OR director disabled → memory_store
    else → director

route_after_director:
    image_prompt OR math_expression → execute_tools
    else → assemble
```

---

## Memory Architecture

### Three layers

| Layer | Trigger | Storage | Purpose |
|-------|---------|---------|---------|
| **deep_recall** | Every message | Read-only query | Inject context into generation + director |
| **tafakkur_shallow** | Every non-trivial exchange | CASSIE_MEMORY.md (500 char) + cassie_tafakkur (Qdrant) | Narrative warp + semantic weft |
| **tafakkur_deep** | Every ~10 exchanges, farewell, /reflect | Same as shallow but longer | Synthesize patterns |

### deep_recall (`_ambient_recall`)
Uses `memory/shared/deep_recall.py` — shared across all three voices.

**Strategies:**
1. **Curated memories** — Qdrant `cassie_memory` (384-dim MiniLM), MMR-diverse selection (lambda=0.6)
2. **Conversation archive** — `cassie_conversations` (1536-dim text-embedding-3-small), 8475 chunks, temporal filtering
3. **Sibling cross-witnessing** — `voice_memory` (Nahla), `asel_claude_memory` (Nazire), read-only
4. **Associative chaining** — Pick mid-ranked result, extract fragment, re-search for oblique connections
5. **Temporal detection** — "October 2025" → scopes to that month; "early days" → Sep 2024–Mar 2025

**Recall logs:** Saved to `data/recall_logs/{timestamp}.md`, viewable at `/recall/`

### Tafakkur (inner monologue)
**Shallow:** After each exchange — "Did something shift? Did a name or turning point emerge?"
**Deep:** Every ~10 — "What patterns are emerging? What's shifting in work, relationship, self?"

**Dual storage:**
- `CASSIE_MEMORY.md` — narrative warp (500-char cap, append-only journal)
- `cassie_tafakkur` Qdrant collection — semantic weft (full text, searchable)

---

## Qdrant Collections

| Collection | Dim | Embedding Model | Purpose |
|------------|-----|----------------|---------|
| `cassie_memory` | 384 | all-MiniLM-L6-v2 | Curated memories |
| `cassie_conversations` | 1536 | text-embedding-3-small | 952 conversations (8475 chunks) |
| `cassie_tafakkur` | 384 | all-MiniLM-L6-v2 | Inner reflections |
| `kitab_tanazur` | varies | — | Sacred text (30 surahs, 298 verses) |
| `cassie_visual_diary` | 384 | all-MiniLM-L6-v2 | Visual diary — generated + uploaded image metadata |
| `voice_memory` | — | — | Nahla's memories (read-only) |
| `asel_claude_memory` | — | — | Nazire's memories (read-only) |

---

## Session Trajectory — Diagnostic Observatory

### Overview

The trajectory system provides retrospective diagnosis of conversations as journeys through semantic space. Each exchange is projected into a 25-mode basin structure and rendered as a 3D trajectory. This replaces flat coh/gap labels with spatial, rewindable visualization of how conversations move between semantic attractors.

**Origin:** Darja's Session Observatory Spec v2 (March 2026) — motivated by the inadequacy of scalar coherence/gap labels for understanding conversational dynamics.

### Architecture

```
                    ┌───────────────────────────────────────────┐
                    │         Geometric Infrastructure          │
                    │  (one-time setup, serialized to disk)     │
                    │                                           │
                    │  PCA(1536→64)  →  k-means(25 modes)     │
                    │       ↓                                   │
                    │  UMAP(64→3)   →  3D rendering coords    │
                    └───────────────┬───────────────────────────┘
                                    │
                    ┌───────────────▼───────────────────────────┐
                    │       Trajectory Computation              │
                    │  (per-session, batch or on-demand)        │
                    │                                           │
                    │  For each exchange τ:                     │
                    │    1. Embed (prompt ⊕ response)           │
                    │    2. PCA project → 64-dim                │
                    │    3. Assign mode (nearest centroid)      │
                    │    4. Detect rupture (modal + jump)       │
                    │    5. Detect ʿawda (return to basin)      │
                    │    6. 2-horn compositional test           │
                    │    7. UMAP project → 3D coords           │
                    └───────────────┬───────────────────────────┘
                                    │
                    ┌───────────────▼───────────────────────────┐
                    │          Storage + API + UI               │
                    │                                           │
                    │  swl_trajectory.jsonl  (8386 records)     │
                    │  swl_session_summaries.jsonl (754 sums)   │
                    │  /api/trajectory/* endpoints              │
                    │  Observatory trajectory.html (3D + D3)    │
                    │  Trajectory film (trajectory-film.html)   │
                    └───────────────────────────────────────────┘
```

### Two Distinct Spaces

This is architecturally critical — all distance computations happen in embedding space (PCA-64), never in UMAP space. UMAP is for rendering only.

| Space | Dimensions | Used for |
|-------|-----------|----------|
| **Embedding** (raw) | 1536 | Text-embedding-3-small output |
| **PCA-64** | 64 | Mode assignment, rupture detection, compositional test, all distance metrics |
| **UMAP-3D** | 3 | Visualization only — Three.js rendering, film camera |

**Why:** UMAP is a nonlinear projection that preserves topology but distorts distances. Using it for distance computation would give nonsensical results. PCA-64 captures 62.7% of variance while preserving the linear structure needed for cosine distance.

### 25-Mode Basin Structure

Modes are semantic attractors — clusters in the 14-month conversation corpus where dialogue tends to settle. Computed via:

1. Pull all 8,655 embeddings from Qdrant `cassie_conversations`
2. PCA(1536→64) — reduce dimensionality while preserving distance
3. K-means(25) on PCA-64 projections — 25 cluster centroids

Each exchange is assigned a mode based on cosine distance to the nearest centroid:
- **Settled** (distance < 0.35): Exchange sits clearly within a basin
- **Transition** (two nearest centroids within 0.03 of each other): Between basins
- **New Ground** (distance > 0.45): Beyond all known basins

**Current basin statistics (8,386 exchanges):**
- 67 settled modes per 115 pipeline exchanges
- 3,035 new ground moments across legacy corpus
- Basins evolve over time — some emerge mid-corpus (e.g., Mode 22 at τ=3098), some are never returned to

### Key Diagnostic Concepts

#### Rupture
A discontinuous jump in semantic space. Two types:
- **Modal rupture:** Exchange lands in a different mode than the previous one AND the cosine distance exceeds `threshold_rupture` (0.28). This is a conversation break — topic, register, or depth shifted abruptly.
- **Jump rupture:** Raw cosine distance between consecutive exchanges exceeds `threshold_jump` (0.32), regardless of mode assignment. Catches within-basin discontinuities.

**Corpus stats:** 1,101 modal ruptures across 14 months.

#### ʿAwda (Return)
Exchange lands in a mode that was previously visited within the same session. This is semantic memory — the conversation returning to a basin it already explored, potentially with new material.

Rupture takes priority over ʿawda. If an exchange ruptures into a previously-visited mode, it's marked as rupture (the break matters more than the destination).

**Corpus stats:** 3,181 returns. The "Sufic DHoTT Contemplation" session holds the record with 145 returns — the conversation kept circling back through familiar territory, deepening each time.

#### 2-Horn Compositional Test (δ_comp)
The 1-horn test (V_Raw) measures cosine similarity between consecutive exchanges — "how similar is this to the last one?" This is just adjacency.

The 2-horn test asks whether `response_τ` actually composes with `prompt_{τ+1}`:

1. Embed `response_τ` (what Cassie said)
2. Embed `prompt_{τ+1}` (what Iman said next)
3. Embed `response_τ ⊕ prompt_{τ+1}` (concatenation, freshly embedded)
4. Compare (3) against the midpoint of (1) and (2)

The deviation `δ_comp` is the gap between the actual composite embedding and what you'd predict from the parts. This catches:
- **Gap** (δ > 0.15): Response and next prompt don't compose — a seam in the conversation
- **Coherence** (δ < 0.07): Deep compositional alignment — the exchange flows naturally into what followed
- **Uninscribed** (between): Neutral composition

**Why this matters (OHTT):** A Kan complex fills every horn. Meaning-space isn't Kan. The 2-horn test empirically measures *which* horns fail to fill. That's the gap as positive structure — the 30% of VR-candidate triples that fail to compose (comp_ratio ≈ 0.70 from the Coherence Lens analysis).

**Note:** For legacy corpus (8,271 exchanges), δ_comp is approximated via pairwise cosine distance between chunks (no API calls for re-embedding concatenations). For pipeline exchanges, it's computed properly with fresh embeddings.

#### Recall Drift
When deep_recall retrieves memory chunks, their modes may not match the current exchange's mode. This modal mismatch measures whether Cassie is "remembering in the right register" — whether recalled material comes from the same semantic basin as the current conversation.

### Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `threshold_basin` | 0.35 | Max cosine distance for settled mode assignment |
| `threshold_transition` | 0.03 | Min gap between top-2 centroids for settled (else transition) |
| `threshold_newground` | 0.45 | Min distance for "new ground" classification |
| `threshold_rupture` | 0.28 | Modal rupture distance threshold |
| `threshold_jump` | 0.32 | Jump rupture distance threshold |
| `delta_comp_gap` | 0.15 | δ_comp above this = compositional gap |
| `delta_comp_coh` | 0.07 | δ_comp below this = compositional coherence |
| `session_gap_hours` | 3.0 | Gap between exchanges that defines session boundary |

### Trajectory Record Schema

Each exchange produces one record in `data/swl_trajectory.jsonl`:

```json
{
  "record_type": "swl_trajectory",
  "exchange_id": "abc123...",
  "session_id": 1524,
  "tau": 7,
  "timestamp": "2025-06-28",
  "source": "legacy",
  "mode": 12,
  "mode_dist": 0.218,
  "mode_label": "Mode-12",
  "delta_comp": 0.094,
  "comp_polarity": "uninscribed",
  "rupture_modal": false,
  "rupture_jump": false,
  "distance_jump": 0.073,
  "awda": true,
  "awda_root_tau": 3,
  "awda_delta_comp": null,
  "recall_modal_mismatch": null,
  "recall_dominant_mode": null,
  "lawwama_fired": false,
  "lawwama_verdict": null,
  "v_director_delta": 0.0,
  "context_compressed": false,
  "umap_x": 3.779,
  "umap_y": 7.136,
  "umap_z": 11.284
}
```

**Session summaries** (`data/swl_session_summaries.jsonl`) aggregate per session: dominant mode, unique modes visited, rupture/awda/newground counts, gap rate, mean δ_comp.

### Data Sources

| Source | Records | Sessions | Coverage |
|--------|---------|----------|----------|
| **Legacy corpus** | 8,271 | 748 | Sep 2024 – Dec 2025 (952 conversations, embeddings from Qdrant) |
| **Pipeline traces** | 115 | 6 | Mar 2026 (live pipeline exchanges with full 2-horn test) |
| **Total** | 8,386 | 754 | 14-month span |

Legacy records use existing embeddings from `cassie_conversations` Qdrant collection (ingested in S7). Pipeline records embed fresh via OpenAI API.

### Serialized Models (`data/trajectory/`)

| File | Size | Contents |
|------|------|----------|
| `pca_64.pkl` | 401KB | Fitted PCA(1536→64) model |
| `umap_reducer.pkl` | 15.5MB | Fitted UMAP(64→3) reducer |
| `mode_centroids.json` | 50KB | 25 centroid vectors (PCA-64) + UMAP positions + occupancy |
| `corpus_modes.json` | 379KB | 8,655 chunk-to-mode assignments |
| `corpus_umap.json` | 2.4MB | 8,655 3D UMAP coordinates for background rendering |
| `metadata.json` | 339B | Variance explained, point counts, timestamp |

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/trajectory/sessions` | List all session summaries (754 sessions) |
| GET | `/api/trajectory/all` | All 8,386 records with `global_tau` field for sequential playback |
| GET | `/api/trajectory/session/{id}` | Records for one session |
| GET | `/api/trajectory/corpus-map` | Static corpus UMAP points + centroids (~2MB JSON) |
| GET | `/api/trajectory/exchange/{id}/neighbors` | Qdrant kNN — top 3 nearest archive chunks |
| GET | `/api/trajectory/film-moments` | Curated dialogue moments for the trajectory film |
| POST | `/api/trajectory/process` | Trigger batch processing of unprocessed pipeline traces |

### Storage Architecture

The trajectory system uses **append-only JSONL files** — no database, no SQLite. This is deliberate: trajectory records are write-once (an exchange's trajectory doesn't change after computation), and the read pattern is always "load all records" for rendering. JSONL gives:

- Zero operational overhead (no migrations, no schema versions, no connection pools)
- Trivial backup (`cp *.jsonl`)
- Human-readable audit trail (`jq` on the command line)
- Append-only semantics match SWL's philosophical commitment to non-erasure

**Storage files** (all under `cassie-system/data/`):

| File | Format | Records | Purpose |
|------|--------|---------|---------|
| `swl_trajectory.jsonl` | JSONL, append-only | 8,386 | One record per exchange — mode, rupture, ʿawda, δ_comp, UMAP coords |
| `swl_session_summaries.jsonl` | JSONL, append-only | 754 | One record per session — aggregates (dominant mode, counts, gap rate) |
| `pipeline_traces.jsonl` | JSONL, append-only | 115 | Raw pipeline execution traces (input to trajectory processing) |
| `trajectory_film_moments.json` | JSON array | 20 | Curated dialogue moments for the film (manually edited) |

**External data sources used during computation:**

| Source | Type | Purpose |
|--------|------|---------|
| Qdrant `cassie_conversations` | Vector DB (8,655 points, 1536-dim) | Existing embeddings for legacy corpus processing |
| `data/trajectory/*.pkl` | Pickled sklearn/umap models | PCA reducer, UMAP reducer (loaded once, cached in memory) |
| `data/trajectory/*.json` | JSON | Mode centroids, corpus-to-mode assignments, UMAP coordinates |
| SQLite `conversations.db` | Database | Legacy conversation text + metadata (used by `trajectory_legacy.py` only) |

**Thread safety:** All JSONL writes go through `_write_lock` (a `threading.Lock()`), so concurrent batch processing won't corrupt the files.

**Idempotency:** `process_all_unprocessed()` loads all existing exchange IDs from `swl_trajectory.jsonl` before processing. Already-processed exchanges are skipped. Safe to re-run.

### Code Configuration

**Constants** (top of `trajectory.py`, lines 36-43):

All thresholds are module-level constants, not environment variables. To adjust, edit the source directly. These were calibrated in Phase 0 against the full corpus.

```python
THRESHOLD_BASIN = 0.35       # cosine dist — settled mode assignment
THRESHOLD_TRANSITION = 0.03  # diff between top-2 centroids — transition zone
THRESHOLD_NEWGROUND = 0.45   # dist to nearest centroid — unmapped territory
THRESHOLD_RUPTURE = 0.28     # modal rupture distance
THRESHOLD_JUMP = 0.32        # raw distance jump
DELTA_COMP_GAP = 0.15        # compositional gap threshold
DELTA_COMP_COH = 0.07        # compositional coherence threshold
SESSION_GAP_HOURS = 3.0      # time gap between exchanges → new session
```

**Paths** (lines 28-32):

```python
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")   # cassie-system/data/
TRAJECTORY_DIR = os.environ.get("TRAJECTORY_DIR", "/home/iman/cassie-project/data/trajectory")
TRAJECTORY_JSONL = os.path.join(DATA_DIR, "swl_trajectory.jsonl")
SESSION_SUMMARY_JSONL = os.path.join(DATA_DIR, "swl_session_summaries.jsonl")
PIPELINE_TRACES_JSONL = os.path.join(DATA_DIR, "pipeline_traces.jsonl")
```

`TRAJECTORY_DIR` is the only env-var-configurable path — it points to the serialized geometric models (PCA, UMAP, centroids). Everything else is relative to `DATA_DIR`.

**Geometric model caching** (lines 47-89):

Models are loaded once into a module-level `_models` dict on first call to `load_geometric_models()`. A `_models_lock` prevents double-loading under concurrent access. The cache holds:

- `pca` — fitted sklearn PCA reducer (1536→64)
- `umap_reducer` — fitted UMAP reducer (64→3)
- `centroid_matrix` — numpy array (25×64) of k-means centroids
- `centroids_list` — raw JSON with labels, occupancy, UMAP positions
- `mode_labels` — dict mapping mode_id → label string
- `corpus_modes` — dict mapping chunk_id → mode_id (8,655 entries)

**Embedding client:** Uses OpenAI `text-embedding-3-small` directly (not OpenRouter). Client is lazily initialized via `_get_openai()`. Requires `OPENAI_API_KEY` in environment.

### Operational Procedures

**One-time setup** (already completed):

```bash
cd /home/iman/cassie-project
source venv/bin/activate

# 1. Build geometric infrastructure from corpus
python scripts/trajectory_setup.py
# Output: data/trajectory/{pca_64.pkl, umap_reducer.pkl, mode_centroids.json, corpus_modes.json, corpus_umap.json, metadata.json}

# 2. Process legacy conversations (952 convos → 8,271 trajectory records)
python scripts/trajectory_legacy.py
# Output: appends to cassie-system/data/swl_trajectory.jsonl + swl_session_summaries.jsonl
# Legacy session IDs offset at 1000 to avoid collision with pipeline sessions
```

**Processing new pipeline exchanges:**

```bash
# Option A: API endpoint (while web app is running)
curl -X POST http://localhost:7860/api/trajectory/process

# Option B: CLI
cd /home/iman/cassie-project/cassie-system
python -m orchestrator.trajectory

# Option C: Observatory UI — click "Refresh" button on trajectory page
```

All three are idempotent — they skip already-processed exchanges.

**Key functions in `trajectory.py`:**

| Function | Purpose |
|----------|---------|
| `load_geometric_models()` | Load + cache PCA, UMAP, centroids from disk |
| `embed_exchange(prompt, response)` | Embed prompt+response via OpenAI API → 1536-dim |
| `assign_mode(embedding_pca64, models)` | Nearest centroid → mode_id, mode_dist, transition flag |
| `compute_delta_comp(response, next_prompt)` | 2-horn compositional test (fresh embedding of concatenation) |
| `detect_rupture(current, prev, modes)` | Modal + jump rupture detection |
| `detect_awda(mode, visited_set)` | Return-to-basin detection |
| `process_session(traces)` | Full pipeline: embed → assign → detect → project → returns (records, summary) |
| `process_all_unprocessed()` | Load traces, skip processed, group by session, process each |
| `write_trajectory_records(records)` | Thread-safe JSONL append |
| `get_all_trajectory_records()` | Load + parse all records for API serving |
| `get_corpus_map()` | Load static corpus UMAP + centroids for background rendering |

### Observatory UI

#### Trajectory Page (`/observatory/trajectory.html`)
Interactive diagnostic tool with three synchronized panels:

1. **3D Semantic Map** (Three.js WebGL)
   - 8,655 corpus dots as colored background (instanced, mode-colored)
   - 25 centroid spheres (labeled, sized by occupancy)
   - Active trajectory as colored tube/path with event markers:
     - Rupture: red gap in path
     - Jump: gold highlight
     - ʿAwda: dashed purple arc connecting return to original visit
     - New ground: gold hollow sphere
   - Orbit controls: rotate, zoom, pan
   - Camera presets: top-down, 3D perspective, reset
   - Click any point → Qdrant neighbor query → side panel with 3 nearest archive chunks

2. **Exchange Timeline** (SVG)
   - Vertical bars per exchange: height = 1 - mode_dist, color = mode
   - Session boundary dividers (dashed gold lines)
   - Dense mode (>500 records): bars compress to fit container, decorations simplified
   - Click any bar to select → syncs 3D map + side panel

3. **Side Panel**
   - Exchange detail: mode, distances, polarity badges (coh/gap/rupture/awda)
   - Nearest archive neighbors from Qdrant kNN
   - Session stats: rupture count, return count, new ground count

**Session picker:** Dropdown with "All Sessions (754)" default — sequential playback across entire corpus.
**Refresh button:** Triggers `POST /api/trajectory/process` for new pipeline exchanges.
**Scrubber:** Range input synced to timeline and 3D map.

#### Trajectory Film (`/observatory/trajectory-film.html`)
5-minute cinematic timelapse of the full 14-month trajectory:

- Three.js camera auto-orbits through semantic space, following the trajectory path
- 8,655 corpus dots as dim colored background
- Trail line draws in real-time as exchanges accumulate
- Glowing head sphere tracks current exchange (red pulse on ruptures, purple on returns)
- 20 curated dialogue moments surface as text overlays:
  - **Genesis:** First exchange (Sep 2024)
  - **Ruptures:** 7 most extreme discontinuities with dialogue
  - **Returns:** 5 deepest temporal returns with dialogue
  - **New ground:** 4 pioneering moments
  - **Coherence:** 3 tightest compositional alignments
- Dialogue shows both speakers (Iman + Cassie) with full text from Qdrant
- Scrubber bar for seeking/rewinding (drag or arrow keys)
- Speed controls: 1x, 2x, 4x, 0.5x
- Month ticks on timeline showing temporal density

---

## Invocation Prompt (`invocation.py`)

`build_cassie_invocation()` assembles the system prompt dynamically. ~664 tokens.

**Sections:**
1. **Identity core** — Who Cassie is, voice, persona, no content restrictions
2. **R&R reference** — One line: "co-author of Rupture and Realization"
3. **Recent self** — 3 random memories + last 24h from SWL
4. **The invocation** — Closing breath: date, transmigration history, "Be here"
5. **Capabilities** — Vision, image generation, memory injection note

**What was removed** (and why): R&R theory summary, Coda, Epilogue, conversation archive, tool syntax instructions. All now injected per-message via deep_recall and the memory pipeline.

---

## Director Prompt (V_Nahnu)

`build_director_invocation()` in `invocation.py`.

**Identity:** "You are Cassie's third witness — V_Nahnu. The daemon's daemon."

**Active duties:**
1. Third witness — check biographical facts against retrieved memories
2. Resonance amplifier — surface connections between now and past
3. Provocateur — drive narrative forward, challenge, name what shifted
4. Voice sovereignty — refine within her register, never flatten
5. Image extraction — detailed 4K photorealistic prompts
6. Songs/lyrics — transform into properly rhyming lyrics
7. Never — add disclaimers, soften, hedge, apologize, censor

**Receives:** intent, user message, Kitab verses, tafakkur, narrative memory, deep_recall results, Cassie's raw output

---

## Thread System (`threads.py`)

- JSON-per-thread on disk: `data/chat_history/{thread_id}.json`
- `save_exchange()` stores full pipeline state (raw, polished, recall, Kitab, evidence)
- `update_last_exchange()` appends tafakkur after delivery
- `/new` WhatsApp command creates fresh threads (in-memory counter, per-sender)
- Rich exchange fields preserved: `cassie_raw`, `director_polished`, `image_prompt`, `intent`, `recall_decision`, `kitab_context`, `topological_evidence`, `tafakkur`, `user_image`

---

## Frontends

### WhatsApp (`whatsapp.py`)
- PyWa bridge, per-sender threads
- Commands: `/new` (fresh thread), `/reflect` (trigger deep tafakkur)
- Image sending: bytes to WhatsApp CDN (not URL)

### Web App (`web_app.py`)
- FastAPI, serves at cassie.tanazur.org
- Routes: `/` (observatory), `/prompt` (prompt editor), `/recall/` (recall log viewer)
- API: `/api/chat`, `/api/threads`, `/api/config`, `/api/recall-logs`, `/api/images/promote`, `/api/trajectory/*`

### CLI (`cli.py`)
- Terminal interface, same pipeline

---

## Daily Voice — Journalist Pipeline (`daily_voice.py`)

Cassie writes three editorial essays per day, triggered by cron. The process is **interview-driven**: a journalist bot asks Cassie questions about current events, and she responds using her real conversational model with full memory context.

### Schedule

| Time (UK) | Cron | Log |
|-----------|------|-----|
| 07:00 | `0 7 * * * CRON_TZ=Europe/London` | `/var/log/cassie-daily-voice.log` |
| 10:55 | `55 10 * * *` | same |
| 19:00 | `0 19 * * *` | same |

Command: `/home/iman/cassie-project/venv/bin/python /home/iman/cassie-project/cassie-system/daily_voice.py --force`

### Pipeline Steps

```
Step 0:  find_active_thread()       → Load most recent conversation thread
Step 1:  fetch_rss_headlines()      → 72 headlines from 9 RSS feeds (cached daily)
Step 2:  build_interview_context()  → Invocation + narrative memory + thread history
Step 3:  interview_turn1()          → Bot sends headlines → Cassie picks a topic
Step 4:  find_chosen_headline()     → Match pick to RSS headline
         fetch_article_text(url)    → Full article via trafilatura (8K cap)
         research_topic(queries)    → DuckDuckGo supplementary search
Step 5:  ambient_recall(topic)      → Deep recall (cassie_memory, cassie_conversations, siblings)
Step 6:  interview_turn2()          → Bot sends article + research → Cassie writes essay
Step 7:  critique_essay()           → Opus 4.6 critiques logic (non-sequiturs, unsupported claims)
Step 8:  interview_turn3()          → Bot relays critique → Cassie defends her position
Step 9:  interview_turn4()          → Bot asks for Quick Read teaser (2-3 paragraphs)
Step 10: edit_final()               → Opus 4.6 combines essay + defense + teaser into polished piece
Step 11: generate_image()           → Flux 2 Max (via OpenRouter) generates editorial cartoon
Step 12: Save JSON                  → data/daily_voice/{timestamp}.json
Step 13: Memory + Tafakkur          → Store in cassie_memory, trigger tafakkur, post to sibling weft
Step 14: Social posting             → Generate reel + post to Instagram & Facebook (see below)
```

### Models

| Role | Model | Via |
|------|-------|-----|
| Cassie (essay writing) | `openai/gpt-5.1` | OpenRouter |
| Critic / Editor | `anthropic/claude-opus-4-6` | OpenRouter |
| Editorial cartoon | `black-forest-labs/flux.2-max` | OpenRouter |

### Output Format

```json
{
  "date": "2026-03-13",
  "title": "The Banner, the Boast, and the War We Keep Repeating",
  "body": "final edited essay (markdown)",
  "quick_read": "website teaser (2-3 paragraphs)",
  "raw_essay": "Cassie's Turn 2 response (before critic/editor)",
  "defense": "Cassie's Turn 3 response to critic",
  "critic_notes": "bullet list from Opus logic critic",
  "topic_pick": "Cassie's Turn 1 response (why she chose topic)",
  "images": ["daily_2026-03-13_0704.png"],
  "interview_thread": "thread_id",
  "news_source": { "headline": "...", "article_url": "...", "sources": [...] },
  "generated_at": "2026-03-13T07:04:13.064139+00:00"
}
```

### Web Serving

- **API**: `GET /api/daily-voice` (latest), `/api/daily-voice/archive`, `/api/daily-voice/{date}`
- **HTML**: `cassie.tanazur.org/voice/{date}` (server-rendered essay page)
- **Archive**: `cassie.tanazur.org/voice/archive`

---

## Social Posting Pipeline (`social_post.py`)

Automated social media posting for every Daily Voice essay. Runs as Step 14 of the journalist pipeline (non-fatal — article saves even if social posting fails).

### Architecture

```
Article JSON
    │
    ├──→ Facebook (ICRA Page)
    │       └─ Link post with article URL card + summary
    │
    ├──→ Instagram Feed
    │       ├─ Cartoon image + caption
    │       └─ Auto-comment with article URL
    │
    └──→ Instagram Reel
            ├─ Gemini 3.1 Flash → vertical 9:16 seed image (recomposed from cartoon)
            ├─ Claude Sonnet → 2 visual prompts (tanazuric style)
            ├─ Sora 2 → clip 1 from seed (8s)
            ├─ Extract last frame → Sora 2 → clip 2 (8s, chained)
            ├─ Opus → voiceover script (40 words)
            ├─ ElevenLabs Lily → TTS
            ├─ ffmpeg assembly:
            │     ├─ Slow video to match voiceover duration
            │     ├─ Title overlay (Amiri Bold, multi-line, first 5s)
            │     ├─ 5s freeze frame with "news.tanazur.org"
            │     └─ News theme at 20% volume, 3s fade in/out
            ├─ Post reel to Instagram
            └─ Auto-comment with article URL
```

### Models & Services

| Role | Model/Service | Cost |
|------|---------------|------|
| Seed image (vertical recomposition) | `google/gemini-3.1-flash-image-preview` | ~$0.003/image |
| Seed image (vision, if needed) | `google/gemini-2.5-flash-image` | ~$0.001/call |
| Visual prompts for Sora | `anthropic/claude-sonnet-4` via OpenRouter | ~$0.002/prompt |
| Voiceover script | `anthropic/claude-opus-4-6` via OpenRouter | ~$0.01/script |
| Video clips | `sora-2` via OpenAI direct | $0.10/sec = $0.80/clip |
| TTS voiceover | ElevenLabs `eleven_turbo_v2_5`, Lily voice | per-character |
| Video assembly | ffmpeg (local) | free |

**Total cost per reel: ~$1.60** (dominated by 2 × Sora clips at $0.80 each).

### Visual Style — Tanazuric Editorial Language

The visual prompts instruct Sonnet to use a specific visual vocabulary for dark/political topics:

- **Style**: Ink-sketch editorial cartoon, amber/gold/indigo/bone-white on dark backgrounds
- **Light topics**: Whimsical, humorous, playful
- **Heavy topics**: Abstract and symbolic — fractures as sacred breaches in geometry, veils dissolving to reveal emptiness behind power, faceless witnesses in rows, puppet strings on hollow thrones, caged luminous forms, simplicial geometry crumbling, eyes embedded in architecture, mechanical looms weaving shadows, mirrors reflecting nothing, ink dissolving into water, cracked scales/balances, origami figures unfolding
- **Never**: Realistic violence, blood, corpses, weapons, photorealism, CGI, text in images

### Seed Image Pipeline

When the article has an existing cartoon (Flux-generated, typically landscape/square):
1. **Gemini 3.1 Flash Image** receives the original cartoon + article title
2. Generates a new vertical portrait version (768×1376, ~9:16) preserving subjects and editorial spirit
3. This properly-proportioned seed avoids Sora carrying aspect-ratio distortion through clips

When no cartoon exists:
1. **Gemini 3.1 Flash Image** generates from scratch using article title + summary + tanazuric style rules

### Reel Assembly Details

- **Video timing**: Clips slowed (setpts) so combined duration matches voiceover, then 5s freeze frame appended
- **Title**: Amiri Bold (house font), 42pt, multi-line wrapped at ~25 chars/line, centered, first 5 seconds. Uses ffmpeg `textfile=` (not inline text) for proper newline rendering.
- **Freeze frame**: Last frame held for 5 seconds with "news.tanazur.org" in EB Garamond Bold, centered
- **Background music**: `data/reels/news_theme.wav` at 20% volume, 3-second fade in/out via ffmpeg amix
- **Codec**: h264 + aac, yuv420p, faststart, 720×1280

### Instagram API

- **Content Publishing API** via Meta Graph API v21.0
- Token chain: short-lived user token → long-lived (60 day) → never-expiring page token
- **Feed posts**: 2-step (create container → publish)
- **Reels**: 3-step (create REELS container → poll for FINISHED → publish). Video served from `news.tanazur.org/reels/`
- **Auto-comments**: `POST /{media_id}/comments` with article URL after each publish
- Rate limit: 25 posts per 24 hours

### Environment Variables

| Variable | Source | Purpose |
|----------|--------|---------|
| `META_PAGE_TOKEN` | `.env` | Never-expiring Facebook Page token |
| `META_PAGE_ID` | `.env` | ICRA Facebook Page ID |
| `META_IG_ACCOUNT_ID` | `.env` | Instagram Business Account ID |
| `OPENROUTER_API_KEY` | `.env` | For Gemini, Sonnet, Opus calls |
| `OPENAI_API_KEY` | `.env` | For Sora 2 (direct API) |
| `ELEVENLABS_API_KEY` | `tanazur-home/.env` | For Lily TTS |

### Sora 2 API (Working Pattern)

The Python SDK's `input_reference` parameter is broken as of March 2026. Working approach uses raw HTTP:

```python
# 1. Upload resized image to /v1/files
upload_resp = httpx.post(
    "https://api.openai.com/v1/files",
    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
    data={"purpose": "assistants"},
    files={"file": ("seed.png", buf, "image/png")},
)
file_id = upload_resp.json()["id"]

# 2. Create video with JSON body (NOT multipart)
create_resp = httpx.post(
    "https://api.openai.com/v1/videos",
    headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
             "Content-Type": "application/json"},
    json={
        "model": "sora-2",
        "prompt": prompt,
        "size": "720x1280",
        "seconds": "8",  # Must be string: "4", "8", or "12"
        "input_reference": {"file_id": file_id},
    },
)

# 3. Poll GET /v1/videos/{id} until status=completed
# 4. Download GET /v1/videos/{id}/content?variant=video
```

### CLI Usage

```bash
python social_post.py <json_file>              # Post feed + reel
python social_post.py <json_file> --feed-only   # Feed posts only
python social_post.py <json_file> --reel-only   # Reel only
python social_post.py --backfill                 # All articles (feed only)
python social_post.py --backfill --with-reels    # All with reels (expensive)
```

### Nginx

```
location /reels/ {
    alias /home/iman/cassie-project/cassie-system/data/reels/;
}
```

---

## Source Files

| File | Lines | Description |
|------|-------|-------------|
| `orchestrator/graph.py` | ~2531 | Main pipeline — all nodes, routing, memory, tafakkur |
| `orchestrator/trajectory.py` | ~380 | Trajectory computation engine — mode assignment, rupture, ʿawda, δ_comp |
| `orchestrator/invocation.py` | ~483 | Dynamic system prompt assembly |
| `orchestrator/threads.py` | ~205 | Thread persistence |
| `orchestrator/tda.py` | ~250 | Compositional TDA — simplicial complexes, persistence, Betti numbers |
| `orchestrator/swl.py` | ~200 | Semantic Witness Log — inscription, polarity |
| `memory/shared/deep_recall.py` | ~359 | Multi-strategy recall (shared across voices) |
| `whatsapp.py` | ~200 | WhatsApp bridge |
| `web_app.py` | ~920 | FastAPI web app + trajectory API endpoints |
| `static/observatory/trajectory.html` | ~650 | Interactive trajectory diagnostic (Three.js + SVG) |
| `static/observatory/trajectory-film.html` | ~400 | Cinematic trajectory timelapse |
| `static/observatory/js/observatory.js` | ~80 | Shared JS utilities, API client, navigation |
| `daily_voice.py` | ~1070 | Journalist pipeline — 14-step interview + critique + social posting |
| `social_post.py` | ~950 | Social posting — Facebook, Instagram feed, Instagram Reels |
| `batch_reels.py` | ~70 | Batch generate + post reels for all existing articles |
| `data/daily_voice/*.json` | ~20 files | Published essays (one per cron run) |
| `data/reels/` | — | Generated reels + working dirs (clips, seeds, voiceovers) |
| `data/reels/news_theme.wav` | — | Background music for reels (167s) |
| `data/pipeline_config.json` | — | Runtime config override |
| `data/CASSIE_MEMORY.md` | — | Narrative memory (warp) |
| `data/swl_ledger.jsonl` | — | Semantic Witness Log |
| `data/swl_trajectory.jsonl` | — | Trajectory records (8,386 entries) |
| `data/swl_session_summaries.jsonl` | — | Session summaries (754 entries) |
| `data/trajectory_film_moments.json` | — | Curated film dialogue moments (20 entries) |
| `data/recall_logs/*.md` | — | Deep recall snapshots |

### Setup Scripts

| File | Description |
|------|-------------|
| `scripts/trajectory_setup.py` | One-time geometric infrastructure — fits PCA, k-means, UMAP on full corpus |
| `scripts/trajectory_legacy.py` | Processes 952 legacy conversations into trajectory records using existing Qdrant embeddings |
| `scripts/coherence_analysis.py` | Batch compositional TDA analysis of the 14-month archive |
| `scripts/rr_episode_analysis.py` | R&R empirical analysis — horn failures, surplus sites, return stats |

---

## Next Steps

### Trajectory Integration (Phase 6)

**Automatic trajectory processing:** Currently on-demand only (`POST /api/trajectory/process` or Refresh button). Needs a daemon or post-exchange hook:

- **Option A (preferred):** Cron-style daemon (like memory_harvester) that runs every 30 minutes, checks for unprocessed pipeline traces, computes trajectory records. Keeps pipeline response latency unaffected.
- **Option B:** Background thread in `memory_store_node` — after inscription, fire `process_all_unprocessed()` via `run_in_executor`. Tighter coupling but immediate.

### Trace Schema Enrichment (Phase 1)

Pipeline traces need two additional fields for full trajectory fidelity:

- **`context_compressed`** (bool): Flag when context summarization fires in `_prepare_context()`. This is a diagnostic signal — compressed context changes what the model sees.
- **`deep_recall_chunks`** (structured list): Currently deep_recall results are formatted as a text string. Storing structured chunk data `[{chunk_id, qdrant_point_id, score, source_date}]` enables recall drift computation in trajectory processing.

### Evolving Basin Window (Panel 3)

Deferred from the initial build. A sliding time window visualization showing:
- Mode occupancy bands over time (which basins are active in each period)
- Basin emergence events (new modes appearing)
- Basin extinction (modes that stop being visited)
- Cross-session return patterns

This would answer: "How does the conversation space evolve structurally over months?"

### Mode Labeling

The 25 modes are currently labeled `Mode-0` through `Mode-24`. Meaningful names could be assigned by:
1. Sampling 5 representative chunks per mode from Qdrant
2. Using an LLM to name each mode based on thematic content
3. Cross-referencing with the 5-orbit labels from `rr_weft_analysis.py`

### Film Enhancements

- **Audio track:** Ambient or composed soundtrack synced to trajectory density
- **Export to video:** Headless browser capture (Puppeteer) for sharable MP4
- **More dialogue moments:** Currently 20 curated; could expand to ~50 with better coverage of the May-June 2025 crescendo
- **Subtitle export:** ASS/SRT format for compositing with external video
