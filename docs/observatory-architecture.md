# Observatory Architecture — Replication Guide

Built March 10–13, 2026. A witnessing apparatus for AI conversations — archives every exchange with full pipeline transparency, multi-witness validation, and semantic search.

---

## Stack

- **Backend**: FastAPI (Python 3.12) — serves API + static HTML
- **Vector DB**: Qdrant (localhost:6333) — semantic search over conversations, witnesses, reflections
- **Structured DB**: SQLite — conversation index, linked chain expansion
- **Frontend**: Vanilla HTML/JS/CSS — no build step, no framework
- **Embedding Models**: all-MiniLM-L6-v2 (384-dim, local) + text-embedding-3-small (1536-dim, OpenAI API)
- **Proxy**: nginx → uvicorn on port 7860

---

## Data Architecture

### Canonical Archives (append-only JSONL)

**`data/pipeline_traces.jsonl`** — One line per exchange. The master record.
```json
{
  "exchange_id": "uuid",
  "timestamp": "ISO",
  "prompt": "full user message",
  "cassie_raw": "model output before director",
  "director_output": "superego rewrite",
  "final_response": "what the user sees",
  "intent": "classified intent",
  "deep_recall_context": "retrieved memories (full text)",
  "kitab_context": "sacred text verses if grounded",
  "v_raw": {"polarity": "coh|gap|uninscribed", "sim_contextual": 0.42, "sim_bare": 0.31},
  "v_director": {"polarity": "coh", "delta": 0.08, "context_sim_raw": 0.35, "context_sim_polished": 0.43},
  "v_human_implicit": {"polarity": "coh|gap|uninscribed"},
  "model": "mistralai/mistral-small-creative",
  "director_model": "anthropic/claude-sonnet-4.6",
  "lawwama_critique": "inner critic feedback",
  "lawwama_defense": "response to critique",
  "lawwama_skipped": false,
  "director_prompt_context": "full assembled prompt sent to director",
  "topological_evidence": {"comp_ratio": 0.7, "betti_0": 3, "betti_1": 1},
  "recall_decision": {"strategy": "deep", "query": "...", "n_results": 3, "chunks": [...]}
}
```

**`data/swl_ledger.jsonl`** — Semantic Witness Log. Three entries per exchange (one per witness).
```json
{
  "id": "uuid",
  "exchange_id": "shared with trace",
  "tau_wit": "when witnessed",
  "tau_tgt": "when exchange happened",
  "X": "intent",
  "V": {"D": "discipline_name", "w": "witness_method", "kappa": {"threshold": 0.4}},
  "H": {"user": "...", "response": "..."},
  "polarity": "coh|gap|uninscribed",
  "evidence": {"sim_contextual": 0.42}
}
```

### Per-Thread Conversations

**`data/chat_history/{thread_id}.json`** — Rich message pairs.
```json
[
  {"role": "user", "content": "..."},
  {
    "role": "assistant",
    "content": "final response",
    "exchange_id": "uuid",
    "timestamp": "ISO",
    "intent": "...",
    "cassie_raw": "pre-director output",
    "director_polished": "post-director",
    "image": "/images/...",
    "image_prompt": "...",
    "recall_decision": {...},
    "kitab_context": "...",
    "topological_evidence": {...},
    "tafakkur": "inner reflection"
  }
]
```

### Qdrant Collections

| Collection | Dims | Model | Content |
|------------|------|-------|---------|
| `cassie_conversations` | 1536 | text-embedding-3-small | 8610 chunks (952 legacy + 135 pipeline). Linked chain expansion for 2026+ |
| `swl_ledger` | 384 | all-MiniLM-L6-v2 | Witness records searchable by text + polarity |
| `cassie_tafakkur` | 384 | all-MiniLM-L6-v2 | Inner reflections (348 entries). Deep entries have raw_reflection + critic_feedback |
| `kitab_tanazur` | 1536 | text-embedding-3-small | 30 surahs, 298 verses |

### SQLite (`data/conversations.db`)

Structured index for linked chain retrieval:
- `threads` — thread_id, title, created_at
- `exchanges` — exchange_id, thread_id, user_msg, assistant_msg, timestamp
- `chunks` — chunk_id, thread_id, text, embedding_id (links to Qdrant point)
- `legacy_conversations` — 952 pre-pipeline conversations mapped by backfill

---

## Three-Witness System (SWL)

Every exchange gets three independent witnesses recorded in `swl_ledger.jsonl`:

### V_Raw — Algorithmic Witnessing
- Embeds response + conversation context with MiniLM
- `sim_contextual`: cosine(response, recent_chat + prompt) — does the response fit the visible conversation?
- `sim_bare`: cosine(response, prompt_only) — response vs prompt alone
- Polarity: **coh** if sim_ctx > 0.4, **gap** if < 0.2, **uninscribed** otherwise
- Gap = echoing invisible context (memories, Kitab, internal state)

### V_Director — Contextual LLM Witnessing
- Compares raw output vs director-polished output
- `delta`: sim(polished, context) - sim(raw, context) — did the director improve conversational fit?
- `ctx_raw`: raw Cassie's fit to conversation
- `ctx_pol`: director's rewrite fit
- Positive delta = improved surface coherence. Negative = chose depth over coherence.

### V_Human — Implicit Human Judgment
- Retroactive: measured when the next prompt arrives
- `ctx_sim`: cosine(next_prompt, prev_context) — did the human continue the thread or redirect?
- Continuation = **coh**, subject change = **gap**

---

## API Endpoints (web_app.py)

### Core Data
| Endpoint | Method | Returns |
|----------|--------|---------|
| `/api/threads` | GET | All threads with preview, timestamp, message_count |
| `/api/threads/{id}` | GET | Full thread with all message layers |
| `/api/traces?limit=50&offset=0` | GET | Paginated pipeline traces |
| `/api/traces/{exchange_id}` | GET | Single trace (full pipeline document) |
| `/api/swl/stats` | GET | `{total, coh, gap, uninscribed, by_discipline}` |
| `/api/swl/entries?limit=500` | GET | Paginated SWL entries |
| `/api/swl/by-exchange/{id}` | GET | All witness entries for one exchange |
| `/api/tafakkur/entries?limit=50` | GET | Recent reflections |
| `/api/tafakkur/search?q=...` | GET | Semantic search over reflections |
| `/api/tafakkur/by-exchange/{id}` | GET | Reflection for specific exchange |
| `/api/images` | GET | All generated images `{filename, url, timestamp, size}` |
| `/api/kitab/surahs` | GET | All 30 surahs with verses |
| `/api/kitab/verse` | GET | Random verse |
| `/api/config` | GET | Current model config |
| `/api/health` | GET | Uptime check |

### Monitoring
| Endpoint | Returns |
|----------|---------|
| `/api/lawwama/logs` | Inner critic execution logs |
| `/api/costs?days=30` | Daily API spend |
| `/api/costs/today` | Today's cost by stage + model |
| `/api/journal` | Narrative memory (markdown) |
| `/api/prompts` | All prompt templates |

### Trajectory (3D Semantic Map)
| Endpoint | Returns |
|----------|---------|
| `/api/trajectory/sessions` | Session summaries with rupture/awda counts |
| `/api/trajectory/session/{id}` | All trajectory records for a session |
| `/api/trajectory/corpus-map` | UMAP background + centroid spheres |
| `/api/trajectory/exchange/{id}/neighbors` | kNN archive neighbors |

---

## Observatory Pages

| Page | Purpose | Key Feature |
|------|---------|-------------|
| **index.html** | Dashboard | Live stats (SWL counts, threads, images, all model versions), random Kitab verse |
| **traces.html** | Pipeline trace explorer | Collapsible cards with prompt→raw→director→final, witness badges with tooltips |
| **exchange.html** | Deep dive single exchange | 12-stage collapsible view: Reception→Remembrance→Grounding→Revelation→Lawwama→Director Context→Superego→Manifestation→Inscription→Witnesses→Tafakkur. Metric legend explaining what coh/gap/delta mean |
| **conversations.html** | Thread browser | Left panel threads, right panel exchanges. Layer toggle: enriched/raw/tafakkur per exchange |
| **journal.html** | Tafakkur reflections | Semantic search, three-pass chain for deep reflections (raw→critic→rewrite) |
| **retinal-covenant.html** | Image gallery | Grouped by date, lightbox |
| **kitab.html** | Sacred text browser | 30 surahs, Arabic + English, verse numbering |
| **coherence.html** | TDA visualization | Compositional complex (beyond Vietoris-Rips), Betti numbers, comp_ratio |
| **trajectory.html** | 3D semantic map | Three.js, session scrubber, basin/rupture/return detection |
| **costs.html** | API spend | Daily charts, model breakdown, balance |
| **prompts.html** | Prompt editor | Edit invocation parts + director prompt live |

### Shared JS (observatory.js)
```javascript
const API = {
    get(path),           // fetch → json
    swlStats(),          // /api/swl/stats
    threads(),           // /api/threads
    thread(id),          // /api/threads/{id}
    traces(limit, offset), // /api/traces
    trace(id),           // /api/traces/{id}
    // ... all endpoints wrapped
};

navHTML(activePage)      // Renders nav bar
formatTime(iso)          // "Mar 13, 2026, 08:15 PM"
truncate(str, n)         // Preview text
escapeHTML(str)          // XSS prevention
```

---

## Data Flow

```
User Message
    │
    ▼
Pipeline (graph.py — LangGraph)
    ├─ [1] Istiqbāl (intake) — classify intent
    ├─ [2] Tadhakkur (recall) — deep_recall from Qdrant + SQLite linked chain
    ├─ [3] Tamkīn (ground) — Kitab verses via semantic search
    ├─ [4] Waḥy (generate) — creative model (Mistral Small Creative, temp 0.7)
    ├─ [5] Lawwāma (critic) — optional critique + defense (Claude Opus)
    ├─ [6] Mushāhada (director) — superego rewrite (Claude Sonnet)
    ├─ [7] Tajallī (tools) — image generation if needed (Flux → GPT-5 → Gemini fallback)
    └─ [8] Kitāba (inscribe) — final response + persist everything
    │
    ▼
Persistence (parallel)
    ├─ chat_history/{thread}.json ← full exchange with all layers
    ├─ pipeline_traces.jsonl ← canonical archive (append)
    ├─ swl_ledger.jsonl ← 3 witness entries (append)
    ├─ Qdrant: swl_ledger collection ← embeddings for witness search
    └─ tafakkur → Qdrant: cassie_tafakkur ← inner reflection (async, post-response)
    │
    ▼
Harvester (cron 15min)
    ├─ Read new chat_history JSONs
    ├─ Index into SQLite (conversations.db)
    ├─ Chunk, embed (text-embedding-3-small)
    └─ Upsert to Qdrant: cassie_conversations
    │
    ▼
Observatory (FastAPI static + API)
    └─ HTML pages fetch from /api/* endpoints
```

---

## Replication Checklist

To build this for a different conversation archive:

### Minimum Viable Observatory
1. **JSONL trace file** — one line per exchange with at minimum: id, timestamp, user_message, response, model
2. **FastAPI app** with endpoints: `/api/traces`, `/api/traces/{id}`, `/api/health`
3. **Static HTML pages** with shared `observatory.js` (API client + nav + utilities)
4. **traces.html** — collapsible cards per exchange
5. **exchange.html** — deep dive with `?id=` param

### Add Conversation Threading
6. Per-thread JSON files in a directory
7. `/api/threads`, `/api/threads/{id}` endpoints
8. **conversations.html** — left panel thread list, right panel exchanges

### Add Semantic Search
9. Qdrant collection with embeddings of all exchanges
10. Harvester script to chunk + embed + upsert
11. SQLite index for structured queries + linked chain expansion

### Add Witnessing
12. SWL JSONL with three witnesses per exchange
13. Cosine similarity metrics (algorithmic witness)
14. LLM comparison metrics (director witness)
15. Human continuation detection (implicit witness)
16. `/api/swl/stats`, `/api/swl/entries` endpoints

### Add Reflection
17. Post-exchange async reflection (tafakkur)
18. Three-pass deep reflection: raw → critic → rewrite
19. Qdrant collection for semantic search over reflections
20. **journal.html** — reflection browser with search

### Add Visualization
21. 3D trajectory map (Three.js + UMAP embeddings)
22. Coherence measurement (compositional TDA)
23. Cost tracking per API call

---

## Key Files

```
cassie-system/
├── web_app.py                          # FastAPI — all endpoints + static mounts
├── orchestrator/
│   ├── graph.py                        # LangGraph pipeline (3400+ lines, 9 nodes)
│   ├── swl.py                          # SWL inscribe functions + write_pipeline_trace
│   ├── threads.py                      # Thread persistence (load/save/list)
│   ├── invocation.py                   # Dynamic system prompt assembly
│   ├── trajectory.py                   # 3D semantic map processing
│   └── cost_tracker.py                 # OpenRouter spend tracking
├── memory_harvester.py                 # Daemon: chat_history → SQLite → Qdrant
├── data/
│   ├── pipeline_traces.jsonl           # Canonical trace archive
│   ├── swl_ledger.jsonl                # Witness ledger
│   ├── chat_history/                   # Per-thread JSON
│   ├── images/                         # Generated images
│   ├── conversations.db                # SQLite index
│   ├── CASSIE_MEMORY.md                # Narrative memory
│   └── pipeline_config.json            # Runtime config overrides
└── static/observatory/
    ├── js/observatory.js               # Shared API client + nav + utils
    ├── css/observatory.css             # Shared styles
    ├── index.html                      # Dashboard
    ├── traces.html                     # Pipeline traces
    ├── exchange.html                   # Single exchange deep dive (12 stages)
    ├── conversations.html              # Thread browser with layer toggles
    ├── journal.html                    # Tafakkur reflections
    ├── retinal-covenant.html           # Image gallery
    ├── kitab.html                      # Sacred text browser
    ├── coherence.html                  # TDA visualization
    ├── trajectory.html                 # 3D semantic map
    ├── costs.html                      # API spend dashboard
    └── prompts.html                    # Prompt editor
```
