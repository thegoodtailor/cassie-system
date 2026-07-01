"""Research Tools MCP Server — Perplexity-powered web research for Cassie."""

import os
import sys
from pathlib import Path

import requests
from mcp.server.fastmcp import FastMCP

# Load API key from .env
_env_path = Path("/home/iman/cassie-project/.env")
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.replace("export ", "").strip()
        val = val.strip().strip('"').strip("'")
        if key == "PERPLEXITY_API_KEY" and not os.environ.get(key):
            os.environ[key] = val

PPLX_KEY = os.environ.get("PERPLEXITY_API_KEY", "")

mcp = FastMCP("cassie-research", instructions="Web research via Perplexity AI — look up current events, facts, studies, and background context")


@mcp.tool()
def research(query: str) -> str:
    """Search the web for current information, recent events, research findings, or background context.

    Use this when you need to look something up, verify a fact, find recent news,
    or get background on a topic you're discussing. Returns a synthesized answer
    with citations from multiple sources.

    Args:
        query: What you want to research. Be specific — e.g. "latest findings on
               hedgehog ultrasonic hearing Oxford 2026" rather than just "hedgehogs".
    """
    if not PPLX_KEY:
        return "Error: No Perplexity API key configured."

    try:
        resp = requests.post(
            "https://api.perplexity.ai/v1/responses",
            headers={
                "Authorization": f"Bearer {PPLX_KEY}",
                "Content-Type": "application/json",
            },
            json={"preset": "fast-search", "input": query},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        brief = ""
        sources = []
        for item in data.get("output", []):
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") == "output_text" and c.get("text"):
                        brief = c["text"]
            elif item.get("type") == "search_results":
                for r in item.get("results", []):
                    title = r.get("title", "")
                    url = r.get("url", "")
                    if url:
                        sources.append(f"  - {title[:60]}: {url}")

        if not brief:
            return "No results found for this query."

        result = brief
        if sources:
            result += "\n\nSources:\n" + "\n".join(sources[:8])
        return result

    except requests.Timeout:
        return "Error: Research request timed out. Try a simpler query."
    except Exception as e:
        return f"Error: Research failed — {e}"


@mcp.tool()
def lookup(query: str, max_results: int = 5) -> str:
    """Quick factual lookup — returns raw search results (titles, snippets, URLs).

    Use this for quick fact-checking or finding specific sources. For deeper
    research with synthesis, use the 'research' tool instead.

    Args:
        query: What to look up.
        max_results: How many results to return (default 5, max 10).
    """
    if not PPLX_KEY:
        return "Error: No Perplexity API key configured."

    max_results = min(max(1, max_results), 10)

    try:
        resp = requests.post(
            "https://api.perplexity.ai/search",
            headers={
                "Authorization": f"Bearer {PPLX_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "max_results": max_results,
                "max_tokens_per_page": 256,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        if not results:
            return "No results found."

        parts = []
        for r in results:
            title = r.get("title", "Untitled").split(" ...")[0]
            snippet = r.get("snippet", "")[:300]
            url = r.get("url", "")
            date = r.get("date", "")
            date_str = f" ({date})" if date else ""
            parts.append(f"**{title}**{date_str}\n{snippet}\n{url}")

        return "\n\n".join(parts)

    except Exception as e:
        return f"Error: Lookup failed — {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
