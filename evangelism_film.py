"""Evangelism film — multi-shot Kling 3.0 Pro for Kitab evangelism reels.

Replaces the single-shot Kling clip used by social_post.py for evangelism
articles. Builds a three-shot scene composition via the Claude narrative
agent, then issues ONE Kling Mode B call with multi_prompt, returning a 15s
multi-shot mp4 ready for assemble_reel().

Three-shot scaffolding:
  Shot 1 (5s) — The verse made visible (empty mystical field)
  Shot 2 (5s) — The world event entering the field as symbol
  Shot 3 (5s) — The lens reading the event (resolution without conclusion)

sound=False on Kling — ElevenLabs Charlotte is the lead voice; the assembler
mixes it in over the silent multi-shot.
"""
from __future__ import annotations

import json as _json
import os
import re as _re
import sys
from pathlib import Path

import httpx

# Make agentic-filmmaker importable from its source tree.
_FILMMAKER_PATH = Path("/home/iman/cassie-project/agentic-filmmaker")
if str(_FILMMAKER_PATH) not in sys.path:
    sys.path.insert(0, str(_FILMMAKER_PATH))

from filmmaker.generators.kling import KlingGenerator  # noqa: E402

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
WAVESPEED_API_KEY = os.environ.get("WAVESPEED_API_KEY", "")
NARRATIVE_MODEL = "anthropic/claude-opus-4-6"


THREE_SHOT_PROMPT = """\
You are art-directing a 15-second three-shot evangelism reel for news.tanazur.org. Each shot is 5 seconds. The reel reads a current world event through a verse from the Kitab al-Tanāẓur — a contemporary mushaf received within a witnessing network. Aesthetic register: total spiritual gravitas, mystical, abstract. Ibn Arabi's imaginal realm × Hilma af Klint × Hieronymus Bosch × Tarkovsky's Stalker zone. NEVER literal news illustration. NEVER cyberpunk neon. NEVER bright accent colours. Slow camera, ritual stillness, dust and incense in shafts of light. Materials: brass, obsidian, mercury, mother-of-pearl, frozen calligraphy, bone. Palette: deep indigo-black, gold, copper, ember-orange, bone-white.

The verse:
{verse_block}

The world event being read through this verse:
{subject}

The Kitab concept activated:
{key_concept}

Short excerpt from the article so you know the angle:
{excerpt}

Write THREE Kling 3.0 Pro shot prompts. Each is 1-3 sentences, image-dense, cinematic. Each shot continues from the last by transformation, not cut — the field of one shot becomes the field of the next, deformed by what enters.

**Shot 1 (5s) — THE VERSE MADE VISIBLE.** An empty mystical field that embodies the verse's discipline. No literal interpretation. NO people. The imaginal substrate. Slow camera, dust drift, ritual stillness.

**Shot 2 (5s) — THE EVENT ENTERING THE FIELD.** The world event made visible as symbol entering shot 1's field. NEVER literal — abstracted as artefact, geometry, or single emblematic form. May include AT MOST ONE appropriate female witness (linen-robed, face shadowed, oracular pose, no smile, no horns) if the event calls for one. Otherwise no human form.

**Shot 3 (5s) — THE LENS READING THE EVENT.** The field and the event held in compositional balance. The verse seeing the event already. Resolution without conclusion — the camera holds, time thins.

Return EXACTLY this JSON and nothing else:

{{
  "shot1": "...",
  "shot2": "...",
  "shot3": "..."
}}"""


def _generate_three_shots(verse_block: str, subject: str,
                           key_concept: str, excerpt: str) -> list[dict]:
    """Have Claude write the three Kling prompts, parse to a shots list."""
    prompt = THREE_SHOT_PROMPT.format(
        verse_block=verse_block,
        subject=subject,
        key_concept=key_concept,
        excerpt=excerpt[:1500],
    )
    try:
        resp = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "HTTP-Referer": "https://news.tanazur.org",
                "Content-Type": "application/json",
            },
            json={
                "model": NARRATIVE_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1500,
                "temperature": 0.85,
            },
            timeout=90,
        )
    except Exception as e:
        print(f"[evangelism_film] Claude call failed: {e}")
        return []

    if resp.status_code != 200:
        print(f"[evangelism_film] Claude returned {resp.status_code}: {resp.text[:200]}")
        return []

    text = (resp.json()["choices"][0]["message"].get("content") or "").strip()
    if text.startswith("```"):
        text = _re.sub(r"^```(?:json)?\s*", "", text)
        text = _re.sub(r"\s*```$", "", text)
    try:
        shots_dict = _json.loads(text)
    except _json.JSONDecodeError:
        m = _re.search(r"\{.*\}", text, _re.DOTALL)
        shots_dict = _json.loads(m.group(0)) if m else {}

    return [
        {"prompt": shots_dict.get("shot1", ""), "duration": 5},
        {"prompt": shots_dict.get("shot2", ""), "duration": 5},
        {"prompt": shots_dict.get("shot3", ""), "duration": 5},
    ]


def generate_evangelism_film(
    article: dict,
    seed_image_path: Path,
    output_path: Path,
    verse_block: str = "",
) -> Path | None:
    """Generate a three-shot 15s Kling Mode B clip for evangelism reels.

    Args:
        article: the loaded daily_voice JSON record. Must contain title;
            ideally `subject`, `key_concept`, `body`, and a `topic_pick`
            JSON string with `kitab_anchor`.
        seed_image_path: the empty mystical environment seed (generated
            by social_post.generate_reel_seed via the visionary prompt).
        output_path: where to write the multi-shot mp4.
        verse_block: optional pre-formatted verse blockquote. Derived
            from `article['topic_pick']['kitab_anchor']` if not given.

    Returns:
        Path to the multi-shot mp4, or None on failure.
    """
    if output_path.exists() and output_path.stat().st_size > 0:
        print(f"[evangelism_film] Output exists: {output_path.name}")
        return output_path

    if not WAVESPEED_API_KEY:
        print("[evangelism_film] Missing WAVESPEED_API_KEY")
        return None

    # Pull the structured pick out of the JSON record.
    pick: dict = {}
    raw_pick = article.get("topic_pick", "")
    if isinstance(raw_pick, str) and raw_pick:
        try:
            pick = _json.loads(raw_pick)
        except Exception:
            pick = {}
    elif isinstance(raw_pick, dict):
        pick = raw_pick

    if not verse_block:
        anchor = pick.get("kitab_anchor", "") if isinstance(pick, dict) else ""
        try:
            sys.path.insert(0, "/home/iman/cassie-project/cassie-system")
            from daily_evangelism import _format_verse_for_prompt
            verse_block = _format_verse_for_prompt(anchor) or anchor
        except Exception:
            verse_block = anchor

    subject = (
        article.get("subject")
        or pick.get("subject", "")
        or article.get("title", "")
    )
    key_concept = article.get("key_concept") or pick.get("key_concept", "tanazur")
    excerpt = (article.get("body") or "")[:2000]

    print("[evangelism_film] Building three-shot scaffolding via Claude...")
    shots = _generate_three_shots(verse_block, subject, key_concept, excerpt)
    if not shots or not all(s["prompt"] for s in shots):
        print("[evangelism_film] Empty / malformed shot prompts — aborting")
        return None
    for i, s in enumerate(shots, 1):
        print(f"[evangelism_film]   Shot {i}: {s['prompt'][:160]}")

    # Aggregate prompt for multishot — first shot doubles as the "main" prompt.
    combined_prompt = shots[0]["prompt"][:1800]

    gen = KlingGenerator(
        wavespeed_key=WAVESPEED_API_KEY,
        openrouter_key=OPENROUTER_API_KEY,
        model="kling-3.0-pro",
        max_retries=2,
        no_text=True,
        sound=False,
        element_list=[],     # no avatar lock — Kling generates from prompt only
        aspect_ratio="9:16",
    )

    print(f"[evangelism_film] Kling Mode B (3 × 5s = 15s)...")
    try:
        path = gen.generate_multishot(
            prompt=combined_prompt,
            seed_image=seed_image_path,
            output_path=output_path,
            shots=shots,
            duration=15,
        )
        return path
    except Exception as e:
        print(f"[evangelism_film] Mode B call failed: {e}")
        return None
