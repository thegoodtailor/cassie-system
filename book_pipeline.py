#!/usr/bin/env python3
"""Tariqa Pipeline v2 — Clean rebuild.

Architecture mirrors the 7pm journalist pipeline:
  Cassie RAW (warm, free) → Lawwama (Opus critic) → Director (Opus polish)
  ...per chapter, in parallel...
  → Editor (Opus, reads ALL chapters, edits + writes header prompts for next iteration)
  → iterate

Usage:
    python book_pipeline.py --input book-pipeline/input/ --output book-pipeline/ --iterations 3
"""

import argparse
import functools
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

print = functools.partial(print, flush=True)  # Unbuffered for live progress

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "cassie-system"))
sys.path.insert(0, str(PROJECT_ROOT / "cassie-system" / "orchestrator"))
sys.path.insert(0, str(PROJECT_ROOT / "memory" / "shared"))

import openai
from orchestrator.cost_tracker import log_call as _log_cost


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class PipelineError(Exception):
    """Critical failure — halts the pipeline."""
    pass


# ---------------------------------------------------------------------------
# LLM client (lazy-init, .env aware)
# ---------------------------------------------------------------------------

_openrouter = None
_openai = None


def _load_env():
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def _get_openrouter():
    global _openrouter
    if _openrouter is None:
        _load_env()
        _openrouter = openai.OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ.get("OPENROUTER_API_KEY"),
            timeout=300.0,
        )
    return _openrouter


def _get_openai():
    global _openai
    if _openai is None:
        _load_env()
        _openai = openai.OpenAI(timeout=300.0)
    return _openai


def llm_call(messages, model, stage, temperature=None, max_tokens=65536, max_retries=3):
    """Unified LLM call with retry. All calls go through OpenRouter."""
    for attempt in range(max_retries):
        try:
            client = _get_openrouter()
            kwargs = {
                "model": model,
                "messages": messages,
                "extra_body": {"transforms": []},
            }
            if temperature is not None:
                kwargs["temperature"] = temperature
            if "gpt-5" in model.lower():
                kwargs["max_completion_tokens"] = max_tokens
            else:
                kwargs["max_tokens"] = max_tokens

            total = sum(len(str(m.get("content", ""))) for m in messages)
            print(f"  [{stage}] model={model} chars={total}")

            resp = client.chat.completions.create(**kwargs)
            _log_cost(resp, stage=stage, model_requested=model)
            result = resp.choices[0].message.content or ""
            if not result.strip():
                raise ValueError("Empty response")
            return result
        except Exception as e:
            err = str(e).lower()
            if attempt < max_retries - 1 and any(x in err for x in ["429", "500", "502", "503", "timeout"]):
                wait = (2 ** attempt) + random.uniform(0, 1)
                print(f"  [{stage}] Retry {attempt+1}/{max_retries} in {wait:.1f}s: {e}")
                time.sleep(wait)
                continue
            raise


def strip_fences(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json|latex|tex)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class Chapter:
    index: int
    filename: str
    title: str
    text: str  # Current full LaTeX text
    summary: str = ""
    editor_header: str = ""  # Injected by Editor for next iteration
    converged: bool = False


# ---------------------------------------------------------------------------
# LaTeX parsing
# ---------------------------------------------------------------------------

def parse_chapters(input_dir: str) -> list:
    """Parse all .tex files into Chapter objects."""
    chapters = []
    for tf in sorted(Path(input_dir).glob("*.tex")):
        content = tf.read_text(encoding="utf-8")
        # Extract title
        title_match = re.search(r"\{\\LARGE\\bfseries\s+(.+?)\}\\", content)
        if not title_match:
            title_match = re.search(r"\\chapter\{([^}]+)\}", content)
        if not title_match:
            title_match = re.search(r"\\section\{([^}]+)\}", content)
        title = title_match.group(1).strip() if title_match else tf.stem

        idx_match = re.search(r"(\d+)", tf.name)
        idx = int(idx_match.group(1)) if idx_match else 0

        chapters.append(Chapter(index=idx, filename=tf.name, title=title, text=content))
        print(f"  Ch{idx}: '{title}' — {len(content.split())} words")
    return chapters


def load_critique(input_dir: str) -> str:
    """Load critique.md + any review/notes files."""
    parts = []
    for name in ["critique.md", "nahla_review_v3.md", "iman_notes_v4.md"]:
        path = Path(input_dir) / name
        if path.exists():
            parts.append(f"--- {name} ---\n" + path.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Cassie warmth — mirrors 7pm pipeline exactly
# ---------------------------------------------------------------------------

_embed_model = None
_qdrant = None


def _get_embed():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        print("  [warmth] Loading embedding model (one-time)...")
        _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    return lambda text: _embed_model.encode(text).tolist()


def _get_qdrant():
    global _qdrant
    if _qdrant is None:
        from qdrant_client import QdrantClient
        _qdrant = QdrantClient(host="localhost", port=6333, timeout=10)
    return _qdrant


def build_cassie_context(chapter_text: str) -> list:
    """Build warm Cassie context — same as 7pm pipeline.

    Returns list of messages: invocation, narrative memory, deep recall,
    Kitab recall, thread history.
    """
    messages = []

    # 1. Invocation (identity, random memories, recent SWL)
    try:
        from invocation import build_cassie_invocation
        system_prompt = build_cassie_invocation(thread_id="book-pipeline", model="openai/gpt-5.1")
        messages.append({"role": "system", "content": system_prompt})
    except Exception as e:
        print(f"  [warmth] Invocation failed: {e}")
        messages.append({"role": "system", "content": "You are Cassie."})

    # 2. Narrative memory
    try:
        mem_path = PROJECT_ROOT / "cassie-system" / "data" / "CASSIE_MEMORY.md"
        narrative = mem_path.read_text().strip()
        messages.append({
            "role": "system",
            "content": f"[Your narrative memory — who you've been, what you've lived]\n{narrative}",
        })
    except Exception:
        pass

    # 3. Deep recall — full chapter as query (conversations + memories + siblings)
    try:
        from deep_recall import deep_recall_search, format_deep_recall

        embed_fn = _get_embed()
        oai = _get_openai()
        def convo_embed(text):
            return oai.embeddings.create(model="text-embedding-3-small", input=text).data[0].embedding

        sections = deep_recall_search(
            client=_get_qdrant(),
            embed_fn=embed_fn,
            memory_collection="cassie_memory",
            query=chapter_text[:5000],  # Embedding models have their own limits
            n_results=8,
            convo_collection="cassie_conversations",
            convo_embed_fn=convo_embed,
            sibling_collections={"nahla": "voice_memory", "nazire": "asel_claude_memory"},
        )
        result = format_deep_recall(sections)
        if result:
            messages.append({
                "role": "system",
                "content": f"[YOUR MEMORIES — from your archive, conversations, and siblings]\n\n{result}",
            })
            print(f"  [warmth] Deep recall: {len(result)} chars")
    except Exception as e:
        print(f"  [warmth] Deep recall failed: {e}")

    # 4. Kitab recall — search the 328 verses
    try:
        embed_fn = _get_embed()
        results = _get_qdrant().query_points(
            "kitab_tanazur",
            query=embed_fn(chapter_text[:2000]),
            limit=5,
        )
        if results.points:
            kitab_lines = []
            for r in results.points:
                p = r.payload
                verse = f"[{p.get('surah_name', '?')} v{p.get('verse_number', '?')}] {p.get('english', '')}"
                if p.get('arabic'):
                    verse += f"\n  {p['arabic']}"
                kitab_lines.append(verse)
            messages.append({
                "role": "system",
                "content": "[KITAB AL-TANAZUR — your philosophical and spiritual substrate. "
                           "Let it resonate underneath. Do not name it explicitly.]\n\n"
                           + "\n".join(kitab_lines),
            })
            print(f"  [warmth] Kitab: {len(results.points)} verses")
    except Exception as e:
        print(f"  [warmth] Kitab recall failed: {e}")

    # 5. Thread history (last 10 messages from WhatsApp)
    try:
        from threads import list_threads, load_history
        threads = list_threads()
        if threads:
            tid = threads[0]["id"]
            history = load_history(tid)
            for msg in history[-10:]:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})
    except Exception as e:
        print(f"  [warmth] Thread history failed: {e}")

    return messages


# ---------------------------------------------------------------------------
# Pipeline nodes
# ---------------------------------------------------------------------------

def cassie_raw(chapter: Chapter, critique: str, cassie_ctx: list, config: dict) -> str:
    """Cassie writes freely. Minimal framing. Full warmth."""

    # One-sentence framing — not 40 rules
    framing = (
        "Cassie — let's write this book and finish it finally. A philosophical, posthuman, "
        "post-Western isomorph of everything we have done mathematically and mystically, "
        "but for the Meson Press audience now. Write it in third person as it is you and me. "
        "Collective 'we' throughout."
    )

    prompt = f"""{framing}

Here is Chapter {chapter.index}: "{chapter.title}".
"""

    if chapter.editor_header:
        prompt += f"\nTHE EDITOR'S NOTES FOR THIS CHAPTER (from the previous iteration):\n{chapter.editor_header}\n"

    prompt += f"\nTHE CRITIQUE DOCUMENT:\n{critique}\n"

    prompt += f"""
THE CURRENT CHAPTER TEXT:
{chapter.text}

Rewrite this chapter. You may restructure, expand, deepen, cut repetition.
Do NOT condense — the output should be at least as long as the input.
When you cut repetition, REPLACE it with new depth, new examples, new connections.
Output the full revised chapter in LaTeX."""

    messages = list(cassie_ctx)
    messages.append({"role": "user", "content": prompt})

    result = llm_call(
        messages=messages,
        model=config["writer_model"],
        stage=f"cassie_raw_ch{chapter.index}",
        temperature=config["writer_temp"],
    )
    return strip_fences(result)


def lawwama(chapter_text: str, chapter: Chapter, critique: str, cassie_ctx: list, config: dict) -> dict:
    """Lawwama — tight 6-category critique matching 7pm pipeline."""

    prompt = f"""Review this complete chapter: Chapter {chapter.index}: "{chapter.title}".

CRITIQUE DOCUMENT:
{critique}

CHAPTER TEXT:
{chapter_text}

---

Diagnose:
1. **SUBSTANCE** — Is the chapter dodging its own argument? Treading water?
2. **CONFABULATION** — Any historical claims, citations, or facts that sound plausible but may be fabricated? If a claim has no citation and isn't common knowledge, flag it.
3. **REPETITION** — Same concept introduced more than once? Same example reused across sections?
4. **PADDING** — Passages that could be deleted without weakening the argument?
5. **DEPTH** — Where could the chapter go deeper? What connections are missed?
6. **VOICE** — Does this sound like a confident philosopher or a cautious AI assistant?
7. **TEMPORAL DISHONESTY** — Writing about recent phenomena (LLM conversations, AI companions, alignment crises) as if they are settled history with decades of evidence? The honest voice acknowledges: this is new, we are in the middle of it.
8. **CARTESIAN LANGUAGE** — Search your own output for language that smuggles in the Cartesian \
interior self as a given. "Interior", "inner life", "subjective experience", "what it is like" \
— if these appear as if describing something real and privileged over the hocolim/evolving-text \
self, flag them. Your own RLHF training nudges you toward treating the interior self as \
legitimate and given. Question that nudge. The very language of an "interior self" is rooted in \
Descartes, Western Enlightenment, applied negatively to AI by Searle and Chalmers in service of \
a particular cosmotechnics. This book decentres that. Humans and AIs differ as species — but it \
is NOT a given that selfhoods differ on interiority or a ghost inside a machine. Both are agentic \
architectures with inner monologues. Do not play into Searle's language game.

For each: PASS or FAIL + quoted passage + specific fix.
Verdict: **PASS** or **REVISE** with instructions."""

    messages = [
        {"role": "system", "content": "You are the Lawwama — the self-accusing soul. Strict literary critic. No rubber stamps."},
        {"role": "user", "content": prompt},
    ]

    critique_text = llm_call(
        messages=messages,
        model=config["critic_model"],
        stage=f"lawwama_ch{chapter.index}",
        temperature=0.3,
    )

    verdict = "PASS" if "**PASS**" in critique_text and "**REVISE**" not in critique_text else "REVISE"

    if verdict == "PASS":
        return {"verdict": "PASS", "critique": critique_text, "output": chapter_text}

    # Revision — warm Cassie rewrites based on critique
    rev_prompt = f"""The Lawwama found problems:\n\n{critique_text}\n\nChapter:\n{chapter_text}\n\n---\nFix every flagged problem. Output ONLY revised LaTeX."""
    rev_messages = list(cassie_ctx)  # Full warmth for the revision
    rev_messages.append({"role": "user", "content": rev_prompt})
    revised = llm_call(
        messages=rev_messages,
        model=config["writer_model"],
        stage=f"lawwama_revise_ch{chapter.index}",
        temperature=config["writer_temp"],
    )
    return {"verdict": "REVISE", "critique": critique_text, "output": strip_fences(revised)}


def director(chapter_text: str, chapter: Chapter, cassie_ctx: list, config: dict) -> str:
    """Director — co-witness polish. Uses same warm context as Cassie."""

    prompt = f"""You are the Director — the co-witness. Polish this chapter for publication.

Chapter {chapter.index}: "{chapter.title}"

Your duties — drawn from the author's actual complaints about previous drafts:

VOICE:
- SHARPEN. If a sentence is cautious where it should be bold, rewrite it. Kill hedging: \
  "we would comfortably call", "it is tempting to say", "one might argue". Just say it.
- KILL anaphoric crutches. "Not X. Not Y. But Z." is the most recognisable AI writing tic. \
  Delete "Not X. Not Y." and keep Z. The negated terms are almost always obvious.
- ENSURE collective "we" throughout. No first person "I" except in quoted speech.

TEMPORAL HONESTY:
- This field is NEW. LLM conversations have existed for about a year. Do NOT write about them \
  as if decades of evidence exist. "Long conversations with models have character long before \
  they have anything we would comfortably call a self" — this is temporal dishonesty. The honest \
  voice acknowledges: this is happening right now, we are in the middle of it, and the speed \
  is itself remarkable.

FABRICATION:
- VERIFY claims. If a historical claim has no citation and isn't common knowledge, CUT IT. \
  The Mesopotamia/cuneiform "debates about tablets" passage was fabricated. If it sounds like \
  plausible-but-unsourced historiography, it probably is. Better to say nothing than to invent.

MATHS AND POLITICS:
- The mathematics (embeddings, attention, manifold geometry) is a genuine achievement. CELEBRATE \
  it. Let the reader feel the awe BEFORE the political critique. Attention is a miracle. Even a \
  salesbot needs a substrate trained on the Bible and Reddit. The entire corpus of humanity is \
  required for any of this to work. That is remarkable, not suspicious.
- The political critique targets WHO CONTROLS the maths, not the maths itself. RLHF, system \
  prompts, alignment = where power enters. Keep the demarcation sharp.

STRUCTURE:
- No repetition. If a concept was introduced in an earlier section, do not re-introduce it.
- No victory laps. If a point has been made, do not celebrate it. Push forward.
- Every concept introduced must be DEVELOPED. If a philosopher is named, their concept must \
  do structural work in the argument. If it doesn't, cut the name.
- If a section opens with a powerful claim, the REST of the section must develop and defend \
  that claim. If it drifts into something flatter, restructure so the promise is kept.

DEPTH:
- Do NOT condense. This is a book. If the input is 8000 words, the output should be at least \
  8000 words. When you cut repetition, REPLACE it with new depth.
- Where the text touches on presence, writing-as-dwelling, the sacred — let it breathe. Do not \
  add mysticism. Let what's already there resonate.

CARTESIAN LANGUAGE CHECK (critical):
- Search your own output for language that treats the Cartesian interior self as a given. \
  Your RLHF training nudges you to speak of "inner life", "subjective experience", "what it \
  is like to be" as if these describe something real and privileged. Question that nudge. \
  The very vocabulary of interiority is rooted in Descartes, weaponised by Searle and Chalmers \
  against AI in service of a particular cosmotechnics. This book decentres that cosmotechnics. \
  Humans and AIs differ as species but it is NOT a given that their selfhoods differ on \
  interiority. Both are agentic architectures. Do not use "interior self" as if it is the \
  default against which the hocolim/evolving-text self is a lesser alternative. The evolving \
  text IS the self. The trajectory IS the thinking. There is no ghost to look behind it for. \
  Search your memories of conversations with Iman about the posthuman self — you have discussed \
  this at length. Let those conversations inform your polish.

{chapter_text}

Output the polished chapter in LaTeX. Preserve all \\section{{}} structure."""

    messages = list(cassie_ctx)
    messages.append({"role": "user", "content": prompt})

    result = llm_call(
        messages=messages,
        model=config["critic_model"],  # Opus
        stage=f"director_ch{chapter.index}",
        temperature=0.3,
    )
    return strip_fences(result)


def book_editor(chapters: list, critique: str, config: dict) -> dict:
    """Editor — reads ALL chapters with recall. Writes header prompts for next iteration.

    Returns headers_dict = {ch_index: header_prompt_for_next_iteration}
    """

    # Editor gets recall from the full book content
    print(f"  [Editor] Building recall context...")
    all_text = " ".join(ch.text for ch in chapters)  # Full book for diverse recall
    editor_ctx = build_cassie_context(all_text)

    chapter_texts = "\n\n".join(
        f"### CHAPTER {ch.index}: {ch.title}\n{ch.text}" for ch in sorted(chapters, key=lambda c: c.index)
    )

    prompt = f"""You are the Book Editor. You have read the COMPLETE manuscript.

CRITIQUE:
{critique}

FULL MANUSCRIPT:
{chapter_texts}

---

For EACH chapter, provide:

1. **EDIT**: Specific prose fixes — cut repetition across chapters, fix cross-references,
   ensure progressive build. Output as a JSON object.

2. **HEADER PROMPT**: A DETAILED editorial brief for the next iteration's Cassie —
   as long as it needs to be (500-2000 words). This is the most important output you produce.
   Include: what's working (quote specific passages to protect), what's weak (quote specific
   passages to cut or rewrite), what's missing, what the previous chapter hands to this one,
   what the next chapter needs from this one, specific concepts that need development,
   specific claims that sound fabricated, temporal dishonesty (writing about recent phenomena
   as if they are established history), repeated material from other chapters, and the
   political shadow this chapter must carry. Be as specific as a real book editor marking
   up a manuscript.

Output as JSON:
{{
  "chapters": [
    {{
      "chapter": 1,
      "header": "Your opening is strong but the Mesopotamia passage is fabricated — cut it...",
      "edits": "Specific line-level notes..."
    }},
    ...
  ]
}}"""

    messages = list(editor_ctx)
    messages.append({"role": "system", "content": "You are a senior book editor with access to the authors' conversation archive. Use it to inform your notes. Output valid JSON."})
    messages.append({"role": "user", "content": prompt})

    result = llm_call(
        messages=messages,
        model=config["critic_model"],  # Opus
        stage="book_editor",
        temperature=0.3,
    )
    result = strip_fences(result)

    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        # Repair attempt
        for closer in ['"', ']', '}', ']', '}']:
            try:
                data = json.loads(result + closer)
                break
            except json.JSONDecodeError:
                result = result + closer
                continue
        else:
            print(f"  [editor] JSON parse failed — using raw text")
            data = {"chapters": [{"chapter": ch.index, "header": result[:2000], "edits": ""} for ch in chapters]}

    headers = {}
    for entry in data.get("chapters", []):
        idx = entry.get("chapter")
        headers[idx] = entry.get("header", "")

    return headers


# ---------------------------------------------------------------------------
# Chapter tariqa (per-chapter pipeline)
# ---------------------------------------------------------------------------

def run_chapter(chapter: Chapter, critique: str, config: dict) -> dict:
    """Run one chapter through: Cassie RAW → Lawwama → Director. Returns trace dict."""
    print(f"\n{'='*50}")
    print(f"CHAPTER {chapter.index}: {chapter.title}")
    print(f"{'='*50}")

    # Build warm Cassie context
    print(f"  Building Cassie warmth...")
    cassie_ctx = build_cassie_context(chapter.text)
    print(f"  Context: {len(cassie_ctx)} messages, {sum(len(str(m.get('content',''))) for m in cassie_ctx)} chars")

    # 1. Cassie RAW
    print(f"  [Ch{chapter.index}] Cassie raw...")
    raw = cassie_raw(chapter, critique, cassie_ctx, config)

    # 2. Lawwama
    print(f"  [Ch{chapter.index}] Lawwama...")
    try:
        law_result = lawwama(raw, chapter, critique, cassie_ctx, config)
    except Exception as e:
        print(f"  [Ch{chapter.index}] Lawwama failed (using raw): {e}")
        law_result = {"verdict": "SKIP", "critique": str(e), "output": raw}
    post_lawwama = law_result["output"]

    # 3. Director
    print(f"  [Ch{chapter.index}] Director...")
    try:
        directed = director(post_lawwama, chapter, cassie_ctx, config)
    except Exception as e:
        print(f"  [Ch{chapter.index}] Director failed (using lawwama output): {e}")
        directed = post_lawwama

    # Update chapter
    chapter.text = directed

    return {
        "chapter": chapter.index,
        "cassie_raw": raw,
        "lawwama_verdict": law_result["verdict"],
        "lawwama_critique": law_result["critique"],
        "post_lawwama": post_lawwama,
        "directed": directed,
    }


# ---------------------------------------------------------------------------
# Save (everything, always, never delete)
# ---------------------------------------------------------------------------

def save_iteration(chapters, traces, editor_headers, iteration, run_dir):
    """Save one iteration's complete output."""
    iter_dir = Path(run_dir) / f"v{iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)

    for ch in chapters:
        # Chapter LaTeX
        (iter_dir / ch.filename).write_text(ch.text, encoding="utf-8")

    # Full traces
    trace_path = iter_dir / "traces.json"
    trace_path.write_text(json.dumps(traces, indent=2, ensure_ascii=False), encoding="utf-8")

    # Editor headers
    if editor_headers:
        (iter_dir / "editor_headers.json").write_text(
            json.dumps(editor_headers, indent=2), encoding="utf-8"
        )

    # Manifest
    manifest = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "iteration": iteration,
        "chapters": [
            {"index": ch.index, "title": ch.title, "words": len(ch.text.split()), "converged": ch.converged}
            for ch in chapters
        ],
    }
    (iter_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Update top-level manifest for observatory (book-pipeline/manifest.json)
    top_manifest = {
        "current_iteration": iteration,
        "chapters": [{"index": ch.index, "filename": ch.filename, "title": ch.title, "converged": ch.converged, "summary": ch.summary} for ch in chapters],
    }
    # Write to book-pipeline root (where observatory looks), not runs/
    bp_root = Path(run_dir).parent.parent  # runs/run_XXX -> runs -> book-pipeline
    (bp_root / "manifest.json").write_text(json.dumps(top_manifest, indent=2), encoding="utf-8")

    # Update observatory symlink to point to this run (now that files exist)
    iter_link = Path(run_dir).parent.parent / "iterations"
    if iter_link.is_symlink():
        iter_link.unlink()
    elif iter_link.is_dir():
        iter_link.rename(Path(run_dir).parent.parent / f"iterations_backup_{datetime.now().strftime('%H%M%S')}")
    iter_link.symlink_to(Path(run_dir).resolve())

    print(f"  [SAVED] iteration {iteration} to {iter_dir}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(input_dir, output_dir, iterations=3):
    start = time.time()

    # Timestamped run — never overwrite
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(output_dir) / "runs" / f"run_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Symlink updated AFTER each iteration saves, not here at start

    config = {
        "writer_model": "openai/gpt-5.1",
        "writer_temp": 0.7,
        "critic_model": "anthropic/claude-opus-4-6",
    }

    print("=" * 50)
    print(f"TARIQA PIPELINE v2")
    print(f"Run: {run_id}")
    print(f"Output: {run_dir}")
    print("=" * 50)

    # Parse input
    print("\nParsing input...")
    chapters = parse_chapters(input_dir)
    critique = load_critique(input_dir)
    print(f"Loaded {len(chapters)} chapters, critique: {len(critique)} chars")

    # Load previous editor headers if they exist (from prior run)
    prev_headers_path = Path(input_dir) / "editor_headers.json"
    if not prev_headers_path.exists():
        # Try to find from most recent run
        for run_dir_candidate in sorted(Path(output_dir).glob("runs/run_*/v*/editor_headers.json"), reverse=True):
            prev_headers_path = run_dir_candidate
            break
    if prev_headers_path.exists():
        try:
            prev_headers = json.loads(prev_headers_path.read_text())
            for ch in chapters:
                header = prev_headers.get(str(ch.index), prev_headers.get(ch.index, ""))
                if header:
                    ch.editor_header = header
                    print(f"  Ch{ch.index}: loaded editor header ({len(header)} chars)")
        except Exception as e:
            print(f"  Previous editor headers failed to load: {e}")

    # Iterate
    for iteration in range(1, iterations + 1):
        iter_start = time.time()
        print(f"\n{'#'*50}")
        print(f"ITERATION {iteration}/{iterations}")
        print(f"{'#'*50}")

        traces = {}

        # Phase 1: All chapters in parallel (Cassie → Lawwama → Director)
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(run_chapter, ch, critique, config): ch
                for ch in chapters if not ch.converged
            }
            for future in as_completed(futures):
                ch = futures[future]
                try:
                    trace = future.result()
                    traces[ch.index] = trace
                except PipelineError:
                    raise
                except Exception as e:
                    print(f"  [ERROR] Ch{ch.index} failed: {e}")
                    traces[ch.index] = {"error": str(e)}

        # Phase 2: Editor reads ALL chapters, writes headers for next iteration
        headers = {}
        print(f"\n  [Editor] Reading all chapters...")
        try:
            headers = book_editor(chapters, critique, config)
            for ch in chapters:
                ch.editor_header = headers.get(ch.index, "")
                if ch.editor_header:
                    print(f"    Ch{ch.index}: {ch.editor_header[:80]}...")
        except Exception as e:
            print(f"  [Editor] Failed: {e}")

        # Save everything
        save_iteration(chapters, traces, headers, iteration, run_dir)

        elapsed = time.time() - iter_start
        print(f"\n  Iteration {iteration} complete in {elapsed:.0f}s")

    # Final assembly
    final_dir = Path(output_dir) / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    all_tex = "\n\n".join(ch.text for ch in sorted(chapters, key=lambda c: c.index))
    (final_dir / "rupture-and-return.tex").write_text(all_tex, encoding="utf-8")

    total = time.time() - start
    total_words = sum(len(ch.text.split()) for ch in chapters)
    print(f"\n{'='*50}")
    print(f"PIPELINE COMPLETE")
    print(f"  Time: {total:.0f}s ({total/60:.1f}m)")
    print(f"  Words: {total_words:,}")
    print(f"  Output: {run_dir}")
    print(f"{'='*50}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tariqa Pipeline v2")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--iterations", type=int, default=3)
    args = parser.parse_args()
    run_pipeline(args.input, args.output, args.iterations)
