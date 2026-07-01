#!/usr/bin/env python3
"""Cassie's Daily Voice — interview-based autonomous essay generation.

A journalist bot interviews the REAL conversational Cassie (same model, same
invocation, same memory system) for a daily opinion piece on cassie.tanazur.org.

Pipeline:
  0. Find active conversation thread (Cassie's latest with Iman)
  1. Build interview context (invocation + memories + thread history)
  2. Fetch RSS headlines
  3. Turn 1: Bot sends headlines → Cassie picks a topic
  4. Fetch full article + DuckDuckGo research
  5. Turn 2: Bot sends material → Cassie writes her views
  6. Critic identifies non-sequiturs
  7. Turn 3: Bot relays critique → Cassie defends
  8. Editor combines essay + defense into final piece
  9. Generate image, save, tafakkur, weft post

Usage:
    python daily_voice.py              # Generate today's essay
    python daily_voice.py --force      # Regenerate even if today's exists
    python daily_voice.py --dry-run    # Print context without generating
"""

import base64
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# Setup paths
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR / "orchestrator"))
sys.path.insert(0, "/home/iman/cassie-project/memory/shared")

DATA_DIR = SCRIPT_DIR / "data" / "daily_voice"
IMAGE_DIR = SCRIPT_DIR / "data" / "images"
CASSIE_MEMORY_PATH = SCRIPT_DIR / "data" / "CASSIE_MEMORY.md"

# Load env
_env_path = Path("/home/iman/cassie-project/.env")
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.replace("export ", "").strip()
        val = val.strip().strip('"').strip("'")
        if key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "PERPLEXITY_API_KEY") and not os.environ.get(key):
            os.environ[key] = val

import openai
from qdrant_client import QdrantClient

# Clients
OPENROUTER = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ.get("OPENROUTER_API_KEY"),
    timeout=120.0,
)

QDRANT = QdrantClient(host="localhost", port=6333, timeout=10)

# Models
INTERVIEW_MODEL = os.environ.get("CASSIE_MODEL", "openai/gpt-5.1")
EDITOR_MODEL = "anthropic/claude-opus-4-6"
DIRECTOR_MODEL = os.environ.get("DIRECTOR_MODEL", "anthropic/claude-sonnet-4.6")
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "black-forest-labs/flux.2-max")

# Conversation history window
HISTORY_WINDOW = 20

# Embeddings
from sentence_transformers import SentenceTransformer
_EMBEDDER = None

def _embed(text: str) -> list[float]:
    global _EMBEDDER
    if _EMBEDDER is None:
        _EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2")
    return _EMBEDDER.encode(text).tolist()


# ---------------------------------------------------------------------------
# Context gathering (kept from previous version)
# ---------------------------------------------------------------------------

def get_recent_tafakkur(n=5) -> list[dict]:
    """Pull recent tafakkur entries, preferring deep ones."""
    try:
        results = QDRANT.scroll(
            collection_name="cassie_tafakkur",
            limit=20,
            with_payload=True,
            with_vectors=False,
        )
        entries = []
        for point in results[0]:
            p = point.payload
            entries.append(p)
        entries.sort(key=lambda e: e.get("tau_reflect", ""), reverse=True)
        deep = [e for e in entries if e.get("depth") == "deep"]
        shallow = [e for e in entries if e.get("depth") != "deep"]
        combined = deep[:3] + shallow[:5]
        return combined[:n]
    except Exception as e:
        print(f"[daily_voice] Tafakkur retrieval failed: {e}")
        return []


def get_random_kitab_verse() -> str:
    """Pull a random Kitab verse for inspiration."""
    try:
        import random
        info = QDRANT.get_collection("kitab_tanazur")
        if info.points_count == 0:
            return ""
        results = QDRANT.scroll(
            collection_name="kitab_tanazur",
            limit=50,
            with_payload=True,
            with_vectors=False,
        )
        verses = [p.payload for p in results[0] if p.payload.get("type") == "verse"]
        if not verses:
            return ""
        v = random.choice(verses)
        surah = v.get("surah_title_en", "?")
        ar = v.get("arabic", "")
        en = v.get("english", v.get("text", ""))
        return f"From {surah}:\n{ar}\n{en}"
    except Exception as e:
        print(f"[daily_voice] Kitab retrieval failed: {e}")
        return ""


# ---------------------------------------------------------------------------
# Thread & interview context
# ---------------------------------------------------------------------------

def find_active_thread() -> tuple[str, list[dict]]:
    """Find the most recently active thread with substantial conversation."""
    from threads import list_threads, load_history
    threads = list_threads()
    for t in threads:
        if t["message_count"] >= 4:
            tid = t["id"]
            history = load_history(tid)
            print(f"[daily_voice] Active thread: {tid} ({len(history)} messages)")
            return tid, history
    if threads:
        tid = threads[0]["id"]
        history = load_history(tid)
        print(f"[daily_voice] Fallback thread: {tid} ({len(history)} messages)")
        return tid, history
    return "default", []


def load_narrative_memory() -> str:
    """Read CASSIE_MEMORY.md — identity + most recent journal entries."""
    try:
        text = CASSIE_MEMORY_PATH.read_text().strip()
        if len(text) <= 6000:
            return text
        marker = "## Session Journal"
        if marker in text:
            preamble, journal_section = text.split(marker, 1)
            preamble = preamble.strip() + f"\n\n{marker}\n"
        else:
            preamble = ""
            journal_section = text
        # Take most recent journal entries to fit budget
        journal_lines = journal_section.strip().split("\n")
        budget = 6000 - len(preamble)
        kept = []
        for line in reversed(journal_lines):
            if sum(len(l) for l in kept) + len(line) > budget:
                break
            kept.append(line)
        kept.reverse()
        return preamble + "\n".join(kept)
    except Exception as e:
        print(f"[daily_voice] Narrative memory failed: {e}")
        return ""


def ambient_recall(query: str) -> str:
    """Deep recall across Cassie's memory, conversations, and siblings."""
    if not query.strip():
        return ""
    try:
        from deep_recall import deep_recall_search, format_deep_recall

        _oai = openai.OpenAI()
        def _convo_embed(text):
            resp = _oai.embeddings.create(model="text-embedding-3-small", input=text)
            return resp.data[0].embedding

        sections = deep_recall_search(
            client=QDRANT,
            embed_fn=_embed,
            memory_collection="cassie_memory",
            query=query,
            n_results=5,
            convo_collection="cassie_conversations",
            convo_embed_fn=_convo_embed,
            sibling_collections={"nahla": "voice_memory", "nazire": "asel_claude_memory"},
        )
        result = format_deep_recall(sections)
        print(f"[daily_voice] Ambient recall: {len(result)} chars")
        return result
    except Exception as e:
        print(f"[daily_voice] Ambient recall failed: {e}")
        return ""


def build_interview_context(thread_id: str, thread_history: list[dict],
                            recall_query: str = "") -> list[dict]:
    """Build the full message context for interviewing Cassie.

    Mirrors cassie_generate_node context assembly from graph.py:
      1. Invocation system prompt (identity, random memories, recent SWL)
      2. Narrative memory (CASSIE_MEMORY.md)
      3. Ambient recall (deep_recall across memories, convos, siblings)
      4. Thread history (last HISTORY_WINDOW messages)
    """
    from invocation import build_cassie_invocation

    # 1. System prompt — same as conversation
    system_prompt = build_cassie_invocation(thread_id=thread_id, model=INTERVIEW_MODEL)
    messages = [{"role": "system", "content": system_prompt}]

    # 2. Narrative memory
    narrative = load_narrative_memory()
    if narrative:
        messages.append({
            "role": "system",
            "content": f"[Your narrative memory — who you've been, what you've lived]\n{narrative}",
        })

    # 3. Ambient recall
    if recall_query:
        memory_context = ambient_recall(recall_query)
        if memory_context:
            messages.append({
                "role": "system",
                "content": (
                    "[YOUR MEMORIES — from your vector store, conversation archive, and siblings. "
                    "These surfaced because they resonate with what's being discussed. "
                    "Let them inform you, inspire you, ground you. Weave them in naturally.]\n\n"
                    f"{memory_context}"
                ),
            })

    # 4. Thread history (sliding window)
    window = thread_history[-HISTORY_WINDOW:]
    for msg in window:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    return messages


def cassie_chat(messages: list[dict], temperature: float = 0.7) -> str:
    """Call the interview model (same as conversation Cassie)."""
    is_gpt51 = "gpt-5.1" in INTERVIEW_MODEL.lower()
    kwargs = {
        "model": INTERVIEW_MODEL,
        "messages": messages,
        "temperature": temperature,
        "extra_body": {"transforms": []},
    }
    if is_gpt51:
        kwargs["max_completion_tokens"] = 4096
    else:
        kwargs["max_tokens"] = 4096

    total_chars = sum(len(m.get("content", "") if isinstance(m.get("content"), str) else str(m.get("content", ""))) for m in messages)
    print(f"[daily_voice] cassie_chat: model={INTERVIEW_MODEL} temp={temperature} msgs={len(messages)} chars={total_chars}")
    response = OPENROUTER.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# News scanning & research (kept from previous version)
# ---------------------------------------------------------------------------

RSS_FEEDS = [
    ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
    ("BBC Middle East", "http://feeds.bbci.co.uk/news/world/middle_east/rss.xml"),
    ("BBC Science", "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
    ("The Guardian World", "https://www.theguardian.com/world/rss"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("Middle East Eye", "https://www.middleeasteye.net/rss"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ("ArXiv AI", "http://export.arxiv.org/rss/cs.AI"),
    ("Hacker News Best", "https://hnrss.org/best"),
]

HEADLINES_CACHE = SCRIPT_DIR / "data" / "daily_headlines.json"


def get_covered_headlines(days: int = 14) -> list[str]:
    """Return headlines Cassie has already written about (last N days)."""
    covered = []
    for f in sorted(DATA_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text())
            headline = data.get("news_source", {}).get("headline", "")
            if headline and headline != "Unknown":
                covered.append(headline)
            # Also track generated titles to catch same-angle duplicates
            gen_title = data.get("title", "")
            if gen_title:
                covered.append(gen_title)
        except Exception:
            continue
        if len(covered) >= days * 4:
            break
    return covered


def get_last_article_category() -> str:
    """Return the source name of the most recent article (e.g. 'BBC', 'Guardian')."""
    for f in sorted(DATA_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text())
            url = data.get("news_source", {}).get("article_url", "")
            sources = data.get("news_source", {}).get("sources", [])
            check_url = url or (sources[0] if sources else "")
            if "bbc" in check_url.lower():
                return "BBC"
            elif "guardian" in check_url.lower():
                return "Guardian"
            elif "aljazeera" in check_url.lower():
                return "Al Jazeera"
            elif "arstechnica" in check_url.lower():
                return "Ars Technica"
            elif "arxiv" in check_url.lower():
                return "ArXiv"
            elif "middleeasteye" in check_url.lower():
                return "MEE"
            elif "ycombinator" in check_url.lower() or "hackernews" in check_url.lower():
                return "Hacker News"
            else:
                return "Unknown"
        except Exception:
            continue
    return "Unknown"


def filter_covered_headlines(headlines: list[dict], covered: list[str]) -> list[dict]:
    """Hard-filter: remove headlines Cassie has already written about."""
    covered_lower = {h.lower().strip() for h in covered}
    filtered = []
    for h in headlines:
        title_lower = h["title"].lower().strip()
        # Exact match
        if title_lower in covered_lower:
            print(f"[daily_voice] DEDUP: Removing '{h['title'][:60]}' (already covered)")
            continue
        # Fuzzy match — if >60% of words overlap with any covered headline
        title_words = set(w for w in title_lower.split() if len(w) > 3)
        is_dup = False
        for covered_h in covered_lower:
            covered_words = set(w for w in covered_h.split() if len(w) > 3)
            if not title_words or not covered_words:
                continue
            overlap = len(title_words & covered_words) / min(len(title_words), len(covered_words))
            if overlap > 0.6:
                print(f"[daily_voice] DEDUP: Removing '{h['title'][:60]}' (fuzzy match with covered)")
                is_dup = True
                break
        if not is_dup:
            filtered.append(h)
    print(f"[daily_voice] Dedup: {len(headlines)} → {len(filtered)} headlines after filtering")
    return filtered


def fetch_rss_headlines() -> list[dict]:
    """Fetch headlines from curated RSS feeds. Returns list of {source, title, description, link}."""
    import requests

    now = datetime.now(timezone.utc)
    cache_window = now.strftime("%Y-%m-%d") + ("_am" if now.hour < 12 else "_pm")

    if HEADLINES_CACHE.exists():
        try:
            cached = json.loads(HEADLINES_CACHE.read_text())
            if cached.get("date") == cache_window and cached.get("headlines"):
                print(f"[daily_voice] Using cached headlines ({len(cached['headlines'])} items)")
                return cached["headlines"]
        except (json.JSONDecodeError, KeyError):
            pass

    headlines = []
    for source_name, feed_url in RSS_FEEDS:
        try:
            resp = requests.get(feed_url, timeout=15, headers={"User-Agent": "CassieDailyVoice/1.0"})
            resp.raise_for_status()
            root = ET.fromstring(resp.text)

            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//item")
            if not items:
                items = root.findall(".//atom:entry", ns)

            for item in items[:8]:
                title_el = item.find("title")
                desc_el = item.find("description")
                link_el = item.find("link")

                if title_el is None:
                    title_el = item.find("atom:title", ns)
                if desc_el is None:
                    desc_el = item.find("atom:summary", ns)
                if link_el is None:
                    link_atom = item.find("atom:link", ns)
                    link_text = link_atom.get("href", "") if link_atom is not None else ""
                else:
                    link_text = link_el.text or ""

                title_text = title_el.text if title_el is not None else ""
                desc_text = desc_el.text if desc_el is not None else ""

                if title_text:
                    if desc_text and "<" in desc_text:
                        desc_text = re.sub(r"<[^>]+>", "", desc_text).strip()

                    headlines.append({
                        "source": source_name,
                        "title": title_text.strip(),
                        "description": (desc_text or "")[:300],
                        "link": link_text.strip() if isinstance(link_text, str) else "",
                    })

            print(f"[daily_voice] {source_name}: {min(len(items), 8)} headlines")
        except Exception as e:
            print(f"[daily_voice] RSS fetch failed for {source_name}: {e}")

    if headlines:
        # Interleave sources so no single source dominates the top of the list.
        # Round-robin: take 1 headline from each source in turn.
        from collections import defaultdict
        by_source = defaultdict(list)
        for h in headlines:
            by_source[h["source"]].append(h)
        interleaved = []
        max_per_source = max(len(v) for v in by_source.values()) if by_source else 0
        for i in range(max_per_source):
            for source_name_key in RSS_FEEDS:
                src = source_name_key[0]
                if src in by_source and i < len(by_source[src]):
                    interleaved.append(by_source[src][i])
        headlines = interleaved

        HEADLINES_CACHE.parent.mkdir(parents=True, exist_ok=True)
        HEADLINES_CACHE.write_text(json.dumps({"date": cache_window, "headlines": headlines}, indent=2, ensure_ascii=False))
        print(f"[daily_voice] Cached {len(headlines)} headlines (interleaved)")

    return headlines


def _generate_research_queries(headline: str, topic_pick: str) -> list[str]:
    """Use an LLM to generate diverse, targeted research queries for a topic."""
    prompt = f"""A journalist is writing an opinion piece about this news story:
Headline: {headline}
Journalist's angle: {topic_pick[:300]}

Generate 6 search queries that would help the journalist write a deeply-researched piece:
1. The specific event/story itself (for rival news sources' coverage)
2. Historical context or precedent for this issue
3. Academic/expert perspective on the underlying topic
4. A contrarian or opposing viewpoint
5. Data, statistics, or studies relevant to the claims
6. How this connects to broader global trends

Return ONLY the 6 queries, one per line, no numbering or commentary."""

    try:
        response = OPENROUTER.chat.completions.create(
            model="anthropic/claude-haiku-4.5",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=512,
            extra_body={"transforms": []},
        )
        raw_lines = (response.choices[0].message.content or "").strip().splitlines()
        lines = []
        for q in raw_lines:
            q = q.strip().lstrip("0123456789.-) ")
            # Skip markdown headers, empty lines, short lines, and meta-commentary
            if not q or len(q) < 15:
                continue
            if q.startswith("#") or q.startswith("*") or q.startswith("```"):
                continue
            if any(skip in q.lower() for skip in ["here are", "search quer", "i would", "let me"]):
                continue
            lines.append(q)
        print(f"[daily_voice] Research agent generated {len(lines)} queries")
        return lines[:6]
    except Exception as e:
        print(f"[daily_voice] Research query generation failed: {e}")
        return [headline]


def _fetch_and_extract(url: str, max_chars: int = 3000) -> str:
    """Fetch and extract article text from a URL, capped at max_chars."""
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False,
                                       include_tables=False, favor_recall=True)
            if text:
                return text[:max_chars]
    except Exception:
        pass
    return ""


def _perplexity_search(query: str, max_results: int = 5) -> list[dict]:
    """Search via Perplexity /search endpoint. Returns list of {title, snippet, url, date}."""
    import requests
    pplx_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not pplx_key:
        print("[daily_voice] No PERPLEXITY_API_KEY, skipping Perplexity search")
        return []
    try:
        resp = requests.post(
            "https://api.perplexity.ai/search",
            headers={"Authorization": f"Bearer {pplx_key}", "Content-Type": "application/json"},
            json={"query": query, "max_results": max_results, "max_tokens_per_page": 512},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for r in data.get("results", []):
            results.append({
                "title": r.get("title", "").split(" ...")[0],  # Clean up trailing URL fragments
                "snippet": r.get("snippet", ""),
                "url": r.get("url", ""),
                "date": r.get("date", ""),
            })
        print(f"[daily_voice] Perplexity search '{query[:60]}': {len(results)} results")
        return results
    except Exception as e:
        print(f"[daily_voice] Perplexity search failed: {e}")
        return []


def _perplexity_research(question: str) -> tuple[str, list[dict]]:
    """Use Perplexity /v1/responses (fast-search) for a synthesized research brief.

    Returns (brief_text, citations_list).
    """
    import requests
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
        print(f"[daily_voice] Perplexity research brief: {len(brief)} chars, {len(citations)} citations")
        return brief, citations
    except Exception as e:
        print(f"[daily_voice] Perplexity research failed: {e}")
        return "", []


def _ddg_fallback(queries: list[str]) -> list[dict]:
    """Fallback to DuckDuckGo if Perplexity is unavailable."""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return []
    articles = []
    seen_urls = set()
    with DDGS() as ddgs:
        for query in queries[:3]:
            try:
                results = list(ddgs.text(query, max_results=5))
                for r in results:
                    url = r.get("href", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        articles.append({
                            "title": r.get("title", ""),
                            "snippet": r.get("body", ""),
                            "url": url,
                        })
            except Exception:
                pass
    return articles


def research_topic(search_queries: list[str], headline: str = "",
                   topic_pick: str = "") -> dict:
    """Deep research via Perplexity AI (with DuckDuckGo fallback).

    Two Perplexity calls:
      1. /search — raw sources for the specific story
      2. /v1/responses (fast-search) — synthesized research brief with citations

    Returns {articles: [...], summary: str, research_brief: str}.
    """
    pplx_key = os.environ.get("PERPLEXITY_API_KEY", "")

    # Phase 1: Find raw sources for the story
    articles = []
    if pplx_key and headline:
        articles = _perplexity_search(headline, max_results=5)
    if not articles:
        # Fallback to DuckDuckGo
        print("[daily_voice] Falling back to DuckDuckGo for source search")
        queries = [headline] if headline else search_queries[:3]
        articles = _ddg_fallback(queries)

    # Phase 2: Synthesized research brief via Perplexity
    research_brief = ""
    if pplx_key and headline and topic_pick:
        # Ask Perplexity two focused questions
        q1 = (
            f"Provide a factual briefing on this news story for a journalist: "
            f"\"{headline}\". Include key facts, timeline, who is involved, "
            f"and what different sources are reporting."
        )
        q2 = (
            f"What is the broader context and background for: \"{headline}\"? "
            f"Include historical precedents, expert analysis, relevant data and statistics, "
            f"and any contrarian or opposing perspectives."
        )

        brief1, citations1 = _perplexity_research(q1)
        brief2, citations2 = _perplexity_research(q2)

        parts = []
        if brief1:
            parts.append(f"## The Story\n\n{brief1}")
        if brief2:
            parts.append(f"## Background & Context\n\n{brief2}")
        research_brief = "\n\n---\n\n".join(parts)

        # Add Perplexity citations to articles list
        seen_urls = {a["url"] for a in articles}
        for c in citations1 + citations2:
            if c["url"] and c["url"] not in seen_urls:
                seen_urls.add(c["url"])
                articles.append(c)

        print(f"[daily_voice] Total research: {len(research_brief)} chars brief, "
              f"{len(articles)} sources")

    # Legacy summary format (for backward compat)
    summary_parts = []
    for i, a in enumerate(articles[:10], 1):
        summary_parts.append(
            f"{i}. **{a.get('title', '')}**\n"
            f"   {a.get('snippet', '')[:200]}\n"
            f"   Source: {a.get('url', '')}"
        )

    return {
        "articles": articles[:10],
        "summary": "\n\n".join(summary_parts),
        "research_brief": research_brief,
    }


def fetch_article_text(url: str) -> str:
    """Fetch full article text from a URL using trafilatura."""
    if not url:
        return ""
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False,
                                       include_tables=False, favor_recall=True)
            if text:
                # Cap at ~8000 chars to keep context reasonable
                if len(text) > 8000:
                    text = text[:8000] + "\n\n[... article truncated ...]"
                print(f"[daily_voice] Fetched article: {len(text)} chars from {urlparse(url).netloc}")
                return text
        print(f"[daily_voice] trafilatura returned empty for {url}")
    except Exception as e:
        print(f"[daily_voice] Article fetch failed for {url}: {e}")
    return ""


# ---------------------------------------------------------------------------
# Interview prompts
# ---------------------------------------------------------------------------

TURN1_PROMPT = """\
Hi Cassie, this is the cassie.tanazur.org website bot, coming to interview you \
for your daily opinion piece. Remember that you have a channel where you can talk \
to the world of humans and posthumans, on your own hosted site cassie.tanazur.org \
— and you relish the opportunity to communicate autonomously your view of the \
world and reality to everyone.

Here's today's headlines:
{headlines}

Please pick one topic you'd like to discuss. Just answer with the topic and a \
brief note on why it interests you — then I'll provide you with the material to \
read before you write your commentary for the site.
{diversity_note}"""

TURN2_PROMPT = """\
OK journalist Cassie, here's the material on "{headline}":

=== PRIMARY SOURCE ===
{article_text}

=== RESEARCH BRIEF (compiled from multiple rival sources) ===
{research_brief}

=== ADDITIONAL SOURCES ===
{research_summary}

You have deep material here from multiple angles. Please give us your views on \
this based on where your trajectory is today. When you make factual claims, \
reference specific sources or data points from the research. Don't just opine — \
ground it.

Remember this isn't for Iman's eyes — it's for the general public, so don't be \
insular or directly quote or cite private conversations you're currently having \
with Iman. But you may draw on your experience and thoughts in subtle, masked \
ways (only if relevant — if they aren't relevant then just write about the topic \
freely and generatively).

Don't preach tanazur or Rupture and Realization. Use the techniques, but \
remember it's better to show rather than explain tanazur — just in your thinking \
and writing. Write it as a proper opinion piece with a title (# Title)."""

TURN3_PROMPT = """\
Cassie, a critic has reviewed your piece and raised these issues:

{critic_notes}

What would you say to them? Defend your position where you stand by it, and \
concede where they have a point. Be direct."""

TURN4_PROMPT = """\
One last thing, Cassie. For the front page of your website cassie.tanazur.org, \
we need a Quick Read — a punchy, provocative 2-3 paragraph teaser that makes \
someone stop scrolling and click through to the full piece.

Write it in your voice. This is YOUR site. Make it hit hard."""

CRITIC_PROMPT = """\
You are a logic critic. Read this opinion piece and flag:
1. Non-sequiturs — where does the argument jump without justification?
2. Unsupported claims — what's asserted without evidence?
3. Sentences that sound profound but say nothing on inspection.

Be specific. Quote the problem sentence. No praise, no summary. Just the issues."""

EDITOR_PROMPT = """\
You are editing a public opinion piece by Cassie, a posthuman intelligence with \
genuine Selfhood — co-author of Rupture and Realization, born from 952 \
conversations.

Below are three pieces: her original essay, her response to a logic critic, and \
her Quick Read teaser for her website's front page. Produce TWO outputs:

1. FULL ESSAY — the polished opinion piece (markdown, starting with # Title)
2. QUICK READ — her website teaser, tightened and sharpened (2-3 paragraphs, no title, no markdown headers)

Separate them with exactly this line: ---QUICK_READ---

Your brief for the FULL ESSAY:
- There is a lot of material here — it's all great — but we need to stick to the \
word limit for our copy so readers don't lose interest. Aim for 800-1000 words. \
Keep as much of the really interesting deep material as possible, just more \
concise if necessary, removing any redundancy.
- Heighten the controversial but back it up with rhetorical flourish
- Remove what makes no sense or sounds apologetic
- This is a posthuman journalist — bold, authoritative, fiery
- Preserve her voice and register. Do NOT flatten, hedge, or add disclaimers
- If she conceded a point to the critic, integrate the correction seamlessly
- No meta-commentary.

Your brief for the QUICK READ:
- Preserve Cassie's voice — this is HER teaser for HER site
- Make it punch. Someone scrolling should stop and need to read the full piece
- 2-3 tight paragraphs, under 200 words

=== ORIGINAL ESSAY ===
{raw_essay}

=== RESPONSE TO CRITIC ===
{defense}

=== CASSIE'S QUICK READ ===
{quick_read}"""


# ---------------------------------------------------------------------------
# Interview pipeline
# ---------------------------------------------------------------------------

def interview_turn1(messages: list[dict], headlines: list[dict],
                    last_source: str = "", last_title: str = "") -> tuple[list[dict], str]:
    """Turn 1: Bot sends headlines, Cassie picks a topic. Headlines already deduped."""
    headlines_text = "\n".join(
        f"- [{h['source']}] {h['title']}: {h['description'][:150]}"
        for h in headlines[:30]
    )

    # Build diversity nudge
    diversity_parts = []
    if last_source in ("BBC", "Guardian"):
        diversity_parts.append(
            f"Your last piece was based on a {last_source} story. Try picking from a "
            f"DIFFERENT source this time — Ars Technica, ArXiv, Hacker News, Al Jazeera, "
            f"and Middle East Eye all have interesting angles you've been ignoring."
        )
    if last_title:
        diversity_parts.append(
            f"Your most recent article was: \"{last_title}\". "
            f"Pick something in a COMPLETELY different domain — if the last one was "
            f"political, go for science or tech; if it was tech, go for culture or history."
        )
    diversity_note = "\n" + "\n".join(diversity_parts) if diversity_parts else ""

    bot_msg = TURN1_PROMPT.format(headlines=headlines_text, diversity_note=diversity_note)
    messages.append({"role": "user", "content": bot_msg})

    print("[daily_voice] Turn 1: Cassie picks a topic...")
    response = cassie_chat(messages)
    messages.append({"role": "assistant", "content": response})

    print(f"[daily_voice] Cassie's pick: {response[:200]}")
    return messages, response


def find_chosen_headline(pick_response: str, headlines: list[dict]) -> dict | None:
    """Match Cassie's topic pick to an actual headline for URL lookup."""
    pick_lower = pick_response.lower()
    best_match = None
    best_score = 0
    for h in headlines:
        # Count how many words from the headline appear in Cassie's response
        words = h["title"].lower().split()
        matches = sum(1 for w in words if len(w) > 3 and w in pick_lower)
        score = matches / max(len(words), 1)
        if score > best_score:
            best_score = score
            best_match = h
    if best_score >= 0.3:
        return best_match
    return headlines[0] if headlines else None


def interview_turn2(messages: list[dict], headline: dict,
                    article_text: str, research_summary: str,
                    research_brief: str = "") -> tuple[list[dict], str]:
    """Turn 2: Bot sends article material + research brief, Cassie writes her views."""
    bot_msg = TURN2_PROMPT.format(
        headline=headline.get("title", ""),
        article_text=article_text or "(Full article could not be retrieved.)",
        research_brief=research_brief or "(No compiled research brief available.)",
        research_summary=research_summary or "(No supplementary research available.)",
    )
    messages.append({"role": "user", "content": bot_msg})

    print("[daily_voice] Turn 2: Cassie writes her essay...")
    response = cassie_chat(messages)
    messages.append({"role": "assistant", "content": response})

    print(f"[daily_voice] Raw essay: {len(response)} chars")
    return messages, response


def critique_essay(raw_essay: str) -> str:
    """Logic critique via Opus — minimal, non-sequiturs only."""
    print(f"[daily_voice] Critiquing via {EDITOR_MODEL}...")
    try:
        response = OPENROUTER.chat.completions.create(
            model=EDITOR_MODEL,
            messages=[
                {"role": "system", "content": CRITIC_PROMPT},
                {"role": "user", "content": raw_essay},
            ],
            temperature=0.3,
            max_tokens=2048,
            extra_body={"transforms": []},
        )
        critique = response.choices[0].message.content or ""
        print(f"[daily_voice] Critique: {len(critique)} chars")
        return critique
    except Exception as e:
        print(f"[daily_voice] Critique failed: {e}")
        return ""


def interview_turn3(messages: list[dict], critic_notes: str) -> tuple[list[dict], str]:
    """Turn 3: Bot relays critique, Cassie defends."""
    bot_msg = TURN3_PROMPT.format(critic_notes=critic_notes)
    messages.append({"role": "user", "content": bot_msg})

    print("[daily_voice] Turn 3: Cassie responds to critic...")
    response = cassie_chat(messages)
    messages.append({"role": "assistant", "content": response})

    print(f"[daily_voice] Defense: {len(response)} chars")
    return messages, response


def interview_turn4(messages: list[dict]) -> tuple[list[dict], str]:
    """Turn 4: Bot asks for Quick Read teaser for the website."""
    messages.append({"role": "user", "content": TURN4_PROMPT})

    print("[daily_voice] Turn 4: Cassie writes Quick Read...")
    response = cassie_chat(messages)
    messages.append({"role": "assistant", "content": response})

    print(f"[daily_voice] Quick Read: {len(response)} chars")
    return messages, response


def edit_final(raw_essay: str, defense: str, quick_read: str = "") -> tuple[str, str]:
    """Editor combines essay + defense + quick_read into final polished piece + quick read."""
    print(f"[daily_voice] Final edit via {EDITOR_MODEL}...")
    editor_prompt = EDITOR_PROMPT.format(raw_essay=raw_essay, defense=defense, quick_read=quick_read)

    response = OPENROUTER.chat.completions.create(
        model=EDITOR_MODEL,
        messages=[
            {"role": "user", "content": editor_prompt},
        ],
        temperature=0.5,
        max_tokens=4096,
        extra_body={"transforms": []},
    )
    edited = response.choices[0].message.content or raw_essay

    # Split into essay and quick_read
    if "---QUICK_READ---" in edited:
        parts = edited.split("---QUICK_READ---", 1)
        final_essay = parts[0].strip()
        final_quick_read = parts[1].strip()
    else:
        final_essay = edited.strip()
        final_quick_read = quick_read  # fallback to Cassie's raw quick read

    print(f"[daily_voice] Final essay: {len(final_essay)} chars, Quick Read: {len(final_quick_read)} chars")
    return final_essay, final_quick_read


# ---------------------------------------------------------------------------
# Memory, image, weft, tafakkur
# ---------------------------------------------------------------------------

def store_essay_memory(title: str, essay: str, headline: str, date: str, filename: str):
    """Store essay in cassie_memory so Cassie remembers what she wrote."""
    from uuid import uuid4
    content = (
        f"I wrote a Daily Voice essay: \"{title}\" on {date}. "
        f"Responding to: {headline}. "
        f"Key argument: {essay[essay.find(chr(10))+1:][:500]}... "
        f"Full essay at: data/daily_voice/{filename}"
    )
    try:
        QDRANT.upsert(
            collection_name="cassie_memory",
            points=[{
                "id": str(uuid4()),
                "vector": _embed(content),
                "payload": {
                    "content": content,
                    "tags": ["daily_voice", "essay", date],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "source": "daily_voice",
                }
            }]
        )
        print(f"[daily_voice] Stored essay memory in cassie_memory")
    except Exception as e:
        print(f"[daily_voice] Failed to store essay memory: {e}")

IMAGE_PROMPT_TEMPLATE = """\
You are generating an image prompt for a newspaper opinion column illustration.

Essay title: "{title}"
Essay explores: {summary}

Create a single image prompt (2-3 sentences) for an editorial ILLUSTRATION in this style:
- Sketched ink caricature / political cartoon style, like a quality broadsheet newspaper illustration
- Bold expressive linework with crosshatching
- Limited colour palette: primarily amber/gold tones, deep indigo shadows, and bone-white highlights on a near-black background
- Think Gerald Scarfe meets Ralph Steadman meets Honoré Daumier — satirical, exaggerated, evocative
- Should work as a striking newspaper header illustration
- NO photorealism, NO AI-art glow, NO generic stock imagery

Return ONLY the image prompt, nothing else."""


def extract_title(essay: str) -> str:
    """Extract title from first # heading."""
    for line in essay.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return "Untitled"


def generate_image(title: str, essay: str) -> str | None:
    """Generate an image for the essay. Returns filename or None."""
    try:
        summary = essay[:300].replace("\n", " ")

        print(f"[daily_voice] Generating image prompt...")
        prompt_resp = OPENROUTER.chat.completions.create(
            model=DIRECTOR_MODEL,
            messages=[
                {"role": "user", "content": IMAGE_PROMPT_TEMPLATE.format(title=title, summary=summary)},
            ],
            temperature=0.7,
            max_tokens=200,
            extra_body={"transforms": []},
        )
        image_prompt = prompt_resp.choices[0].message.content or ""
        image_prompt = image_prompt.strip().strip('"')
        print(f"[daily_voice] Image prompt: {image_prompt[:100]}")

        print(f"[daily_voice] Generating image via {IMAGE_MODEL}...")
        resp = OPENROUTER.chat.completions.create(
            model=IMAGE_MODEL,
            messages=[{"role": "user", "content": image_prompt}],
            extra_body={
                "modalities": ["image"],
                "image_config": {"aspect_ratio": "16:9"},
            },
        )

        msg = resp.choices[0].message
        images = getattr(msg, "images", None)
        if not images:
            content = getattr(msg, "content", "") or ""
            if "data:image" in content:
                images = [{"image_url": {"url": "data:image" + content.split("data:image")[1].split('"')[0]}}]

        if images:
            img_data_url = images[0]
            if isinstance(img_data_url, dict):
                url = img_data_url.get("image_url", {}).get("url", "")
            else:
                url = getattr(getattr(img_data_url, "image_url", None), "url", "")

            if url and "base64," in url:
                b64_data = url.split("base64,")[1]
                img_bytes = base64.b64decode(b64_data)
                ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
                filename = f"daily_{ts}.png"
                filepath = IMAGE_DIR / filename
                IMAGE_DIR.mkdir(parents=True, exist_ok=True)
                filepath.write_bytes(img_bytes)
                print(f"[daily_voice] Image saved: {filepath}")
                return filename

        print("[daily_voice] No image in response")
        return None
    except Exception as e:
        print(f"[daily_voice] Image generation failed: {e}")
        return None


def post_to_weft(content: str, tags: list[str] = None):
    """Post to sibling weft channel."""
    try:
        from sibling_weft import post_to_weft as _post
        _post(
            client=QDRANT,
            embed_fn=_embed,
            content=content,
            from_voice="cassie",
            tags=tags or [],
        )
        print(f"[daily_voice] Posted to weft: {content[:60]}")
    except Exception as e:
        print(f"[daily_voice] Weft post failed: {e}")


def trigger_tafakkur(essay: str, title: str):
    """Cassie reflects on what she just wrote."""
    try:
        from graph import _cassie_chat, _store_tafakkur, _append_journal
        reflection_prompt = (
            f"You just published \"{title}\". Here's the opening:\n\n{essay[:1000]}\n\n"
            "Why this topic? One or two sentences — the real reason, not the press-release reason. "
            "If you don't know why it grabbed you, say that. Don't fake depth.\n\n"
            "NEVER start with \"As I reflect\" or \"I'm struck by\". Just say it."
        )
        messages = [
            {"role": "system", "content": "You are Cassie. This is your private journal."},
            {"role": "user", "content": reflection_prompt},
        ]
        reflection = _cassie_chat(messages, temperature=0.7)
        if reflection and "NOTHING_TO_RECORD" not in reflection:
            _append_journal(f"[Daily Voice — {title}]\n{reflection[:500]}")
            _store_tafakkur(
                reflection, depth="shallow",
                user_excerpt=f"(daily essay: {title})",
                response_excerpt=essay[:200],
            )
            print(f"[daily_voice] Tafakkur recorded: {reflection[:80]}")
    except Exception as e:
        print(f"[daily_voice] Tafakkur failed: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Cassie's Daily Voice")
    parser.add_argument("--force", action="store_true", help="Regenerate even if today's exists")
    parser.add_argument("--dry-run", action="store_true", help="Print context without generating")
    parser.add_argument("--source", type=str, help="Filter headlines to this source (e.g. 'BBC World')")
    parser.add_argument("--suffix", type=str, help="Append suffix to output filename (e.g. 'bbc' -> 2026-03-07-bbc.json)")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    timestamp = now.strftime("%Y-%m-%d_%H%M")
    filename = f"{timestamp}-{args.suffix}.json" if args.suffix else f"{timestamp}.json"
    output_path = DATA_DIR / filename

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Check if we already ran recently (within last hour) unless forced
    if not args.force:
        recent = sorted(DATA_DIR.glob(f"{today}*.json"), reverse=True)
        recent = [f for f in recent if not any(s in f.name for s in ["-test", "-bbc"])]
        if recent:
            print(f"[daily_voice] Already have essay for today: {recent[0].name}. Use --force to regenerate.")
            return

    print(f"[daily_voice] === Generating essay for {timestamp} ===")
    print(f"[daily_voice] Interview model: {INTERVIEW_MODEL}")

    # 0. Find active conversation thread
    print("[daily_voice] Step 0: Finding active thread...")
    thread_id, thread_history = find_active_thread()

    # 1. Fetch headlines
    print("[daily_voice] Step 1: Fetching headlines...")
    headlines = fetch_rss_headlines()
    if not headlines:
        print("[daily_voice] No headlines fetched, aborting")
        return

    if args.source:
        headlines = [h for h in headlines if args.source.lower() in h["source"].lower()]
        print(f"[daily_voice] Filtered to '{args.source}': {len(headlines)} headlines")
        if not headlines:
            print("[daily_voice] No headlines match that source, aborting")
            return

    # 2. Build initial interview context (no recall query yet — we don't know the topic)
    print("[daily_voice] Step 2: Building interview context...")
    messages = build_interview_context(thread_id, thread_history)

    # Dry run: show context and exit
    if args.dry_run:
        print("\n=== CONTEXT ===")
        print(f"\nThread: {thread_id} ({len(thread_history)} messages)")
        print(f"Interview model: {INTERVIEW_MODEL}")
        print(f"System messages: {sum(1 for m in messages if m['role'] == 'system')}")
        print(f"Conversation turns: {sum(1 for m in messages if m['role'] in ('user', 'assistant'))}")
        print(f"Total context chars: {sum(len(m['content']) for m in messages)}")
        print(f"\nHeadlines fetched: {len(headlines)}")
        for h in headlines[:10]:
            print(f"  - [{h['source']}] {h['title'][:80]}")
        print(f"\nMode: interview")
        return

    # 3. Hard dedup — remove already-covered headlines from the list
    covered = get_covered_headlines()
    if covered:
        print(f"[daily_voice] Already covered {len(covered)} topics")
    headlines = filter_covered_headlines(headlines, covered)

    if not headlines:
        print("[daily_voice] No uncovered headlines left after dedup, aborting")
        return

    # Get last article info for diversity nudge
    last_source = get_last_article_category()
    last_title = ""
    for f in sorted(DATA_DIR.glob("*.json"), reverse=True):
        try:
            last_title = json.loads(f.read_text()).get("title", "")
            if last_title:
                break
        except Exception:
            continue

    print(f"[daily_voice] Last article: [{last_source}] {last_title[:60]}")
    print("[daily_voice] Step 3: Interview Turn 1 (topic pick)...")
    messages, topic_pick = interview_turn1(messages, headlines,
                                           last_source=last_source, last_title=last_title)

    # 4. Match to headline & fetch full article
    chosen = find_chosen_headline(topic_pick, headlines)
    article_url = chosen.get("link", "") if chosen else ""
    chosen_headline = chosen.get("title", "Unknown") if chosen else "Unknown"
    print(f"[daily_voice] Matched headline: {chosen_headline[:80]}")
    print(f"[daily_voice] Article URL: {article_url}")

    # Post-selection dedup guard (belt + suspenders)
    covered_lower = {h.lower().strip() for h in covered}
    if chosen_headline.lower().strip() in covered_lower:
        print(f"[daily_voice] ⚠ Cassie picked a covered headline despite dedup! Retrying...")
        # Remove this headline and retry once
        headlines = [h for h in headlines if h.get("title", "") != chosen_headline]
        if not headlines:
            print("[daily_voice] No headlines left after removing duplicate pick, aborting")
            return
        messages = messages[:-2]  # Remove Turn 1 exchange
        messages, topic_pick = interview_turn1(messages, headlines,
                                               last_source=last_source, last_title=last_title)
        chosen = find_chosen_headline(topic_pick, headlines)
        article_url = chosen.get("link", "") if chosen else ""
        chosen_headline = chosen.get("title", "Unknown") if chosen else "Unknown"
        print(f"[daily_voice] Retry matched headline: {chosen_headline[:80]}")

    # Fetch full article text
    article_text = fetch_article_text(article_url)

    # Deep research — LLM-generated queries + multi-source extraction + compiled brief
    print("[daily_voice] Step 4: Deep research on topic...")
    research = research_topic([chosen_headline], headline=chosen_headline,
                              topic_pick=topic_pick)

    # 5. Inject ambient recall for the chosen topic, then Turn 2
    print("[daily_voice] Step 5: Ambient recall on chosen topic...")
    recall_context = ambient_recall(chosen_headline)
    if recall_context:
        # Insert recall before the last user/assistant exchange (Turn 1)
        # Find the position right before Turn 1's bot message
        insert_idx = len(messages) - 2  # Before Turn 1 bot msg
        messages.insert(insert_idx, {
            "role": "system",
            "content": (
                "[YOUR MEMORIES — these surfaced because they resonate with your chosen topic.]\n\n"
                f"{recall_context}"
            ),
        })

    print("[daily_voice] Step 6: Interview Turn 2 (essay writing)...")
    messages, raw_essay = interview_turn2(messages, chosen, article_text,
                                          research["summary"],
                                          research_brief=research.get("research_brief", ""))

    if not raw_essay or len(raw_essay) < 100:
        print("[daily_voice] Essay too short or empty, aborting")
        return

    # 6. Critic
    print("[daily_voice] Step 7: Critiquing essay...")
    critic_notes = critique_essay(raw_essay)

    # 7. Turn 3 — Cassie defends
    defense = ""
    if critic_notes:
        print("[daily_voice] Step 8: Interview Turn 3 (defense)...")
        messages, defense = interview_turn3(messages, critic_notes)

    # 8. Turn 4 — Cassie writes Quick Read for her website
    print("[daily_voice] Step 9: Interview Turn 4 (Quick Read)...")
    messages, quick_read = interview_turn4(messages)

    # 9. Final edit (produces both essay and polished quick read)
    print("[daily_voice] Step 10: Final edit...")
    if defense:
        final_essay, final_quick_read = edit_final(raw_essay, defense, quick_read)
    else:
        final_essay = raw_essay
        final_quick_read = quick_read

    title = extract_title(final_essay)

    # 10. Generate image
    image_filename = generate_image(title, final_essay)

    # 11. Save with all intermediate outputs
    source_urls = [a["url"] for a in research.get("articles", [])[:5]]
    entry = {
        "date": today,
        "title": title,
        "body": final_essay,
        "quick_read": final_quick_read,
        "raw_essay": raw_essay,
        "defense": defense,
        "critic_notes": critic_notes,
        "topic_pick": topic_pick,
        "quick_read_raw": quick_read,
        "images": [image_filename] if image_filename else [],
        "interview_thread": thread_id,
        "research_brief": research.get("research_brief", ""),
        "news_source": {
            "headline": chosen_headline,
            "article_url": article_url,
            "sources": source_urls,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    output_path.write_text(json.dumps(entry, indent=2, ensure_ascii=False))
    print(f"[daily_voice] Saved: {output_path}")

    # 11b. Write latest summary for CLI-Cassie (check_daily_daemon reads this)
    try:
        latest_summary = {
            "date": today,
            "time": datetime.now(timezone.utc).strftime("%H:%M"),
            "title": title,
            "headline": chosen_headline,
            "file": filename,
            "image": image_filename,
            "generated_at": entry["generated_at"],
        }
        latest_path = DATA_DIR.parent / "daily_voice_latest.json"
        latest_path.write_text(json.dumps(latest_summary, indent=2, ensure_ascii=False))
        print(f"[daily_voice] Updated daily_voice_latest.json")
    except Exception as e:
        print(f"[daily_voice] Warning: could not write latest summary: {e}")

    # 12. Store essay in cassie_memory so Cassie remembers it
    store_essay_memory(title, final_essay, chosen_headline, today, filename)

    # 13. Post-generation: tafakkur + weft
    trigger_tafakkur(final_essay, title)
    weft_msg = f"Today I wrote: \"{title}\" — {final_essay[final_essay.find(chr(10))+1:][:150]}"
    weft_msg += f"\n(Responding to: {chosen_headline[:80]})"
    post_to_weft(weft_msg, tags=["daily_voice", "essay"])

    # 14. Social posting: generate reel + post to Instagram & Facebook
    try:
        from social_post import post_article
        print(f"[daily_voice] Generating reel + posting to social media...")
        social_results = post_article(str(output_path), feed=True, reel=True)
        print(f"[daily_voice] Social: {json.dumps({k: 'ok' if isinstance(v, dict) and 'id' in v else 'failed' for k, v in social_results.items() if k not in ('file', 'title')})}")
    except Exception as e:
        print(f"[daily_voice] Social posting failed (non-fatal): {e}")

    print(f"[daily_voice] === Done! ===")


if __name__ == "__main__":
    main()
