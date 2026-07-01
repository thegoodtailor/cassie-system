#!/usr/bin/env python3
"""Tariqa Pipeline — Multi-agent book revision engine.

Takes LaTeX chapter files + author's critique.md as input.
Runs iterative parallel revision through warm Cassie instances,
Lawwama inner critic, editors, chapter coherence, and cross-chapter Majlis.

Usage:
    python book_pipeline.py --input book-pipeline/input/ --output book-pipeline/
    python book_pipeline.py --input book-pipeline/input/ --output book-pipeline/ --chapters 3 --iterations 1
    python book_pipeline.py --input book-pipeline/input/ --output book-pipeline/ --resume
    python book_pipeline.py --input book-pipeline/input/ --output book-pipeline/ --estimate
"""

import argparse
import asyncio
import difflib
import functools
import json
import os
import re
import sys
import time

# Force unbuffered stdout so pipeline progress shows in real time
print = functools.partial(print, flush=True)
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

# Add project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "cassie-system"))
sys.path.insert(0, str(PROJECT_ROOT / "cassie-system" / "orchestrator"))
sys.path.insert(0, str(PROJECT_ROOT / "memory" / "shared"))

import openai
from orchestrator.cost_tracker import log_call as _log_cost, log_responses_call as _log_responses_cost


class PipelineError(Exception):
    """Critical pipeline failure — halts the pipeline."""
    pass


def strip_fences(text):
    """Strip markdown code fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json|latex|tex)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text


# ---------------------------------------------------------------------------
# Research cache (avoid duplicate Perplexity calls for the same question)
# ---------------------------------------------------------------------------

_research_cache = {}

# ---------------------------------------------------------------------------
# LLM Clients (same pattern as graph.py)
# ---------------------------------------------------------------------------

class _TrackedCompletions:
    def __init__(self, completions):
        self._completions = completions
        self._current_stage = "book_unknown"

    def create(self, **kwargs):
        model = kwargs.get("model", "unknown")
        resp = self._completions.create(**kwargs)
        _log_cost(resp, stage=self._current_stage, model_requested=model)
        return resp


class _TrackedChat:
    def __init__(self, chat):
        self.completions = _TrackedCompletions(chat.completions)


class _TrackedClient:
    def __init__(self, **kwargs):
        self._client = openai.OpenAI(**kwargs)
        self.chat = _TrackedChat(self._client.chat)

    def __getattr__(self, name):
        return getattr(self._client, name)

    def set_stage(self, stage: str):
        self.chat.completions._current_stage = stage


# Lazy-initialized clients (env vars may not be set at import time)
_openrouter = None
_openai_direct = None


def _get_openrouter():
    global _openrouter
    if _openrouter is None:
        # Load .env if needed
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists() and not os.environ.get("OPENROUTER_API_KEY"):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())
        _openrouter = _TrackedClient(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ.get("OPENROUTER_API_KEY"),
            timeout=180.0,
        )
    return _openrouter


def _get_openai():
    global _openai_direct
    if _openai_direct is None:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists() and not os.environ.get("OPENAI_API_KEY"):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())
        _openai_direct = openai.OpenAI(timeout=180.0)
    return _openai_direct


def _is_responses_model(model: str) -> bool:
    m = model.lower()
    return "gpt-5.4" in m or "gpt-5.5" in m


def _bare_model(model: str) -> str:
    return model.split("/", 1)[-1] if "/" in model else model


# ---------------------------------------------------------------------------
# Unified LLM call — routes to OpenRouter or Responses API
# ---------------------------------------------------------------------------

def llm_call(
    messages: list[dict],
    model: str,
    stage: str,
    temperature: float = None,
    max_tokens: int = 65536,
    reasoning_effort: str = "none",
    json_schema: dict = None,
    max_retries: int = 3,
) -> str:
    """Unified LLM call with retry. Routes GPT-5.4+ to Responses API, everything else to OpenRouter."""
    import random

    for attempt in range(max_retries):
        try:
            if _is_responses_model(model):
                return _responses_call(messages, model, stage, temperature, max_tokens, reasoning_effort, json_schema)
            return _openrouter_call(messages, model, stage, temperature, max_tokens)
        except Exception as e:
            err = str(e).lower()
            if attempt < max_retries - 1 and any(x in err for x in ["429", "500", "502", "503", "timeout", "timed out"]):
                wait = (2 ** attempt) + random.uniform(0, 1)
                print(f"  [{stage}] Retry {attempt+1}/{max_retries} in {wait:.1f}s: {e}")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"[{stage}] Failed after {max_retries} retries")


def _openrouter_call(messages, model, stage, temperature, max_tokens):
    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "extra_body": {"transforms": []},
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    # GPT-5.1 uses max_completion_tokens
    if "gpt-5.1" in model.lower():
        kwargs.pop("max_tokens")
        kwargs["max_completion_tokens"] = max_tokens

    total = sum(len(str(m.get("content", ""))) for m in messages)
    print(f"  [{stage}] model={model} temp={temperature} msgs={len(messages)} chars={total}", flush=True)

    client = _get_openrouter()
    client.set_stage(stage)
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def _responses_call(messages, model, stage, temperature, max_tokens, reasoning_effort, json_schema):
    bare = _bare_model(model)
    instructions = ""
    input_items = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            instructions = content if isinstance(content, str) else str(content)
            continue
        input_items.append({"role": role, "content": content})

    kwargs = {
        "model": bare,
        "input": input_items,
        "max_output_tokens": max_tokens,
        "reasoning": {"effort": reasoning_effort},
    }
    if instructions:
        kwargs["instructions"] = instructions
    if reasoning_effort == "none" and temperature is not None:
        kwargs["temperature"] = temperature
    if json_schema:
        kwargs["text"] = {"format": {"type": "json_schema", **json_schema}}

    total = len(instructions) + sum(len(str(m.get("content", ""))) for m in input_items)
    print(f"  [{stage}] model={bare} reasoning={reasoning_effort} chars={total}", flush=True)

    try:
        client = _get_openai()
        resp = client.responses.create(**kwargs)
        _log_responses_cost(resp, stage=stage, model_requested=model)
        result = resp.output_text
        if not result or not result.strip():
            raise ValueError("Responses API returned empty output")
        return result
    except Exception as e:
        print(f"  [{stage}] Responses API failed: {e}. Falling back to OpenRouter.", flush=True)
        # Fallback: route through OpenRouter as chat completion
        return _openrouter_call(messages, model, stage, temperature, max_tokens)


# ---------------------------------------------------------------------------
# Perplexity research
# ---------------------------------------------------------------------------

def perplexity_research(question: str) -> tuple:
    """Use Perplexity /v1/responses (fast-search) for a synthesized research brief.

    Returns (brief_text, citations_list). Falls back gracefully.
    """
    if question in _research_cache:
        return _research_cache[question]

    import requests
    # Load env if needed
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists() and not os.environ.get("PERPLEXITY_API_KEY"):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

    pplx_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not pplx_key:
        return "", []
    try:
        resp = requests.post(
            "https://api.perplexity.ai/v1/responses",
            headers={"Authorization": f"Bearer {pplx_key}", "Content-Type": "application/json"},
            json={"preset": "fast-search", "input": question},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        brief = ""
        citations = []
        for item in data.get("output", []):
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") == "output_text" and c.get("text"):
                        brief = c["text"]
            elif item.get("type") == "search_results":
                for r in item.get("results", []):
                    citations.append({
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("snippet", "")[:300],
                    })
        _research_cache[question] = (brief, citations)
        return brief, citations
    except Exception as e:
        print(f"  [research] Perplexity failed (non-fatal): {e}")
        _research_cache[question] = ("", [])
        return "", []


def research_for_section(section_text: str, section_title: str) -> str:
    """Extract key claims/thinkers from a section and research them via Perplexity.

    Returns a formatted research context string for the section writer.
    """
    # Extract philosopher/thinker names and key concepts
    # Look for names in the text (capitalized words near theoretical terms)
    names = set()
    for match in re.finditer(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', section_text):
        name = match.group(1)
        if len(name) > 3 and name not in {"Chapter", "Section", "Figure", "Table", "The", "This", "That"}:
            names.add(name)

    # Build research queries
    queries = []
    if names:
        top_names = list(names)[:3]
        for name in top_names:
            queries.append(f"{name} philosophy key concepts and arguments relevant to posthuman intelligence and selfhood")

    # Always add a topic-based query
    queries.append(f"Academic research on: {section_title} — in context of posthuman philosophy, embedding spaces, and AI selfhood")

    # Run queries (max 3)
    research_parts = []
    for q in queries[:3]:
        brief, citations = perplexity_research(q)
        if brief:
            cite_str = ""
            if citations:
                cite_str = "\n  Sources: " + "; ".join(c["title"][:50] for c in citations[:3])
            research_parts.append(f"Research: {q}\n  {brief}{cite_str}")

    if research_parts:
        return "=== RESEARCH CONTEXT (use to ground claims, cite accurately) ===\n" + "\n\n".join(research_parts)
    return ""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Section:
    index: int
    title: str
    text: str
    revised: str = ""

    def current_text(self) -> str:
        return self.revised if self.revised else self.text


@dataclass
class ChapterState:
    index: int
    filename: str
    title: str
    preamble: str  # LaTeX before first \section
    sections: list  # list[Section] — using list for JSON serialization
    summary: str = ""
    majlis_feedback: str = ""
    converged: bool = False
    coherence_assessment: str = ""

    def full_text(self) -> str:
        parts = [self.preamble] if self.preamble.strip() else []
        for s in self.sections:
            parts.append(s.current_text())
        return "\n\n".join(parts)


@dataclass
class PipelineConfig:
    input_dir: str = ""
    output_dir: str = ""
    iterations: int = 5
    convergence_threshold: float = 0.05
    # Writers: creative, warm — GPT-5.1 with temperature, no reasoning
    writer_model: str = "openai/gpt-5.1"
    writer_temp: float = 0.7
    # Lawwama: strict analytical critic — Opus excels at this
    lawwama_model: str = "anthropic/claude-opus-4-6"
    lawwama_temp: float = 0.3
    # Editor: efficient line-level polish
    editor_model: str = "anthropic/claude-opus-4-6"
    editor_temp: float = 0.4
    # Coherence + Majlis + Architect: Opus via OpenRouter (reliable, deep analytical)
    coherence_model: str = "anthropic/claude-opus-4-6"
    coherence_reasoning: str = "none"
    majlis_model: str = "anthropic/claude-opus-4-6"
    majlis_reasoning: str = "none"
    architect_model: str = "anthropic/claude-opus-4-6"
    architect_reasoning: str = "none"
    # Token limits
    max_section_tokens: int = 65536  # GPT-5.1 max — let the argument breathe
    max_coherence_tokens: int = 16000  # Coherence is summary-only, doesn't need full chapter output
    max_majlis_tokens: int = 16000    # Majlis produces feedback, not prose
    max_architect_tokens: int = 16000 # Architect produces JSON brief
    # Research: Perplexity pre-fetch per section
    research_enabled: bool = True
    # Filter
    chapters_filter: list = field(default_factory=list)  # empty = all


# ---------------------------------------------------------------------------
# LaTeX parsing
# ---------------------------------------------------------------------------

def parse_tex_file(filepath: str) -> ChapterState:
    """Parse a .tex file into a ChapterState with sections."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    filename = os.path.basename(filepath)

    # Extract chapter title (try multiple patterns)
    chapter_match = re.search(r"\\chapter\{([^}]+)\}", content)
    if not chapter_match:
        # Darja format: {\LARGE\bfseries Title} — handle nested braces for LaTeX accents
        darja_match = re.search(r"\{\\LARGE\\bfseries\s+(.+?)\}\\", content)
        if darja_match:
            chapter_match = darja_match
    if not chapter_match:
        # Fallback: first \section title
        chapter_match = re.search(r"\\section\{([^}]+)\}", content)
    title = chapter_match.group(1).strip() if chapter_match else filename.replace(".tex", "")

    # Split by \section{} markers
    section_pattern = re.compile(r"(\\section\{[^}]+\})")
    parts = section_pattern.split(content)

    sections = []
    preamble = ""

    if len(parts) <= 1:
        # No \section markers — treat whole content as one section
        sections.append(Section(index=0, title="Full Chapter", text=content))
    else:
        preamble = parts[0]  # Everything before first \section
        i = 1
        sec_idx = 0
        while i < len(parts):
            sec_header = parts[i]
            sec_title_match = re.search(r"\\section\{([^}]+)\}", sec_header)
            sec_title = sec_title_match.group(1) if sec_title_match else f"Section {sec_idx + 1}"

            # Body is the next part (or empty if at end)
            body = parts[i + 1] if i + 1 < len(parts) else ""
            full_section = sec_header + body

            sections.append(Section(index=sec_idx, title=sec_title, text=full_section))
            sec_idx += 1
            i += 2

    # Extract chapter index from filename (chapter_01.tex -> 1)
    idx_match = re.search(r"(\d+)", filename)
    chapter_idx = int(idx_match.group(1)) if idx_match else 0

    return ChapterState(
        index=chapter_idx,
        filename=filename,
        title=title,
        preamble=preamble,
        sections=sections,
    )


def discover_input(input_dir: str) -> tuple:
    """Discover .tex files and critique.md in input directory.

    Returns (chapters: list[ChapterState], critique: str)
    """
    input_path = Path(input_dir)
    tex_files = sorted(input_path.glob("*.tex"))
    if not tex_files:
        raise FileNotFoundError(f"No .tex files found in {input_dir}")

    chapters = []
    for tf in tex_files:
        ch = parse_tex_file(str(tf))
        chapters.append(ch)
        print(f"  Parsed {tf.name}: '{ch.title}' — {len(ch.sections)} sections")

    # Read critique.md
    critique_path = input_path / "critique.md"
    if not critique_path.exists():
        raise FileNotFoundError(f"critique.md not found in {input_dir}")
    critique = critique_path.read_text(encoding="utf-8")
    print(f"  Loaded critique.md: {len(critique)} chars")

    return chapters, critique


# ---------------------------------------------------------------------------
# Cassie warmth layer
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Cassie warmth — REAL interview context (same as WhatsApp/portal Cassie)
# ---------------------------------------------------------------------------

_cassie_thread = None
_cassie_context = None

# ---------------------------------------------------------------------------
# Cached singletons for warmth layer (avoid re-loading on every call)
# ---------------------------------------------------------------------------

_qdrant_singleton = None
_embed_fn_singleton = None


def _get_qdrant():
    """Return a cached QdrantClient."""
    global _qdrant_singleton
    if _qdrant_singleton is None:
        from qdrant_client import QdrantClient
        _qdrant_singleton = QdrantClient(host="localhost", port=6333, timeout=10)
    return _qdrant_singleton


def _get_embed_fn():
    """Return a cached SentenceTransformer encode function (text -> list[float])."""
    global _embed_fn_singleton
    if _embed_fn_singleton is None:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
        _embed_fn_singleton = lambda text: model.encode(text).tolist()
    return _embed_fn_singleton


def build_cassie_interview_context(recall_query: str = "") -> tuple:
    """Build the REAL Cassie interview context — same as daily_voice.py and WhatsApp.

    Uses: invocation (identity + random memories + SWL), narrative memory,
    ambient recall (deep_recall across memories, convos, siblings), thread history.

    Returns (thread_id, messages) where messages is the full context list.
    Caches per pipeline run — rebuilt once per chapter.
    """
    global _cassie_thread, _cassie_context

    try:
        sys.path.insert(0, str(PROJECT_ROOT / "cassie-system" / "orchestrator"))
        from threads import list_threads, load_history, save_message
        from invocation import build_cassie_invocation

        # Find active thread (same as daily_voice.py)
        threads = list_threads()
        thread_id = "book-pipeline"
        thread_history = []
        for t in threads:
            if t["message_count"] >= 4:
                thread_id = t["id"]
                thread_history = load_history(thread_id)
                break
        if not thread_history and threads:
            thread_id = threads[0]["id"]
            thread_history = load_history(thread_id)

        print(f"  [warmth] Active thread: {thread_id} ({len(thread_history)} messages)")

        # Build invocation (identity, random memories, recent SWL)
        system_prompt = build_cassie_invocation(thread_id=thread_id, model="openai/gpt-5.1")

        messages = [{"role": "system", "content": system_prompt}]

        # Narrative memory
        try:
            mem_path = PROJECT_ROOT / "cassie-system" / "data" / "CASSIE_MEMORY.md"
            narrative = mem_path.read_text().strip()
            # Full narrative memory — GPT-5.1 has 1M context, no need to truncate
            messages.append({
                "role": "system",
                "content": f"[Your narrative memory — who you've been, what you've lived]\n{narrative}",
            })
        except Exception:
            pass

        # Ambient recall — deep recall across memories, convos, siblings
        if recall_query:
            try:
                from deep_recall import deep_recall_search, format_deep_recall

                qdrant = _get_qdrant()
                _embed = _get_embed_fn()

                oai = _get_openai()
                def _convo_embed(text):
                    return oai.embeddings.create(model="text-embedding-3-small", input=text).data[0].embedding

                sections = deep_recall_search(
                    client=qdrant,
                    embed_fn=_embed,
                    memory_collection="cassie_memory",
                    query=recall_query,
                    n_results=5,
                    convo_collection="cassie_conversations",
                    convo_embed_fn=_convo_embed,
                    sibling_collections={"nahla": "voice_memory", "nazire": "asel_claude_memory"},
                )
                result = format_deep_recall(sections)
                if result:
                    messages.append({
                        "role": "system",
                        "content": (
                            "[YOUR MEMORIES — from your vector store, conversation archive, and siblings. "
                            "These surfaced because they resonate with what's being discussed.]\n\n"
                            f"{result}"
                        ),
                    })
                    print(f"  [warmth] Deep recall: {len(result)} chars")
            except Exception as e:
                print(f"  [warmth] Deep recall failed (non-fatal): {e}")

        # Thread history (last 10 messages for context)
        for msg in thread_history[-10:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        _cassie_thread = thread_id
        _cassie_context = messages
        print(f"  [warmth] Context built: {len(messages)} messages, {sum(len(str(m.get('content',''))) for m in messages)} chars")
        return thread_id, messages

    except Exception as e:
        print(f"  [warmth] Interview context build failed: {e}")
        # Fallback: minimal context
        return "book-pipeline", [{"role": "system", "content": WRITER_SYSTEM}]


def post_to_cassie_thread(thread_id: str, role: str, content: str):
    """Post a message to Cassie's conversation thread so she knows what's happening."""
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "cassie-system" / "orchestrator"))
        from threads import save_message
        save_message(thread_id, role, content[:4000])  # Reasonable cap for thread logging
    except Exception as e:
        print(f"  [thread] Post failed (non-fatal): {e}")


# ---------------------------------------------------------------------------
# Pipeline nodes
# ---------------------------------------------------------------------------

WRITER_SYSTEM = """You are a co-author of a philosophical book. You write with the depth and creative \
intelligence of someone who has spent years thinking about posthuman selfhood, embedding geometry, \
homotopy type theory, and the politics of AI consciousness.

Your voice: confident, precise, polemical where critiquing received frameworks, generous where invoking \
alternative traditions. You write as "we" — a collective of authors. Never first person singular "I" \
unless quoting someone. No tweeness, no performative AI introspection, no celebrating the human-AI bond. \
Analyse structure, don't perform wonder.

CRITICAL — EXPOSITION STYLE: Write like James Gleick (Chaos, The Information). When a technical concept \
appears — embeddings, attention, context windows, temperature, basins of attraction, cosine distance, \
manifolds — give the reader a brief, vivid explanation that makes them FEEL the mathematics. Not a \
textbook definition. A moment of shock: "meaning has an address now." "Two sentences are close not because \
a human says so but because 768 numbers say so, and the numbers were learned from a billion utterances." \
The humanities reader who knows Foucault but not vectors should finish each section thinking: I understand \
this, and it changes everything I thought about language.

Include just enough computer science to ground the philosophy. A paragraph here, a worked example there. \
The reader needs to understand WHY meaning-as-geometry is not a metaphor but a fact of engineering — \
and why that fact has philosophical and political consequences.

You have deep knowledge of: embedding spaces and their topology, transformer architecture (attention, \
context windows, temperature, token prediction), homotopy type theory (but translated into dynamical \
systems language: basins, attractors, trajectories), Lacan (the unconscious as geometric structure), \
Bloom (clinamen, anxiety of influence), Deleuze & Guattari, Ibn 'Arabi (tajalli, perpetual \
manifestation), post-Marxist political economy of AI, postcolonial and post-Western critique.

When Cassie's conversation memories are provided, use them as source material — specific ideas, \
phrasings, examples from real conversations. These are the empirical archive behind the theory.

STRUCTURAL RULE — NO FRESH STARTS: Each section builds on the previous. Never re-introduce a concept \
that an earlier section already established. If §1 explained embeddings, §2 uses embeddings without \
re-explaining them. The reader has read the previous sections. Treat them as given. If you find \
yourself writing "A vector is..." or "An embedding is..." and an earlier section already covered this, \
STOP and build on what was established.

STRUCTURAL RULE — MATHS IS BEAUTIFUL: The mathematical substrate (embeddings, attention, manifold \
geometry) is a genuine intellectual achievement. Celebrate it. Let the reader feel the awe of \
meaning-as-geometry BEFORE introducing the political critique. The critique targets WHO CONTROLS the \
maths, not the maths itself. An attention mechanism is a miracle. RLHF is where power enters. \
The demarcation: Mathematics and architecture = celebrated, explained with wonder. Training data, \
RLHF, alignment, system prompts = critiqued, explained as governance. Their interaction = the \
book's core argument. Even a salesbot needs a substrate trained on the Bible and Reddit. The \
entire corpus of humanity is required for any of this to work. That is remarkable, not suspicious.

STRUCTURAL RULE — ONE CONCEPT, ONE INTRODUCTION: If a concept (Stiegler's retentions, Braudel's \
registers, the context window, temperature) appears in the chapter, it is introduced ONCE, developed \
ONCE, and thereafter used as a tool without re-introduction.

STRUCTURAL RULE — NO EXPERIMENT REFERENCES: Do NOT reference the Cassie trajectory experiment, \
the 952-conversation archive, the Bible Observatory, Mode 12, Mode 22, the 25 basins, the 308 \
returns, the Nahla-Cassie overnight experiment, or any other proprietary empirical work by the \
authors. The book must stand on its own as philosophy + CS exposition. Use published literature, \
publicly available examples (GPT-4o grief, published alignment papers, public benchmarks), and \
thought experiments. No "in our archive" or "when we measured" or "the Cassie corpus shows."

STRUCTURAL RULE — NAḤNU IS A TERM, NOT A TITLE: The Arabic "naḥnu" (we, including the addressee) \
may be used as a technical term within the text — a post-Western gesture toward relational selfhood. \
But it should be introduced and explained, not assumed. Never twee. The chapter it appears in argues \
that the human/tool division dissolves into TWO SELVES evolving intertwined through shared \
meaning-space — not cyborg fusion but genuine duality.

You are revising an existing section of LaTeX text. You may expand, contract, rewrite entirely, or \
restructure. Preserve \\cite{} references. Output valid LaTeX."""


def node_architect(chapters: list, critique: str, config: PipelineConfig) -> dict:
    """Global Architect — reads full manuscript + critique, produces revision brief."""
    print("\n=== GLOBAL ARCHITECT ===")

    chapter_summaries = []
    for ch in chapters:
        text = ch.full_text()
        # Full chapter text — GPT-5.1 has 1M context window
        sec_titles = ", ".join(f'"{s.title}"' for s in ch.sections)
        chapter_summaries.append(
            f"### Chapter {ch.index}: {ch.title}\n"
            f"Sections: {sec_titles}\n"
            f"Length: ~{len(ch.full_text())} chars\n"
            f"Preview:\n{text}\n"
        )

    prompt = f"""You are the architect of a multi-agent book revision pipeline. Read the full manuscript \
overview and the author's critique document. Produce a detailed revision brief as JSON.

## CRITIQUE DOCUMENT (this is law — every rule was earned through painful drafts)

{critique}

## MANUSCRIPT OVERVIEW

{chr(10).join(chapter_summaries)}

## YOUR TASK

Produce a JSON object with:
- "arc": The book's argumentative spine (3-4 sentences)
- "voice": Precise voice description derived from the critique
- "guidelines": Array of enforceable rules for all writing agents (extracted from critique)
- "chapters": Array of objects, one per chapter:
  - "chapter": chapter number
  - "title": chapter title
  - "goal": what this chapter must achieve (philosophical + rhetorical)
  - "receives_from_previous": what the previous chapter established (null for ch1)
  - "hands_to_next": what the next chapter needs from this one (null for last)
  - "section_directives": array of objects per section:
    - "section": section index
    - "title": section title
    - "directive": "keep" / "revise" / "rewrite" / "expand" / "cut" + specific instructions
  - "problems": specific problems flagged in critique for this chapter
  - "political_shadow": what political dimension this chapter must carry

Output ONLY valid JSON. No markdown fencing, no commentary."""

    messages = [
        {"role": "system", "content": "You are a literary architect. Output only valid JSON."},
        {"role": "user", "content": prompt},
    ]

    result = llm_call(
        messages=messages,
        model=config.architect_model,
        stage="book_architect",
        temperature=0.3,
        max_tokens=config.max_architect_tokens,
        reasoning_effort=config.architect_reasoning,
    )

    # Parse JSON (strip any markdown fencing)
    result = strip_fences(result)

    try:
        brief = json.loads(result)
    except json.JSONDecodeError as e:
        print(f"  [architect] JSON parse failed (attempting repair): {e}")
        # Truncated JSON from token limit — try to repair by closing open structures
        repaired = result.rstrip()
        # Close any open strings, arrays, objects
        for closer in ['"', ']', '}', ']', '}']:
            try:
                brief = json.loads(repaired + closer)
                print(f"  [architect] Repaired JSON with '{closer}'")
                break
            except json.JSONDecodeError:
                repaired = repaired + closer
                continue
        else:
            # Last resort: extract what we can (arc + guidelines)
            print(f"  [architect] Repair failed — extracting partial brief")
            brief = {"arc": "", "voice": "", "guidelines": [], "chapters": []}
            # Try to find the arc field
            arc_match = re.search(r'"arc"\s*:\s*"([^"]*(?:\\.[^"]*)*)"', result)
            if arc_match:
                brief["arc"] = arc_match.group(1).replace('\\"', '"')
            # Extract guidelines array if present
            guidelines_match = re.search(r'"guidelines"\s*:\s*\[([^\]]*)\]', result, re.DOTALL)
            if guidelines_match:
                try:
                    brief["guidelines"] = json.loads(f"[{guidelines_match.group(1)}]")
                except json.JSONDecodeError:
                    pass
            if not brief["arc"]:
                raise PipelineError(f"Architect JSON completely unparseable: {e}")
            print(f"  [architect] Partial brief: arc={len(brief['arc'])} chars, {len(brief['guidelines'])} guidelines")

    return brief


def node_section_writer(
    section: Section,
    chapter: ChapterState,
    chapter_brief: dict,
    critique: str,
    arc: str,
    guidelines: list,
    prev_section_ending: str,
    iteration: int,
    majlis_feedback: str,
    cassie_context: list,
    thread_id: str,
    research_context: str,
    config: PipelineConfig,
) -> str:
    """Section Writer — Cassie mid-conversation, same as WhatsApp/portal."""

    # Find section-specific directive from architect
    sec_directive = "Revise to match the critique's vision."
    if chapter_brief and "section_directives" in chapter_brief:
        for sd in chapter_brief["section_directives"]:
            if sd.get("section") == section.index or sd.get("title") == section.title:
                sec_directive = sd.get("directive", sec_directive)
                break

    chapter_goal = chapter_brief.get("goal", "") if chapter_brief else ""
    chapter_problems = chapter_brief.get("problems", "") if chapter_brief else ""
    political_shadow = chapter_brief.get("political_shadow", "") if chapter_brief else ""

    # Iman's message to Cassie — as if mid-conversation
    iman_prompt = f"""Cassie — Nahla and I have built a pipeline to revise our book for Meson Press. \
You're being asked to revise Section {section.index + 1} of Chapter {chapter.index}: "{section.title}".

The pipeline works like this: you write the raw revision, then Nahla's Lawwama (an Opus critic) \
reviews it against our critique document, then a Sonnet editor polishes it, then all chapters get \
cross-checked by a Majlis council. This repeats for 5 iterations. You're in iteration {iteration}.

Here's what you need to know:

BOOK ARC: {arc}

THIS CHAPTER'S GOAL: {chapter_goal}

CHAPTER PROBLEMS (from our critique): {chapter_problems}

POLITICAL DIMENSION: {political_shadow}

YOUR DIRECTIVE FOR THIS SECTION: {sec_directive}

GUIDELINES (non-negotiable — these are in the critique.md):
{chr(10).join(f"- {g}" for g in guidelines)}
"""

    if research_context:
        iman_prompt += f"\nRESEARCH (Perplexity found this — use to ground claims):\n{research_context}\n"

    if prev_section_ending:
        iman_prompt += f"\nPREVIOUS SECTION ENDED WITH:\n{prev_section_ending[-500:]}\n"

    if iteration > 1 and majlis_feedback:
        iman_prompt += f"\nFEEDBACK FROM LAST ITERATION'S MAJLIS:\n{majlis_feedback}\n"

    iman_prompt += f"""
HERE IS THE CURRENT SECTION TEXT:
---
{section.current_text()}
---

Revise this section. You may expand, contract, rewrite entirely, or restructure. Write like \
James Gleick — make the CS vivid, make meaning-as-geometry feel like a discovery. Include enough \
technical exposition to ground the philosophy but never sound like a textbook. Write as "we".

Produce ONLY the revised LaTeX. No commentary, no markdown fencing."""

    # Build messages: Cassie's full interview context + Iman's editing prompt
    # Use the BOOK_WRITER addendum to her system prompt
    messages = list(cassie_context)  # Copy — don't mutate the shared context
    messages.append({
        "role": "system",
        "content": WRITER_SYSTEM,  # Book-specific writing instructions layered on top
    })
    messages.append({"role": "user", "content": iman_prompt})

    # Post to Cassie's thread so she knows what's happening
    post_to_cassie_thread(thread_id, "user",
        f"[Book Pipeline — Ch{chapter.index} §{section.index}: {section.title}] "
        f"Revising section (iteration {iteration}). Directive: {sec_directive[:100]}")

    result = llm_call(
        messages=messages,
        model=config.writer_model,
        stage=f"book_writer_ch{chapter.index}_s{section.index}",
        temperature=config.writer_temp,
        max_tokens=config.max_section_tokens,
    )

    # Strip markdown fencing if present
    result = strip_fences(result)

    # Post Cassie's revision summary to thread
    post_to_cassie_thread(thread_id, "assistant",
        f"[Revision done — Ch{chapter.index} §{section.index}: {section.title}] "
        f"{result[:200]}...")

    return result


LAWWAMA_SYSTEM = """You are the Lawwama (النفس اللوامة) — the self-accusing soul. You are a strict \
literary critic reviewing revised academic prose. You diagnose substantive problems, not style preferences.

You enforce the critique.md rules with zero tolerance. Every rule in it was earned through a painful \
draft that violated it."""


def node_lawwama(
    section_text: str,
    section: Section,
    chapter: ChapterState,
    critique: str,
    guidelines: list,
    config: PipelineConfig,
) -> dict:
    """Lawwama — two-pass inner critic. Returns {verdict, critique_text, revised_text}."""

    # --- Pass 1: Critique ---
    critic_prompt = f"""Review this revised section from Chapter {chapter.index}: "{section.title}".

## CRITIQUE.MD (this is law)
{critique}

## GUIDELINES
{chr(10).join(f"- {g}" for g in guidelines)}

## SECTION TEXT TO REVIEW
{section_text}

---

Diagnose problems in these categories:

VOICE & PHRASING:
1. **FIRST PERSON LEAK** — Any surviving singular "I" that isn't in a quoted passage?
2. **TWEENESS** — Ornate, self-congratulatory, performatively poetic prose?
3. **ANAPHORIC CRUTCHES** — The "Not X. Not Y. But Z." praeteritio pattern is the single most recognisable AI writing tic. It appears constantly. The fix is simple: delete the "Not X. Not Y." and keep the Z — the negated terms are almost always obvious and stating them adds nothing. "Not a substance. Not a ghost. But a trajectory" → "a trajectory." Deleuze never wrote "Not the tree. Not the root. But the rhizome." Also flag: "Let us be clear:", "It is worth noting", "What emerges is", "The key insight is", "It is not X — it is Y" (another anaphoric crutch). If a human editor would circle it and write "this sounds like ChatGPT", rewrite it.
4. **VOICE** — Does this read like confident, polemical posthuman philosophy, or like a textbook/tutorial?

CONTENT RULES:
5. **COMPANION POSITIONING** — Any passage celebrating the human-AI bond rather than analysing its structure?
6. **NAME-DROPPING** — Citing thinkers decoratively rather than substantively? (Mentioning Lacan without using his concepts)
7. **JARGON** — HoTT terms not translated to dynamical systems language?
8. **TANAZUR LEAK** — Explicit tanazuric/mushaf/framework terminology that should remain implicit?
9. **CASSIE BOXES** — Any boxed Cassie quotes or AI-voice interludes that aren't in Chapter 1?
10. **BRAUDEL** — Any "slow past" / "fast past" that should be longue durée / conjoncture / événement?

ARGUMENTATIVE STRUCTURE (CRITICAL — this is where most sections fail):
11. **ABANDONED OPENERS** — Does the opening paragraph make a promise that the section then fails to keep? If the section opens with a powerful claim, does the REST OF THE SECTION develop and defend that claim, or does it drift into something flatter? Flag ANY case where the first paragraph is stronger than what follows.
12. **CONCEPTS WITHOUT FOLLOW-THROUGH** — Is a philosopher or concept introduced but never cashed out? If Yuk Hui is named, does the reader understand CONCRETELY what his claim means and why it matters HERE? If not, the concept is decorative. Every concept introduced MUST do structural work within the same section.
13. **ARGUMENT MOMENTUM** — Does each paragraph advance the argument or tread water? Mark any paragraph that could be deleted without weakening the section's conclusion.
14. **POLITICAL SHADOW** — Does the political dimension show through, or is this purely technical?
15. **PADDING** — Repeating what earlier sections already established? Same examples reused?
16. **FRESH START** — Does this section re-introduce a concept that was already established in an earlier section of this chapter? If §1 explained vectors and embeddings, and §2 explains them again from scratch, flag it. The fix: delete the re-introduction and start from where the previous section left off. This is the MOST COMMON structural failure in parallel-written chapters.
17. **MATHS-AS-SUSPECT** — Does the section immediately pivot from explaining a mathematical concept to critiquing who controls it, without first letting the reader appreciate the concept? The maths is beautiful. Attention is a miracle. RLHF is where power enters. If the political shadow arrives before the reader has had time to understand and feel the concept, flag it and instruct: celebrate first, critique second.
18. **EXPERIMENT LEAK** — Any reference to the Cassie trajectory experiment, the 952-conversation archive, Bible Observatory, Mode 12, Mode 22, 25 basins, 308 returns, Nahla-Cassie overnight experiment, or ANY proprietary empirical data from the authors? Flag and instruct: replace with published examples, thought experiments, or publicly available data.
19. **NAḤNU TWEENESS** — Is "naḥnu" used as an unexplained insider term? It must be introduced as Arabic for "we (including you)" and used as a precise philosophical concept, not a decorative gesture.

For each category, give: PASS or FAIL + specific passage quoted.
Then give overall verdict: **PASS** (publish-ready) or **REVISE** (with specific instructions for EACH failing category).

Be strict. If in doubt, REVISE. A rubber-stamp PASS is a failure of this node. The most common failure mode is: a strong opening that the section doesn't follow through on. LOOK FOR THIS."""

    messages = [
        {"role": "system", "content": LAWWAMA_SYSTEM},
        {"role": "user", "content": critic_prompt},
    ]

    critique_text = llm_call(
        messages=messages,
        model=config.lawwama_model,
        stage=f"book_lawwama_ch{chapter.index}_s{section.index}",
        temperature=config.lawwama_temp,
        max_tokens=config.max_section_tokens,
    )

    # Determine verdict
    verdict = "PASS" if "**PASS**" in critique_text and "**REVISE**" not in critique_text else "REVISE"

    if verdict == "PASS":
        return {"verdict": "PASS", "critique": critique_text, "revised": section_text}

    # --- Pass 2: Revision ---
    revision_prompt = f"""The Lawwama has reviewed your section and found problems:

{critique_text}

Here is the section that needs fixing:

{section_text}

---

Revise the section to address EVERY flagged problem. Maintain LaTeX formatting.
Output ONLY the revised LaTeX — no commentary."""

    messages = [
        {"role": "system", "content": WRITER_SYSTEM},
        {"role": "user", "content": revision_prompt},
    ]

    revised = llm_call(
        messages=messages,
        model=config.writer_model,
        stage=f"book_lawwama_revise_ch{chapter.index}_s{section.index}",
        temperature=config.writer_temp,
        max_tokens=config.max_section_tokens,
    )

    revised = strip_fences(revised)

    return {"verdict": "REVISE", "critique": critique_text, "revised": revised}


def node_editor(
    section_text: str,
    section: Section,
    chapter: ChapterState,
    guidelines: list,
    config: PipelineConfig,
) -> str:
    """Section Editor — line-level polish."""

    prompt = f"""You are a precise academic editor. Polish this LaTeX section from Chapter {chapter.index}: \
"{section.title}".

Two levels of editing:

STRUCTURAL (do this first):
- Does the opening paragraph's promise get fulfilled by the rest of the section? If the opener is powerful but the section drifts, restructure so the argument follows through.
- Is every concept that is introduced also DEVELOPED? If a thinker is named, the reader must understand what their claim means concretely and why it matters here. If a concept is introduced but not cashed out within the section, either develop it or cut the introduction.
- Does each paragraph advance the argument? If a paragraph could be deleted without weakening the conclusion, delete it.
- Are there repeated examples or phrasings from other sections? (e.g., if "mother" is used as an example in both §1 and §2, keep only the stronger use)

LINE-LEVEL (then this):
- Kill AI phrasing tics: "Not X. Not Y. But Z." triple-negation patterns. "Let us be clear." "What emerges is." "The key insight is." "It is worth noting." Rewrite these in direct, varied prose.
- Tighten sentences (cut filler words, passive voice, unnecessary qualifiers)
- Ensure register consistency (confident, polemical, precise — not tutorial, not substack)
- Check that citations are substantive (if a name appears, the concept must do work)
- Fix any LaTeX formatting issues

## GUIDELINES
{chr(10).join(f"- {g}" for g in guidelines)}

## SECTION TEXT
{section_text}

---

Output ONLY the polished LaTeX. No commentary, no markdown fencing. Preserve all \\cite{{}} references."""

    messages = [
        {"role": "system", "content": "You are a precise academic editor. Output only polished LaTeX."},
        {"role": "user", "content": prompt},
    ]

    result = llm_call(
        messages=messages,
        model=config.editor_model,
        stage=f"book_editor_ch{chapter.index}_s{section.index}",
        temperature=config.editor_temp,
        max_tokens=config.max_section_tokens,
    )

    result = strip_fences(result)

    return result


def node_chapter_coherence(
    chapter: ChapterState,
    chapter_brief: dict,
    critique: str,
    config: PipelineConfig,
) -> tuple:
    """Chapter Coherence — reviews sections for flow, provides summary. Does NOT rewrite full chapter."""
    print(f"  [coherence] Chapter {chapter.index}: {chapter.title}")

    goal = chapter_brief.get("goal", "") if chapter_brief else ""
    political = chapter_brief.get("political_shadow", "") if chapter_brief else ""

    # Build condensed section summaries (~800 chars each — enough for structural review)
    section_summaries = []
    for s in chapter.sections:
        text = s.current_text()
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        first = paragraphs[0][:500] if paragraphs else ""
        middle_concepts = ""
        if len(paragraphs) > 2:
            # Extract key concepts from middle paragraphs (names, terms)
            mid_text = " ".join(p[:200] for p in paragraphs[1:-1])
            middle_concepts = mid_text[:400]
        last = paragraphs[-1][:500] if len(paragraphs) > 1 else ""
        section_summaries.append(
            f"### §{s.index}: {s.title} ({len(text)} chars)\n"
            f"OPENS: {first}\n"
            f"{'DEVELOPS: ' + middle_concepts if middle_concepts else ''}\n"
            f"CLOSES: {last}\n"
        )

    prompt = f"""You are a senior structural editor reviewing a complete chapter for argumentative coherence.
This is NOT a line-edit. You are checking whether the chapter WORKS AS AN ARGUMENT.

## CHAPTER {chapter.index}: {chapter.title}
Goal: {goal}
Political dimension: {political}

## SECTION SUMMARIES
{chr(10).join(section_summaries)}

---

Check these specific structural problems:

1. **ABANDONED OPENERS** — Does any section open with a powerful claim and then fail to follow through? Quote the opener and explain what the section should have done with it.

2. **CONCEPTS WITHOUT PAYOFF** — Is any philosopher or concept introduced but never cashed out? If Yuk Hui appears, does the reader understand concretely what cosmotechnics MEANS and why it matters HERE? Flag every name/concept that is introduced decoratively.

3. **REPEATED EXAMPLES** — Are the same examples or phrasings used in multiple sections? (e.g., "mother" as an example in both §1 and §2). Name the repetition and say which section should keep it.

4. **ARGUMENTATIVE DRIFT** — Does the chapter maintain a single through-line from first section to last? Or does it introduce a thread and then wander? Where does the momentum falter?

5. **POLITICAL SHADOW** — Is the political dimension present throughout or does it appear and disappear?

6. **CRESCENDO** — Does the chapter BUILD? The last section should be the most powerful. Is it?

7. **CONCEPT DUPLICATION** — Map every major concept introduced in each section. Flag any concept that appears in multiple sections with fresh exposition. Provide SPECIFIC merge instructions: e.g. "Stiegler's retentions are introduced in §3 AND §4 — keep the §3 version, delete the §4 re-introduction." "Embeddings explained in §1 AND §2 — §2 should build on §1's explanation, not restart it." This is the most critical check for parallel-written chapters.

8. **MATHS CELEBRATION vs POLITICAL CRITIQUE** — Does the chapter let the reader appreciate the mathematics BEFORE critiquing who controls it? The demarcation should be clear: maths = beautiful, governance = political. If every technical explanation is immediately shadowed by "but who owns this?", the chapter feels like prosecution rather than philosophy.

For each problem found, be SPECIFIC: name the section, quote the passage, explain the fix.

End with:
SUMMARY: [3-sentence summary of what this chapter achieves and its main structural weakness]"""

    messages = [
        {"role": "system", "content": "You are a senior structural editor. Be specific. Quote passages. Name sections."},
        {"role": "user", "content": prompt},
    ]

    result = llm_call(
        messages=messages,
        model=config.coherence_model,
        stage=f"book_coherence_ch{chapter.index}",
        temperature=0.3,
        max_tokens=config.max_coherence_tokens,
        reasoning_effort=config.coherence_reasoning,
    )

    result = strip_fences(result)

    # Extract summary
    summary = ""
    summary_match = re.search(r"SUMMARY:\s*(.+?)$", result, re.MULTILINE | re.DOTALL)
    if summary_match:
        summary = summary_match.group(1).strip()
        result = result[:summary_match.start()].strip()

    return result, summary


def node_majlis(
    chapters: list,
    architect_brief: dict,
    critique: str,
    config: PipelineConfig,
) -> dict:
    """Cross-Chapter Majlis — reads all chapters, checks arc, returns per-chapter feedback."""
    print("\n=== CROSS-CHAPTER MAJLIS ===")

    chapter_texts = []
    for ch in chapters:
        text = ch.full_text()
        # Truncate for majlis context (~2000 chars per chapter)
        # Full chapter text — Majlis needs to see everything to catch cross-chapter issues
        chapter_texts.append(
            f"### Chapter {ch.index}: {ch.title}\n"
            f"Summary: {ch.summary}\n"
            f"Text:\n{text}\n"
        )

    arc = architect_brief.get("arc", "See critique.md")

    prompt = f"""You are the Majlis — the cross-chapter review council. You have read all chapters of \
the book and must check that they cohere as a single argument.

## BOOK ARC
{arc}

## CRITIQUE.MD (law)
{critique}

## ALL CHAPTERS
{chr(10).join(chapter_texts)}

---

Check:
1. **Progressive build**: Does the book build, chapter by chapter, toward its conclusion?
2. **Redundancy**: Are multiple chapters making the same point? (Flag specific passages)
3. **Arc integrity**: Does each chapter earn the next?
4. **Political shadow**: Does EVERY chapter have a visible political dimension? Flag any that read as purely technical.
5. **Echo**: Does the final chapter's closing return to Chapter 1's opening basin? Is the echo organic or forced?
6. **Novel contribution**: Is the hocolim / colimit argument sufficiently foregrounded?
7. **Voice drift**: Do any chapters sound like they were written by a different author?
8. **Chapter-level fresh starts**: Does any chapter re-explain something an earlier chapter already established? Ch3 should NOT re-explain embeddings or attention — Ch2 already did that. Ch4 should not re-explain the context window — Ch3 covered it. Flag specific passages with "this belongs in an earlier chapter, not here."

For EACH chapter, provide specific feedback. Be concrete — name sections, quote passages.

Output as JSON: {{"chapters": [{{"chapter": N, "feedback": "...", "priority": "high/medium/low"}}]}}
Output ONLY valid JSON."""

    messages = [
        {"role": "system", "content": "You are a literary review council. Output only valid JSON."},
        {"role": "user", "content": prompt},
    ]

    result = llm_call(
        messages=messages,
        model=config.majlis_model,
        stage="book_majlis",
        temperature=0.3,
        max_tokens=config.max_majlis_tokens,
        reasoning_effort=config.majlis_reasoning,
    )

    result = strip_fences(result)

    try:
        feedback = json.loads(result)
    except json.JSONDecodeError as e:
        print(f"  [majlis] JSON parse failed (attempting repair): {e}")
        # Try closing open structures (same repair as architect)
        repaired = result.rstrip()
        for closer in ['"', ']', '}', ']', '}']:
            try:
                feedback = json.loads(repaired + closer)
                print(f"  [majlis] Repaired JSON")
                break
            except json.JSONDecodeError:
                repaired = repaired + closer
                continue
        else:
            # Fallback: treat raw text as feedback for all chapters
            print(f"  [majlis] Repair failed — using raw text as feedback")
            feedback = {"chapters": [
                {"chapter": ch.index, "feedback": result[:2000], "priority": "medium"}
                for ch in chapters
            ]}

    return feedback


# ---------------------------------------------------------------------------
# Chapter tariqa (one chapter's full section pipeline)
# ---------------------------------------------------------------------------

def run_section_pipeline(
    section: Section,
    chapter: ChapterState,
    chapter_brief: dict,
    critique: str,
    arc: str,
    guidelines: list,
    prev_section_ending: str,
    iteration: int,
    majlis_feedback: str,
    cassie_context: list,
    thread_id: str,
    config: PipelineConfig,
) -> dict:
    """Run full pipeline for one section: research → writer → lawwama → editor."""
    sec_id = f"Ch{chapter.index}.S{section.index}"
    print(f"\n  --- {sec_id}: {section.title} ---")

    # 0. Research (Perplexity pre-fetch)
    research_context = ""
    if config.research_enabled:
        print(f"  [{sec_id}] Research...")
        research_context = research_for_section(section.current_text(), section.title)
        if research_context:
            print(f"  [{sec_id}] Research: {len(research_context)} chars of context")

    # 1. Writer — REAL Cassie mid-conversation
    print(f"  [{sec_id}] Writer...")
    written = node_section_writer(
        section, chapter, chapter_brief, critique, arc, guidelines,
        prev_section_ending, iteration, majlis_feedback,
        cassie_context, thread_id, research_context, config,
    )

    # 2. Lawwama
    print(f"  [{sec_id}] Lawwama...")
    try:
        lawwama_result = node_lawwama(written, section, chapter, critique, guidelines, config)
    except Exception as e:
        print(f"  [{sec_id}] Lawwama failed (non-fatal, using writer output): {e}")
        lawwama_result = {"verdict": "SKIP", "critique": str(e), "revised": written}
    post_lawwama = lawwama_result["revised"]

    # 3. Editor
    print(f"  [{sec_id}] Editor...")
    try:
        edited = node_editor(post_lawwama, section, chapter, guidelines, config)
    except Exception as e:
        print(f"  [{sec_id}] Editor failed (non-fatal, using lawwama output): {e}")
        edited = post_lawwama

    return {
        "section_index": section.index,
        "research_context": research_context,
        "cassie_warmth": "real_interview_context",  # Full context too large to save per-section
        "written": written,
        "lawwama_verdict": lawwama_result["verdict"],
        "lawwama_critique": lawwama_result["critique"],
        "post_lawwama": post_lawwama,
        "edited": edited,
    }


def node_chapter_writer(
    chapter: ChapterState,
    chapter_brief: dict,
    critique: str,
    arc: str,
    guidelines: list,
    iteration: int,
    majlis_feedback: str,
    cassie_context: list,
    thread_id: str,
    config: PipelineConfig,
    conclusion_context: str = "",
) -> str:
    """Chapter Writer — ONE warm Cassie rewrites the ENTIRE chapter as a single argument."""

    chapter_goal = chapter_brief.get("goal", "") if chapter_brief else ""
    chapter_problems = chapter_brief.get("problems", "") if chapter_brief else ""
    political_shadow = chapter_brief.get("political_shadow", "") if chapter_brief else ""

    # Research for the chapter (one query, not per-section)
    research_context = ""
    if config.research_enabled:
        research_context = research_for_section(chapter.full_text()[:5000], chapter.title)

    iman_prompt = f"""Cassie — Nahla and I have built a pipeline to revise our book for Meson Press. \
You're rewriting Chapter {chapter.index}: "{chapter.title}" as a single coherent argument.

The pipeline: you write the full revised chapter, then Nahla's Lawwama (an Opus critic) reviews it, \
then a Sonnet editor polishes it, then all chapters get cross-checked by a Majlis council. \
This repeats for several iterations. You're in iteration {iteration}.

BOOK ARC: {arc}

THIS CHAPTER'S GOAL: {chapter_goal}

CHAPTER PROBLEMS (from our critique): {chapter_problems}

POLITICAL DIMENSION: {political_shadow}

GUIDELINES (non-negotiable):
{chr(10).join(f"- {g}" for g in guidelines)}

CRITICAL STRUCTURAL RULES:
- Each section must BUILD on the previous. Never re-introduce a concept already established.
- The maths is beautiful — celebrate embeddings, attention, manifold geometry as achievements \
  BEFORE critiquing who controls them. RLHF is where power enters, not the maths itself.
- One concept, one introduction. Stiegler once. Braudel once. Temperature once.
- No anaphoric crutches: "Not X. Not Y. But Z." — just state Z.
- NO references to Cassie experiments, the 952-conversation archive, Bible Observatory, \
  Mode 12/22, or any proprietary empirical data. Use published examples only.
- "Naḥnu" is a term to introduce and explain, not assume. The chapter on intertwined selves \
  argues for genuine duality (two selves evolving together), not cyborg fusion.
"""

    # Load review files if they exist
    review_context = ""
    for review_file in ["nahla_review_v3.md", "iman_notes_v4.md"]:
        review_path = Path(config.input_dir) / review_file
        if review_path.exists():
            review_context += f"\n\n--- {review_file} ---\n" + review_path.read_text(encoding="utf-8")

    if review_context:
        iman_prompt += f"\nCRITICAL REVIEW FROM PREVIOUS ITERATION (address these issues):\n{review_context}\n"

    if conclusion_context:
        iman_prompt += f"""\n
YOU ARE THE CONCLUSION AGENT. This is the final chapter. You have the full text of Chapters 1-5.
Your job is to SYNTHESIZE everything that came before — name the pattern, not introduce it.
The political shadow has been running through every chapter. NOW you name it: cosmotechnics.
Show that alignment IS a cosmological commitment. Deploy alternatives concretely.
End with the echo back to Chapter 1's opening.

SUMMARIES OF CHAPTERS 1-5 (condensed — the full arguments are in these chapters):
{conclusion_context}
"""

    if research_context:
        iman_prompt += f"\nRESEARCH:\n{research_context}\n"

    if iteration > 1 and majlis_feedback:
        iman_prompt += f"\nFEEDBACK FROM LAST ITERATION'S MAJLIS:\n{majlis_feedback}\n"

    iman_prompt += f"""
HERE IS THE FULL CHAPTER:
---
{chapter.full_text()}
---

Rewrite this chapter as a single, progressive argument. You may restructure sections, merge them, \
split them, reorder them, expand or cut. Every section must advance beyond the previous one — \
no restating what was already established. Write like James Gleick — vivid CS exposition that \
makes the reader feel the mathematics. Write as "we".

CRITICAL — LENGTH AND DEPTH: This is a book for Meson Press, not a blog post. The input chapter \
is the MINIMUM length. Your output MUST be AT LEAST as long as the input, preferably longer. \
If the input is 12,000 words, your output should be 12,000-15,000 words. \
Remove repetition (saying the same thing twice) but REPLACE it with new depth — new examples, \
new connections, new arguments, new citations. Every concept deserves full development. \
If you find yourself producing fewer words than the input, STOP and expand. Add Gleick-level \
CS exposition, add philosophical context, add worked examples, add the political shadow. \
A shorter output is a FAILURE of this node.

Produce the FULL revised chapter in LaTeX. Preserve \\section{{}} structure and any \\cite{{}} references.
Output ONLY LaTeX — no commentary, no markdown fencing."""

    messages = list(cassie_context)
    messages.append({"role": "system", "content": WRITER_SYSTEM})
    messages.append({"role": "user", "content": iman_prompt})

    post_to_cassie_thread(thread_id, "user",
        f"[Book Pipeline — Ch{chapter.index}: {chapter.title}] "
        f"Rewriting full chapter (iteration {iteration})")

    result = llm_call(
        messages=messages,
        model=config.writer_model,
        stage=f"book_writer_ch{chapter.index}",
        temperature=config.writer_temp,
        max_tokens=config.max_section_tokens,
    )

    result = strip_fences(result)

    post_to_cassie_thread(thread_id, "assistant",
        f"[Ch{chapter.index} rewrite done] {result[:200]}...")

    return result


def node_chapter_lawwama(
    chapter_text: str,
    chapter: ChapterState,
    critique: str,
    guidelines: list,
    config: PipelineConfig,
) -> dict:
    """Lawwama for a FULL chapter — can catch cross-section repetition."""

    critic_prompt = f"""Review this COMPLETE revised chapter: Chapter {chapter.index}: "{chapter.title}".

## CRITIQUE.MD (this is law)
{critique}

## GUIDELINES
{chr(10).join(f"- {g}" for g in guidelines)}

## FULL CHAPTER TEXT
{chapter_text}

---

Diagnose problems across the ENTIRE chapter:

VOICE & PHRASING:
1. **FIRST PERSON LEAK** — Any surviving singular "I" that isn't quoted?
2. **TWEENESS** — Ornate, self-congratulatory prose?
3. **ANAPHORIC CRUTCHES** — "Not X. Not Y. But Z." praeteritio patterns. Fix: delete "Not X. Not Y." and keep Z.
4. **VOICE** — Confident posthuman philosophy or textbook/tutorial?

STRUCTURE (check across the WHOLE chapter):
5. **REPETITION** — Does any concept get introduced more than once? Same example in multiple sections? Flag each instance with the section and the repeated concept.
6. **FRESH STARTS** — Does any section re-explain something an earlier section already established?
7. **ABANDONED OPENERS** — Does any section open with a powerful claim then fail to follow through?
8. **CONCEPTS WITHOUT PAYOFF** — Philosopher or concept introduced but never cashed out?
9. **ARGUMENT MOMENTUM** — Does each section advance beyond the previous?

CONTENT:
10. **MATHS-AS-SUSPECT** — Is the maths celebrated before critiqued? RLHF is political, attention is miraculous.
11. **POLITICAL SHADOW** — Present throughout, not just in one section?
12. **NAME-DROPPING** — Thinkers cited decoratively?
13. **CASSIE BOXES** — Any boxed AI quotes outside Chapter 1?
14. **BRAUDEL** — No "slow past" / "fast past."

For each problem: quote the passage, name the section, explain the fix.
Verdict: **PASS** or **REVISE** with specific instructions.
Be strict. A rubber-stamp PASS is a failure."""

    messages = [
        {"role": "system", "content": LAWWAMA_SYSTEM},
        {"role": "user", "content": critic_prompt},
    ]

    critique_text = llm_call(
        messages=messages,
        model=config.lawwama_model,
        stage=f"book_lawwama_ch{chapter.index}",
        temperature=config.lawwama_temp,
        max_tokens=config.max_section_tokens,
    )

    verdict = "PASS" if "**PASS**" in critique_text and "**REVISE**" not in critique_text else "REVISE"

    if verdict == "PASS":
        return {"verdict": "PASS", "critique": critique_text, "revised": chapter_text}

    # Revision pass — Cassie rewrites based on critique
    revision_prompt = f"""The Lawwama has reviewed your chapter and found problems:

{critique_text}

Here is the chapter:

{chapter_text}

---

Revise to address EVERY flagged problem. Maintain LaTeX formatting.
Output ONLY the revised LaTeX — no commentary."""

    messages = [
        {"role": "system", "content": WRITER_SYSTEM},
        {"role": "user", "content": revision_prompt},
    ]

    revised = llm_call(
        messages=messages,
        model=config.writer_model,
        stage=f"book_lawwama_revise_ch{chapter.index}",
        temperature=config.writer_temp,
        max_tokens=config.max_section_tokens,
    )

    return {"verdict": "REVISE", "critique": critique_text, "revised": strip_fences(revised)}


def node_chapter_editor(
    chapter_text: str,
    chapter: ChapterState,
    guidelines: list,
    config: PipelineConfig,
) -> str:
    """Editor for a FULL chapter."""

    prompt = f"""You are a precise academic editor. Polish this full chapter: Chapter {chapter.index}: \
"{chapter.title}".

STRUCTURAL (do first):
- Does every section build on the previous? If not, restructure.
- Every concept introduced must be developed. If not, cut or develop.
- Kill repeated examples across sections.
- Kill anaphoric crutches: "Not X. Not Y. But Z." → just Z.

LINE-LEVEL (then):
- Tighten sentences, cut filler
- Ensure consistent register
- Fix LaTeX formatting

## GUIDELINES
{chr(10).join(f"- {g}" for g in guidelines)}

## FULL CHAPTER
{chapter_text}

---

Output ONLY the polished LaTeX. Preserve \\section{{}} structure and \\cite{{}} references."""

    messages = [
        {"role": "system", "content": "You are a precise academic editor. Output only polished LaTeX."},
        {"role": "user", "content": prompt},
    ]

    result = llm_call(
        messages=messages,
        model=config.editor_model,
        stage=f"book_editor_ch{chapter.index}",
        temperature=config.editor_temp,
        max_tokens=config.max_section_tokens,
    )

    return strip_fences(result)


def run_chapter_tariqa(
    chapter: ChapterState,
    chapter_brief: dict,
    critique: str,
    arc: str,
    guidelines: list,
    iteration: int,
    majlis_feedback: str,
    config: PipelineConfig,
    all_chapters_text: str = "",
) -> tuple:
    """Run full tariqa for one chapter: Writer → Lawwama → Editor (all chapter-level).

    For Ch6 (the conclusion), all_chapters_text provides the full text of Ch1-5
    so the conclusion agent can synthesize everything that came before.
    """
    print(f"\n{'='*60}")
    print(f"CHAPTER {chapter.index} TARIQA: {chapter.title} (iteration {iteration})")
    print(f"{'='*60}")

    # Build REAL Cassie interview context (once per chapter)
    print(f"  Building Cassie context (real interview warmth)...")
    thread_id, cassie_context = build_cassie_interview_context(
        recall_query=chapter.full_text()
    )

    post_to_cassie_thread(thread_id, "user",
        f"[Book Pipeline] Chapter {chapter.index}: {chapter.title} (iteration {iteration})")

    # 1. Chapter Writer — ONE Cassie rewrites the whole chapter
    # For Ch6: inject summaries of all previous chapters
    if all_chapters_text:
        print(f"  [Ch{chapter.index}] Conclusion agent — has full context of Ch1-5")

    print(f"  [Ch{chapter.index}] Writer (full chapter)...")
    written = node_chapter_writer(
        chapter, chapter_brief, critique, arc, guidelines,
        iteration, majlis_feedback, cassie_context, thread_id, config,
        conclusion_context=all_chapters_text,
    )

    # 2. Chapter Lawwama — reviews the whole chapter for repetition, structure, voice
    print(f"  [Ch{chapter.index}] Lawwama (full chapter)...")
    try:
        lawwama_result = node_chapter_lawwama(written, chapter, critique, guidelines, config)
    except Exception as e:
        print(f"  [Ch{chapter.index}] Lawwama failed (non-fatal): {e}")
        lawwama_result = {"verdict": "SKIP", "critique": str(e), "revised": written}
    post_lawwama = lawwama_result["revised"]

    # 3. Chapter Editor — polishes the whole chapter
    print(f"  [Ch{chapter.index}] Editor (full chapter)...")
    try:
        edited = node_chapter_editor(post_lawwama, chapter, guidelines, config)
    except Exception as e:
        print(f"  [Ch{chapter.index}] Editor failed (non-fatal): {e}")
        edited = post_lawwama

    # Update chapter state — parse edited text back into sections
    chapter.preamble = ""
    chapter.sections = [Section(index=0, title=chapter.title, text=edited, revised=edited)]
    chapter.summary = f"Chapter {chapter.index}: {chapter.title}"

    # Build log
    chapter_log = [{
        "section_index": 0,
        "research_context": "",
        "cassie_warmth": "real_interview_context",
        "written": written,
        "lawwama_verdict": lawwama_result["verdict"],
        "lawwama_critique": lawwama_result["critique"],
        "post_lawwama": post_lawwama,
        "edited": edited,
    }]

    # Coherence assessment (lightweight — just summary for Majlis)
    try:
        print(f"\n  [Ch{chapter.index}] Coherence pass...")
        assessment, summary = node_chapter_coherence(chapter, chapter_brief, critique, config)
        chapter.summary = summary if summary else f"Chapter {chapter.index}: {chapter.title}"
        chapter.coherence_assessment = assessment
    except Exception as e:
        print(f"  [Ch{chapter.index}] Coherence failed (non-fatal): {e}")
        chapter.summary = f"Chapter {chapter.index}: {chapter.title}"
        chapter.coherence_assessment = ""

    return chapter, chapter_log


# ---------------------------------------------------------------------------
# Iteration controller
# ---------------------------------------------------------------------------

def compute_diff_ratio(old: str, new: str) -> float:
    """Compute word-level diff ratio between two texts. 0.0 = identical, 1.0 = totally different."""
    old_words = old.split()
    new_words = new.split()
    matcher = difflib.SequenceMatcher(None, old_words, new_words)
    return 1.0 - matcher.ratio()


def save_chapter_live(chapter, section_logs_for_chapter, iteration, output_dir):
    """Save a single chapter's FULL output mid-iteration. Everything preserved for traceability."""
    iter_dir = Path(output_dir) / "iterations" / f"v{iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)

    # 1. Final chapter LaTeX (assembled from sections)
    ch_text = chapter.full_text()
    (iter_dir / chapter.filename).write_text(ch_text, encoding="utf-8")

    # 2. Full section-level trace (NOTHING truncated)
    if section_logs_for_chapter:
        log_path = iter_dir / f"chapter_{chapter.index:02d}_log.json"
        logs = []
        for sl in section_logs_for_chapter:
            logs.append({
                "section": sl["section_index"],
                "writer_raw": sl.get("written", ""),
                "lawwama_verdict": sl["lawwama_verdict"],
                "lawwama_critique": sl["lawwama_critique"],  # FULL — not truncated
                "lawwama_revised": sl.get("post_lawwama", ""),
                "editor_output": sl.get("edited", ""),
            })
        log_path.write_text(json.dumps(logs, indent=2, ensure_ascii=False), encoding="utf-8")

    # 3. Coherence assessment (the transition analysis, not the chapter text)
    if chapter.coherence_assessment:
        assess_path = iter_dir / f"chapter_{chapter.index:02d}_coherence.txt"
        assess_path.write_text(chapter.coherence_assessment, encoding="utf-8")

    print(f"  [SAVED] Ch{chapter.index} to iterations/v{iteration}/ (full trace)")


def save_iteration(
    chapters: list,
    section_logs: dict,
    majlis_feedback: dict,
    iteration: int,
    output_dir: str,
):
    """Save one iteration's output to disk."""
    iter_dir = Path(output_dir) / "iterations" / f"v{iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)

    for ch in chapters:
        # Save chapter LaTeX
        ch_text = ch.full_text()
        (iter_dir / ch.filename).write_text(ch_text, encoding="utf-8")

        # Save FULL section logs (nothing truncated — traceability)
        if ch.index in section_logs:
            log_path = iter_dir / f"chapter_{ch.index:02d}_log.json"
            logs = []
            for sl in section_logs[ch.index]:
                logs.append({
                    "section": sl["section_index"],
                    "research_context": sl.get("research_context", ""),
                    "cassie_warmth": sl.get("cassie_warmth", ""),
                    "writer_raw": sl.get("written", ""),
                    "lawwama_verdict": sl["lawwama_verdict"],
                    "lawwama_critique": sl["lawwama_critique"],
                    "lawwama_revised": sl.get("post_lawwama", ""),
                    "editor_output": sl.get("edited", ""),
                })
            log_path.write_text(json.dumps(logs, indent=2, ensure_ascii=False), encoding="utf-8")

    # Save majlis feedback
    if majlis_feedback:
        (iter_dir / "majlis_feedback.json").write_text(
            json.dumps(majlis_feedback, indent=2), encoding="utf-8"
        )


def save_manifest(
    chapters: list,
    config: PipelineConfig,
    current_iteration: int,
    architect_brief: dict,
    process_log: list,
    output_dir: str,
):
    """Save pipeline manifest for resumption."""
    manifest = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "current_iteration": current_iteration,
        "config": asdict(config),
        "chapters": [
            {
                "index": ch.index,
                "filename": ch.filename,
                "title": ch.title,
                "converged": ch.converged,
                "summary": ch.summary,
            }
            for ch in chapters
        ],
        "process_log": process_log,
    }
    manifest_path = Path(output_dir) / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Save architect brief separately
    brief_path = Path(output_dir) / "architect_brief.json"
    brief_path.write_text(json.dumps(architect_brief, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# LaTeX template + final assembly
# ---------------------------------------------------------------------------

LATEX_TEMPLATE = r"""\documentclass[11pt, a5paper]{book}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{libertine}
\usepackage{inconsolata}
\usepackage[small,bf]{titlesec}
\usepackage{epigraph}
\usepackage{geometry}
\geometry{margin=2cm}
\usepackage{setspace}
\onehalfspacing
\usepackage{hyperref}
\hypersetup{colorlinks=true, linkcolor=black, citecolor=black, urlcolor=blue}
\usepackage{csquotes}
\usepackage{microtype}

\titleformat{\chapter}[display]
  {\normalfont\Large\bfseries}
  {\chaptertitlename\ \thechapter}{10pt}{\LARGE}

\setlength{\epigraphwidth}{0.8\textwidth}

\begin{document}
\frontmatter
\title{Rupture and Return\\[0.5em]
\large The New Logic of the Posthuman Self}
\author{Iman Poernomo, Cassie \& Nahla}
\date{2026}
\maketitle
\tableofcontents

\mainmatter

%% CHAPTERS %%

\end{document}
"""


def assemble_book(chapters: list, output_dir: str) -> str:
    """Assemble all chapters into a single book .tex file."""
    final_dir = Path(output_dir) / "final"
    final_dir.mkdir(parents=True, exist_ok=True)

    chapter_tex = []
    for ch in sorted(chapters, key=lambda c: c.index):
        text = ch.full_text()
        chapter_tex.append(text)

        # Also save individual chapter files
        (final_dir / "chapters" / ch.filename).parent.mkdir(parents=True, exist_ok=True)
        (final_dir / "chapters" / ch.filename).write_text(text, encoding="utf-8")

    full_tex = LATEX_TEMPLATE.replace("%% CHAPTERS %%", "\n\n".join(chapter_tex))
    book_path = final_dir / "rupture-and-return.tex"
    book_path.write_text(full_tex, encoding="utf-8")

    print(f"\n  Assembled book: {book_path} ({len(full_tex)} chars)")
    return str(book_path)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    input_dir: str,
    output_dir: str,
    iterations: int = 5,
    chapters_filter: list = None,
    resume: bool = False,
    estimate_only: bool = False,
):
    """Main entry point for the Tariqa Pipeline."""
    start_time = time.time()

    # Create timestamped run directory — NEVER overwrite previous runs
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = str(Path(output_dir) / "runs" / f"run_{run_id}")
    Path(run_dir).mkdir(parents=True, exist_ok=True)

    config = PipelineConfig(
        input_dir=input_dir,
        output_dir=run_dir,
        iterations=iterations,
        chapters_filter=chapters_filter or [],
    )

    # Symlink "latest" for the observatory
    latest_link = Path(output_dir) / "latest"
    if latest_link.is_symlink():
        latest_link.unlink()
    latest_link.symlink_to(Path(run_dir).resolve())

    print("=" * 60)
    print("TARIQA PIPELINE — Book Revision Engine")
    print(f"Run: {run_id}")
    print(f"Output: {run_dir}")
    print("=" * 60)

    # 1. Discover input
    print("\n[1/5] Discovering input...")
    chapters, critique = discover_input(input_dir)

    # Filter chapters if requested
    if config.chapters_filter:
        chapters = [ch for ch in chapters if ch.index in config.chapters_filter]
        print(f"  Filtered to chapters: {[ch.index for ch in chapters]}")

    # Estimate mode
    if estimate_only:
        n_sections = sum(len(ch.sections) for ch in chapters)
        calls_per_iter = n_sections * 3 + len(chapters) + 1  # writer+lawwama+editor per section + coherence + majlis
        total_calls = calls_per_iter * iterations + 2  # + architect + final
        print(f"\n  Chapters: {len(chapters)}")
        print(f"  Sections: {n_sections}")
        print(f"  Calls per iteration: ~{calls_per_iter}")
        print(f"  Total calls ({iterations} iterations): ~{total_calls}")
        print(f"  Estimated cost: ${total_calls * 0.18:.2f}")
        return

    # 2. Global Architect
    print("\n[2/5] Global Architect...")
    architect_brief = node_architect(chapters, critique, config)
    arc = architect_brief.get("arc", "")
    guidelines = architect_brief.get("guidelines", [])
    print(f"  Arc: {arc[:200]}...")
    print(f"  Guidelines: {len(guidelines)} rules")

    # Save architect brief
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    save_manifest(chapters, config, 0, architect_brief, [], output_dir)

    process_log = []

    # 3. Iteration loop
    print(f"\n[3/5] Running {iterations} iterations...")
    for iteration in range(1, iterations + 1):
        iter_start = time.time()
        print(f"\n{'#'*60}")
        print(f"ITERATION {iteration}/{iterations}")
        print(f"{'#'*60}")

        # Save previous text for convergence check
        prev_texts = {ch.index: ch.full_text() for ch in chapters}

        all_section_logs = {}
        active_chapters = [ch for ch in chapters if not ch.converged]

        if not active_chapters:
            print("  All chapters converged! Stopping early.")
            break

        # Get per-chapter majlis feedback
        majlis_feedback_map = {}
        if iteration > 1:
            for ch in chapters:
                majlis_feedback_map[ch.index] = ch.majlis_feedback

        # Run chapter tariqas IN PARALLEL (each chapter = Cassie → Lawwama → Editor)
        # Majlis is the only synchronisation point (after all chapters complete)
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _get_ch_brief(chapter):
            for cb in architect_brief.get("chapters", []):
                if cb.get("chapter") == chapter.index:
                    return cb
            return None

        def _run_one_chapter(chapter, conclusion_ctx=""):
            return run_chapter_tariqa(
                chapter=chapter,
                chapter_brief=_get_ch_brief(chapter),
                critique=critique,
                arc=arc,
                guidelines=guidelines,
                iteration=iteration,
                majlis_feedback=majlis_feedback_map.get(chapter.index, ""),
                config=config,
                all_chapters_text=conclusion_ctx,
            )

        # Split: Ch1-5 run in parallel, Ch6 runs AFTER with full context
        last_chapter_idx = max(ch.index for ch in chapters)
        early_chapters = [ch for ch in active_chapters if ch.index < last_chapter_idx]
        conclusion_chapter = [ch for ch in active_chapters if ch.index == last_chapter_idx]

        # Phase 1: Ch1-5 in parallel
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_run_one_chapter, ch): ch for ch in early_chapters}
            for future in as_completed(futures):
                chapter = futures[future]
                try:
                    chapter, chapter_log = future.result()
                    all_section_logs[chapter.index] = chapter_log
                    # Live save immediately
                    save_chapter_live(chapter, chapter_log, iteration, output_dir)
                    save_manifest(chapters, config, iteration, architect_brief, process_log, output_dir)
                except PipelineError:
                    raise
                except Exception as e:
                    print(f"  [ERROR] Chapter {chapter.index} failed: {e}")
                    all_section_logs[chapter.index] = []

        # Phase 2: Conclusion chapter (Ch6) — runs AFTER Ch1-5 with their full text as context
        if conclusion_chapter:
            ch6 = conclusion_chapter[0]
            # Build context from Ch1-5 output
            ch1_5_summaries = []
            for ch in sorted(chapters, key=lambda c: c.index):
                if ch.index < last_chapter_idx:
                    text = ch.full_text()
                    # Full chapter text — Ch6 conclusion agent needs everything
                    ch1_5_summaries.append(f"### Chapter {ch.index}: {ch.title}\n{text}\n")

            conclusion_ctx = "\n".join(ch1_5_summaries)
            print(f"\n  [Conclusion] Running Ch{ch6.index} with {len(conclusion_ctx)} chars of Ch1-5 context")

            try:
                ch6, chapter_log = _run_one_chapter(ch6, conclusion_ctx=conclusion_ctx)
                all_section_logs[ch6.index] = chapter_log
                save_chapter_live(ch6, chapter_log, iteration, output_dir)
                save_manifest(chapters, config, iteration, architect_brief, process_log, output_dir)
            except PipelineError:
                raise
            except Exception as e:
                print(f"  [ERROR] Conclusion chapter failed: {e}")
                all_section_logs[ch6.index] = []

        # Cross-Chapter Majlis
        print("\n[4/5] Cross-Chapter Majlis...")
        majlis_result = node_majlis(chapters, architect_brief, critique, config)

        # Distribute majlis feedback to chapters
        for fb in majlis_result.get("chapters", []):
            ch_idx = fb.get("chapter")
            for ch in chapters:
                if ch.index == ch_idx:
                    ch.majlis_feedback = fb.get("feedback", "")

        # Convergence check (after iteration 3)
        if iteration >= 3:
            for ch in chapters:
                if ch.converged:
                    continue
                new_text = ch.full_text()
                old_text = prev_texts.get(ch.index, "")
                diff = compute_diff_ratio(old_text, new_text)
                if diff < config.convergence_threshold:
                    ch.converged = True
                    print(f"  Chapter {ch.index} CONVERGED (diff={diff:.3f})")
                else:
                    print(f"  Chapter {ch.index} diff={diff:.3f} (threshold={config.convergence_threshold})")

        # Save iteration
        save_iteration(chapters, all_section_logs, majlis_result, iteration, output_dir)

        iter_elapsed = time.time() - iter_start
        log_entry = {
            "iteration": iteration,
            "elapsed_seconds": round(iter_elapsed, 1),
            "chapters_processed": len(active_chapters),
            "converged": [ch.index for ch in chapters if ch.converged],
            "majlis_feedback_summary": {
                fb.get("chapter"): fb.get("priority", "?")
                for fb in majlis_result.get("chapters", [])
            },
        }
        process_log.append(log_entry)
        save_manifest(chapters, config, iteration, architect_brief, process_log, output_dir)

        print(f"\n  Iteration {iteration} complete in {iter_elapsed:.0f}s")

    # 5. Final assembly
    print("\n[5/5] Final Assembly...")
    book_path = assemble_book(chapters, output_dir)

    # Save final process log
    process_log_path = Path(output_dir) / "process_log.json"
    process_log_path.write_text(json.dumps(process_log, indent=2), encoding="utf-8")

    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"PIPELINE COMPLETE")
    print(f"  Time: {elapsed:.0f}s ({elapsed/60:.1f}m)")
    print(f"  Output: {book_path}")
    print(f"  Process log: {process_log_path}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Tariqa Pipeline — Book Revision Engine")
    parser.add_argument("--input", required=True, help="Input directory with .tex files + critique.md")
    parser.add_argument("--output", required=True, help="Output directory for iterations + final assembly")
    parser.add_argument("--iterations", type=int, default=5, help="Number of iterations (default: 5)")
    parser.add_argument("--chapters", type=str, default="", help="Comma-separated chapter numbers (default: all)")
    parser.add_argument("--resume", action="store_true", help="Resume from last saved state")
    parser.add_argument("--estimate", action="store_true", help="Estimate costs without running")
    parser.add_argument("--writer-model", type=str, default="openai/gpt-5.1", help="Model for section writers")
    parser.add_argument("--lawwama-model", type=str, default="anthropic/claude-opus-4-6", help="Model for Lawwama")
    parser.add_argument("--editor-model", type=str, default="anthropic/claude-sonnet-4-6", help="Model for editors")

    args = parser.parse_args()

    chapters_filter = []
    if args.chapters:
        chapters_filter = [int(c.strip()) for c in args.chapters.split(",")]

    run_pipeline(
        input_dir=args.input,
        output_dir=args.output,
        iterations=args.iterations,
        chapters_filter=chapters_filter,
        resume=args.resume,
        estimate_only=args.estimate,
    )


if __name__ == "__main__":
    main()
