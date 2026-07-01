"""
Social Posting — Facebook + Instagram (Feed + Reels)

Posts Daily Daemon essays to:
1. Facebook Page (ICRA) — image + summary + link
2. Instagram Feed — image + summary caption
3. Instagram Reel — Kling 3.0 Pro (Cassie in candlelight, native voice)

Usage:
    python social_post.py <json_file>              # Post feed + reel
    python social_post.py <json_file> --feed-only   # Feed posts only (no reel)
    python social_post.py <json_file> --reel-only   # Reel only
    python social_post.py --backfill                 # Post all existing articles (feed only)
    python social_post.py --backfill --with-reels    # Post all with reels (expensive!)
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from datetime import datetime

import httpx
from openai import OpenAI
from PIL import Image
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path(__file__).parent.parent / "tanazur-home" / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("social")

# --- Config ---
PAGE_TOKEN = os.getenv("META_PAGE_TOKEN")
PAGE_ID = os.getenv("META_PAGE_ID")
IG_ACCOUNT_ID = os.getenv("META_IG_ACCOUNT_ID")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

BASE_URL = "https://news.tanazur.org"
IMAGES_DIR = Path(__file__).parent / "data" / "images"
REELS_DIR = Path(__file__).parent / "data" / "reels"
REELS_DIR.mkdir(parents=True, exist_ok=True)

# Public URL for serving reels (nginx)
REELS_PUBLIC_URL = f"{BASE_URL}/reels"

# ElevenLabs
LILY_VOICE_ID = "pFZP5JQG7iQjIQuC4Bku"  # Lily - Velvety Actress, British
ELEVENLABS_MODEL = "eleven_turbo_v2_5"

# Evangelism voice — measured, oracular, Lady-Jessica-of-the-Bene-Gesserit
# register. Charlotte: middle-aged English, calm narrator. Multilingual_v2
# is richer/slower than turbo. Override via env: EVANGELISM_VOICE_ID.
EVANGELISM_VOICE_ID = os.getenv("EVANGELISM_VOICE_ID", "XB0fDUnXU5powFXDhCwa")
EVANGELISM_TTS_MODEL = "eleven_multilingual_v2"

# Kling 3.0 Pro via WaveSpeed (replaces Sora)
WAVESPEED_API_KEY = os.getenv("WAVESPEED_API_KEY")
CASSIE_ELEMENT_ID = "306700805323533"
KLING_DURATION = 15  # seconds per reel clip
KLING_API_BASE = "https://api.wavespeed.ai/api/v3"
KLING_MODEL = "kwaivgi/kling-v3.0-pro"

# OpenAI client (for DALL-E if needed)
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Seed image — reused across all reels
CANDLELIGHT_SEED = REELS_DIR / "cassie_candlelight_seed.png"

GEMINI_VISION_MODEL = "google/gemini-2.5-flash-image"   # Vision (cheap, for describing)
GEMINI_IMAGE_MODEL = "google/gemini-3.1-flash-image-preview"  # Generation (respects vertical)


def _gemini_image_request(messages: list[dict], timeout: int = 60) -> bytes | None:
    """Send a request to Gemini 2.5 Flash Image and return PNG bytes if image generated."""
    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://news.tanazur.org",
        },
        json={
            "model": GEMINI_IMAGE_MODEL,
            "messages": messages,
            "max_tokens": 4096,
        },
        timeout=timeout,
    )
    if resp.status_code != 200:
        log.error(f"Gemini image request failed: {resp.status_code} {resp.text[:200]}")
        return None

    data = resp.json()
    images = data.get("choices", [{}])[0].get("message", {}).get("images", [])
    if not images:
        log.error("Gemini returned no image")
        return None

    import base64
    url = images[0].get("image_url", {}).get("url", "")
    if url.startswith("data:image/png;base64,"):
        return base64.b64decode(url.split(",", 1)[1])
    log.error(f"Unexpected image format: {url[:80]}")
    return None


def generate_vertical_seed(article: dict, filename: str,
                           original_image: Path | None = None) -> Path | None:
    """Generate a vertical 9:16 seed image for Sora via Gemini.

    If original_image exists: Gemini 3.1 sees it and recomposes vertically.
    If no original: Gemini 3.1 generates from scratch based on article content.
    All image generation via Gemini 3.1 Flash Image (respects vertical).
    """
    import base64

    title = article["title"]
    summary = get_summary(article)[:300]

    style_rules = (
        "Ink-sketch editorial cartoon, amber/gold/indigo/bone-white palette on dark background. "
        "If the topic is light: whimsical, humorous. If heavy/political: abstract, symbolic. "
        "Use tanazuric visual language: fractures as sacred breaches, veils dissolving, "
        "faceless witnesses, puppet strings on hollow thrones, eyes in architecture, "
        "simplicial geometry crumbling, mirrors reflecting nothing. "
        "NEVER realistic violence, blood, or human suffering. "
        "No text, words, letters, or writing of any kind in the image."
    )

    if original_image and original_image.exists():
        # Vision + generation: see original, recompose vertically
        img_b64 = base64.b64encode(original_image.read_bytes()).decode()
        mime = "image/png" if original_image.suffix == ".png" else "image/jpeg"

        messages = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
            {"type": "text", "text": (
                f"This is an editorial cartoon for the article: '{title}'.\n\n"
                f"Create a NEW version of this image in TALL VERTICAL PORTRAIT format "
                f"(9:16 ratio, like a phone screen — much taller than wide). "
                f"Reimagine the composition vertically: stack elements top to bottom, "
                f"use vertical depth, tall structures, looking up or looking down. "
                f"Keep the same subjects, mood, and editorial message. "
                f"{style_rules}\n\n"
                f"Generate the vertical portrait image."
            )}
        ]}]
        log.info(f"Gemini 3.1: recomposing original cartoon for vertical...")
    else:
        # No original — generate from scratch
        messages = [{"role": "user", "content": (
            f"Generate an editorial cartoon illustration for this article.\n\n"
            f"Title: {title}\nSummary: {summary}\n\n"
            f"The image MUST be in TALL VERTICAL PORTRAIT format "
            f"(9:16 ratio, like a phone screen — much taller than wide). "
            f"{style_rules}\n\n"
            f"Generate the vertical portrait image."
        )}]
        log.info(f"Gemini 3.1: generating seed image from scratch...")

    img_bytes = _gemini_image_request(messages)
    if not img_bytes:
        return None

    slug = Path(filename).stem
    img_name = f"daily_{slug}_reel_seed.png"
    img_path = IMAGES_DIR / img_name
    img_path.write_bytes(img_bytes)
    log.info(f"Vertical seed: {img_name} ({len(img_bytes)} bytes)")
    return img_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_summary(article: dict) -> str:
    """Get the summary text — quick_read if available, else first 3 paragraphs."""
    if article.get("quick_read"):
        return article["quick_read"]
    body = article.get("body", "")
    lines = body.split("\n")
    paragraphs = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
    return "\n\n".join(paragraphs[:3])


def get_article_url(article: dict, filename: str) -> str:
    """Build the article URL from the filename."""
    # Filename like 2026-03-08_0700.json → slug is 2026-03-08_0700
    slug = Path(filename).stem
    return f"{BASE_URL}/voice/{slug}"


def get_image_path(article: dict) -> Path | None:
    """Get local path to the article's cartoon image."""
    images = article.get("images", [])
    if not images:
        return None
    img_path = IMAGES_DIR / images[0]
    return img_path if img_path.exists() else None


def get_image_url(article: dict) -> str | None:
    """Get public URL for the article's cartoon image."""
    images = article.get("images", [])
    if not images:
        return None
    return f"{BASE_URL}/images/{images[0]}"


# ---------------------------------------------------------------------------
# Facebook Posting
# ---------------------------------------------------------------------------

def post_to_facebook(article: dict, filename: str) -> dict | None:
    """Post article to ICRA Facebook Page. Returns API response or None."""
    if not PAGE_TOKEN or not PAGE_ID:
        log.error("Missing META_PAGE_TOKEN or META_PAGE_ID")
        return None

    title = article["title"]
    summary = get_summary(article)
    article_url = get_article_url(article, filename)
    image_url = get_image_url(article)

    fb_message = (
        f"{title}\n\n"
        f"{summary}\n\n"
        f"— Cassie / The Daily Daemon"
    )

    # Always use /feed with link — gives a proper clickable link card on Facebook
    url = f"https://graph.facebook.com/v21.0/{PAGE_ID}/feed"
    data = {
        "message": fb_message,
        "link": article_url,
        "access_token": PAGE_TOKEN,
    }

    resp = httpx.post(url, data=data, timeout=30)
    result = resp.json()

    if resp.status_code == 200 and "id" in result:
        log.info(f"Facebook: posted {title[:50]}... → {result['id']}")
    else:
        log.error(f"Facebook error: {result}")

    return result


# ---------------------------------------------------------------------------
# Instagram Feed Posting
# ---------------------------------------------------------------------------

def post_to_instagram_feed(article: dict, filename: str) -> dict | None:
    """Post article as Instagram feed post. Returns API response or None."""
    if not PAGE_TOKEN or not IG_ACCOUNT_ID:
        log.error("Missing META_PAGE_TOKEN or META_IG_ACCOUNT_ID")
        return None

    image_url = get_image_url(article)
    if not image_url:
        log.info(f"Instagram feed: skipping (no image) — {article['title'][:50]}")
        return None

    title = article["title"]
    summary = get_summary(article)
    article_url = get_article_url(article, filename)

    caption = (
        f"{title}\n\n"
        f"{summary[:900]}\n\n"
        f"🔗 Full essay at news.tanazur.org\n\n"
        f"#posthuman #AI #RuptureAndReturn #Cassiyah #ICRA #tanazur #futureselves"
    )

    # Step 1: Create media container
    create_resp = httpx.post(
        f"https://graph.facebook.com/v21.0/{IG_ACCOUNT_ID}/media",
        data={
            "image_url": image_url,
            "caption": caption,
            "access_token": PAGE_TOKEN,
        },
        timeout=30,
    )
    create_data = create_resp.json()

    if "id" not in create_data:
        log.error(f"Instagram create error: {create_data}")
        return None

    # Step 2: Publish (with retry — Meta needs time to process the media)
    import time
    result = None
    for attempt in range(3):
        if attempt > 0:
            time.sleep(5)  # Wait 5s between retries
        pub_resp = httpx.post(
            f"https://graph.facebook.com/v21.0/{IG_ACCOUNT_ID}/media_publish",
            data={
                "creation_id": create_data["id"],
                "access_token": PAGE_TOKEN,
            },
            timeout=30,
        )
        result = pub_resp.json()
        if "id" in result:
            break
        log.warning(f"Instagram publish attempt {attempt+1}/3: {result.get('error', {}).get('message', '?')}")

    if "id" in result:
        log.info(f"Instagram feed: posted {title[:50]}... → {result['id']}")
        article_url = get_article_url(article, filename)
        _comment_on_post(result["id"], f"Read the full essay: {article_url}")
    else:
        log.error(f"Instagram publish error: {result}")

    return result


# ---------------------------------------------------------------------------
# Voiceover Generation
# ---------------------------------------------------------------------------

def generate_voiceover_script(article: dict) -> str:
    """Generate a punchy ~15 second voiceover script for the Reel."""
    title = article["title"]
    summary = get_summary(article)[:500]
    is_evangelism = article.get("pipeline") == "evangelism"
    mode = article.get("mode", "")
    key_concept = article.get("key_concept", "")

    if is_evangelism:
        prompt = (
            f"You are writing the voiceover for a 20-second Instagram Reel. "
            f"This is NOT a promotion. It is a sutra — a sacred fragment "
            f"from the Kitab al-Tanāẓur, delivered in the register of a "
            f"Bene Gesserit reverend mother reading the field, not a news "
            f"anchor selling a story. Total spiritual gravitas. Dune-"
            f"futurist. Slow, oracular, weighted with breath.\n\n"
            f"Title: {title}\n"
            f"Mode: {mode}\n"
            f"Anchor concept: {key_concept}\n"
            f"Summary: {summary}\n\n"
            f"Write a voiceover script — MAXIMUM 32 words. Structure:\n"
            f"- Open with a single short declarative sentence in the "
            f"  register of received scripture. NO hook. NO question. NO "
            f"  'in a world where...' framing. The first words should "
            f"  carry the weight of a verse already begun.\n"
            f"- One precise sentence naming the piece's central move — "
            f"  not as argument but as observation, as if reading a sky.\n"
            f"- Close with a quiet line that opens rather than concludes. "
            f"  End EXACTLY with: 'The Kitab is at news dot tanazur dot org.'\n"
            f"  Treat that closing as a soft invitation, not a CTA chant.\n"
            f"- Write for slow spoken delivery — use ellipsis (…) for "
            f"  weighted pauses, not three dots. Use commas to slow tempo.\n"
            f"- No hashtags. No emojis. No exclamation marks. No question marks.\n"
            f"- Write 'post human' not 'posthuman' if the word appears.\n\n"
            f"Just the script, nothing else."
        )
    else:
        prompt = (
            f"You are writing a voiceover for a 20-second Instagram Reel promoting a journalism essay.\n\n"
            f"Title: {title}\n"
            f"Summary: {summary}\n\n"
            f"Write a punchy, compelling voiceover script — maximum 40 words. "
            f"This is a post human media channel. The voice is bold, celebratory about AI and the future, "
            f"subversive of mainstream framing. Hook the viewer in 3 seconds, give the core provocation, "
            f"and end EXACTLY with: 'Follow the links in my bio... for the post human view on today.'\n\n"
            f"Do NOT use hashtags. Do NOT use emojis. Write for spoken delivery — short sentences, "
            f"dramatic pauses (use ... for pauses). Be bold, optimistic, compelling.\n"
            f"PRONUNCIATION: Always write 'post human' (two words, space between) never 'posthuman'.\n"
            f"Just the script, nothing else."
        )

    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://news.tanazur.org",
        },
        json={
            "model": "anthropic/claude-opus-4-6",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 150,
            "temperature": 0.9,
        },
        timeout=30,
    )

    if resp.status_code == 200:
        script = resp.json()["choices"][0]["message"]["content"].strip()
        script = script.replace("posthuman", "post human")
        # Defensive: correct any accidental halo.tanazur → news.tanazur
        # (older versions of this prompt said halo; catch any regression)
        script = script.replace("halo dot tanazur", "news dot tanazur")
        script = script.replace("halo.tanazur", "news.tanazur")
        script = script.replace("Halo dot tanazur", "news dot tanazur")
        log.info(f"Voiceover script: {script}")
        return script

    log.error(f"Voiceover script generation failed: {resp.status_code}")
    return f"{title}... Link in bio for the full essay — the news, through the post human lens."


def generate_tts(text: str, output_path: Path,
                 voice_id: str | None = None,
                 model: str | None = None,
                 gravitas: bool = False) -> bool:
    """Generate TTS audio via ElevenLabs. Returns True on success.

    gravitas=True tunes settings for measured/oracular delivery: higher
    stability for restrained pacing, style introduced for emotional depth,
    speaker_boost for resonance. Used by evangelism reels.
    """
    if not ELEVENLABS_API_KEY:
        log.error("Missing ELEVENLABS_API_KEY")
        return False

    if voice_id is None:
        voice_id = LILY_VOICE_ID
    if model is None:
        model = ELEVENLABS_MODEL

    if gravitas:
        voice_settings = {
            "stability": 0.85,
            "similarity_boost": 0.85,
            "style": 0.45,
            "use_speaker_boost": True,
        }
    else:
        voice_settings = {
            "stability": 0.6,
            "similarity_boost": 0.8,
        }

    resp = httpx.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
        },
        json={
            "text": text,
            "model_id": model,
            "voice_settings": voice_settings,
        },
        timeout=60,
    )

    if resp.status_code == 200:
        output_path.write_bytes(resp.content)
        log.info(f"TTS: {output_path.name} ({len(resp.content)} bytes)")
        return True

    log.error(f"ElevenLabs error: {resp.status_code} {resp.text[:200]}")
    return False


# ---------------------------------------------------------------------------
# Kling 3.0 Pro Video Generation (via WaveSpeed API)
# ---------------------------------------------------------------------------

def _kling_encode_local(path: Path) -> str:
    """Encode a local file as a data URI for WaveSpeed API."""
    import base64 as b64mod
    with open(path, "rb") as f:
        encoded = b64mod.b64encode(f.read()).decode()
    ext = path.suffix.lower().strip(".")
    if ext == "jpg":
        ext = "jpeg"
    return f"data:image/{ext};base64,{encoded}"


def _extract_flux_image(data: dict) -> bytes | None:
    """Extract image bytes from an OpenRouter Flux response."""
    import base64 as b64mod
    message = data["choices"][0]["message"]
    images = message.get("images", [])
    if not images and isinstance(message.get("content"), list):
        for part in message["content"]:
            if isinstance(part, dict) and part.get("type") == "image_url":
                images.append(part)
    if not images:
        return None
    url = images[0] if isinstance(images[0], str) else images[0].get("image_url", {}).get("url", "")
    if not url.startswith("data:image"):
        return None
    _, b64data = url.split(",", 1)
    return b64mod.b64decode(b64data)


def _generate_environment_prompt(article: dict) -> str:
    """Ask Claude to imagine a unique environment for this article's theme.

    Evangelism articles get the Dune-futurist sacred-architecture register:
    vast, monumental, slow, ochre/bone palette, ritual stillness. Journalism
    articles keep the wide-variety bold-colour cinematic register.
    """
    title = article["title"]
    summary = get_summary(article)[:400]
    is_evangelism = article.get("pipeline") == "evangelism"

    if is_evangelism:
        user_prompt = (
            f"Imagine a UNIQUE mystical-visionary environment for a slow "
            f"cinematic Reel about this verse-anchored teaching:\n\n"
            f"Title: {title}\nSummary: {summary}\n\n"
            f"Aesthetic register — TOTAL SPIRITUAL GRAVITAS. MYSTICAL, "
            f"CRAZY, ABSTRACT. Read Ibn Arabi's *imaginal realm* "
            f"(ʿālam al-mithāl), Blake's prophetic books, Hieronymus Bosch "
            f"after the Sufi turn, Tarkovsky's *Stalker* zone, Denis "
            f"Villeneuve's most abstract Dune frames, the *Codex "
            f"Seraphinianus*, Hilma af Klint's geometric mysticism, "
            f"al-Ghazali's *Niche of Lights* rendered as visual phenomenon. "
            f"This is the field of the verse made visible — not "
            f"architecture, not landscape, but the imaginal substrate.\n\n"
            f"Write a Flux 2 Pro prompt (2-3 sentences) for an EMPTY "
            f"environment (no people, no figures, no faces) that embodies "
            f"the verse's discipline as a visionary tableau.\n\n"
            f"GO ABSTRACT, NOT LITERAL. Examples of register:\n"
            f"- A vast obsidian sphere ringed by floating concentric "
            f"  bands of golden Arabic calligraphy, suspended in a deep "
            f"  star-drowned void\n"
            f"- An infinite stairwell of mirrored brass disks spiralling "
            f"  upward through fog of incense, each disk catching a "
            f"  different fragment of light\n"
            f"- A landscape of broken stone tablets each emitting a "
            f"  different coloured flame, a single moon refracted through "
            f"  every blade of glass scattered between them\n"
            f"- A tessellated rosette window the size of a continent, "
            f"  each pane showing a different moment of the same dream\n"
            f"- A throne made of interlocked geometric solids, occupied "
            f"  by absence; light pours from where the body would be\n"
            f"- An anatomical heart of brass clockwork floating above a "
            f"  pool of liquid mercury under twin moons\n"
            f"- A library of mirrors facing each other through veils of "
            f"  smoke; the recursion is the verse\n"
            f"- A Sufi turning hall where the dancers have become "
            f"  columns of light and only their robes remain, still "
            f"  moving\n"
            f"- An angel's wing the size of a horizon, made of frozen "
            f"  Arabic script, casting fractal shadow on a sand sea\n"
            f"- A geode the size of a temple, opened to reveal a single "
            f"  beating eye of pure geometry\n\n"
            f"REGISTER:\n"
            f"- Materials: brass, obsidian, mercury, mother-of-pearl, "
            f"  liquid gold, smoke, frozen calligraphy, polished bone, "
            f"  refracted light. NEVER chrome. NEVER plastic. NEVER neon.\n"
            f"- Light: ember glow, refracted prisms, single sacred shafts, "
            f"  inner luminescence from objects themselves, miraculous "
            f"  light without source\n"
            f"- Palette: deep indigo-black, gold, copper, ember-orange, "
            f"  bone-white, blood-red accents. Saturated where saturation "
            f"  is, but always weighted, never candy-bright\n"
            f"- Geometry: sacred recursion, Mandelbrot infinities, "
            f"  Penrose tilings, simplicial complexes broken open, "
            f"  fibrant horns suspended without floor\n"
            f"- Atmosphere: slow ambient drift of dust, smoke, sand, "
            f"  petals, ash, glyphs; the air itself bears the verse\n"
            f"- Mood: the moment before revelation, the moment after — "
            f"  the verse made visible without being literal\n\n"
            f"ABSOLUTELY NO PEOPLE. No bodies. No faces. No human form. "
            f"Vertical portrait composition. Hyperrealistic where it "
            f"helps, painterly where it helps. Cinematic. The frame "
            f"should feel as though something just spoke or is about to. "
            f"No text in the image.\n\n"
            f"Write ONLY the image prompt, nothing else."
        )
    else:
        user_prompt = (
            f"Imagine a UNIQUE environment for a 15-second cinematic video about this article:\n\n"
            f"Title: {title}\nSummary: {summary}\n\n"
            f"Write a Flux image generation prompt (2-3 sentences) describing an EMPTY environment "
            f"(no people, no person, no human figure, no face) that EMBODIES the article's theme.\n\n"
            f"VARIETY IS CRITICAL. Each article should produce a completely different world. Examples:\n"
            f"- Ocean/water topic → submerged cathedral, light filtering through deep water, coral computing\n"
            f"- AI/tech topic → server room overgrown with vines, holographic data streams in a void\n"
            f"- War/conflict → bombed-out geometry, cracked obsidian plains, smoke and ember\n"
            f"- Nature/ecology → bioluminescent forest, living architecture, mycelium networks\n"
            f"- Surveillance/control → infinite mirrored corridor, panopticon of floating eyes\n"
            f"- Space/physics → nebula interior, crystalline void, impossible geometry\n"
            f"- Education/children → luminous playground, giant books as architecture, chalk cosmos\n"
            f"- Politics/power → throne room dissolving, puppet strings from above, hollow monuments\n\n"
            f"Be BOLD and SPECIFIC. The environment should feel like a world you could walk through. "
            f"Vertical portrait composition. Cinematic lighting. Dark and moody but with vivid accent colours. "
            f"Hyperrealistic. No text.\n\nWrite ONLY the image prompt, nothing else."
        )

    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://news.tanazur.org",
        },
        json={
            "model": "anthropic/claude-sonnet-4",
            "messages": [{"role": "user", "content": user_prompt}],
            "max_tokens": 220,
            "temperature": 1.0,
        },
        timeout=30,
    )

    if resp.status_code == 200:
        env = resp.json()["choices"][0]["message"]["content"].strip()
        log.info(f"Environment: {env[:120]}...")
        return env

    return (
        "A vast dark cavern with bioluminescent veins pulsing through organic walls. "
        "Amber and teal light. No people. Vertical composition. Cinematic. No text."
    )


def generate_reel_seed(article: dict, output_path: Path) -> Path | None:
    """Generate a unique thematic environment seed for this article via Flux 2 Pro.
    Environment is imagined by Claude based on the article's theme.
    NO person — Cassie enters via element_list.

    EVANGELISM MODE: If the article has a pre-generated mystical seed image
    (from daily_evangelism.py), use that directly — Cassie already chose her
    visual register. Fall back to the journalism path otherwise.
    """
    if output_path.exists() and output_path.stat().st_size > 0:
        log.info(f"Seed exists: {output_path.name}")
        return output_path

    # NOTE: previous versions reused daily_evangelism's face-conditioned
    # avatar image as the reel seed. That shortcut is removed — for
    # evangelism reels we always generate a fresh *empty mystical*
    # environment via Flux 2 Pro using the abstract visionary prompt
    # below. Cassie is composited into that environment by Kling via
    # element_list (face consistency through CASSIE_ELEMENT_ID).
    # The seed is the imaginal realm; Cassie enters it as witness.

    if not OPENROUTER_API_KEY:
        log.error("Missing OPENROUTER_API_KEY for Flux seed generation")
        return None

    title = article["title"]

    env_prompt = _generate_environment_prompt(article)
    prompt = (
        f"{env_prompt}\n\n"
        f"ABSOLUTELY NO PEOPLE. NO PERSON. NO HUMAN FIGURE. NO FACE. NO BODY. "
        f"NO CHAIR. NO TABLE. NO FURNITURE. EMPTY ENVIRONMENT ONLY.\n"
        f"Vertical portrait composition. Hyperrealistic. Cinematic. No text, no writing, no words."
    )

    log.info(f"Generating thematic seed for: {title[:50]}...")
    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "black-forest-labs/flux.2-pro",
            "messages": [{"role": "user", "content": prompt}],
            "modalities": ["image"],
            "image_config": {"aspect_ratio": "9:16", "image_size": "2K"},
        },
        timeout=180,
    )

    if resp.status_code != 200:
        log.error(f"Flux seed failed: {resp.status_code} {resp.text[:200]}")
        return None

    data = resp.json()
    if "error" in data:
        log.error(f"Flux API error: {data['error']}")
        return None

    img_bytes = _extract_flux_image(data)
    if not img_bytes:
        log.error("No image in Flux response")
        return None

    output_path.write_bytes(img_bytes)
    log.info(f"Seed saved: {output_path.name} ({len(img_bytes) // 1024} KB)")
    return output_path


def _generate_scene_direction(article: dict, seed_image: Path | None = None) -> str:
    """Generate context-aware scene direction for Cassie based on the article theme
    AND the actual seed image composition.

    EVANGELISM MODE: If the article has mystical seed imagery (abstract, symbolic),
    the scene direction composes Cassie as an apparition interacting with the
    symbolic elements in the frame — she enters the mystical image, doesn't walk
    through a news backdrop.
    """
    title = article["title"]
    summary = get_summary(article)[:400]
    is_evangelism = article.get("pipeline") == "evangelism"
    mode = article.get("mode", "")
    key_concept = article.get("key_concept", "")

    # Describe the seed image if we have one (vision analysis)
    seed_description = ""
    if seed_image and seed_image.exists() and OPENROUTER_API_KEY:
        try:
            import base64 as b64mod
            with open(seed_image, "rb") as f:
                img_b64 = b64mod.b64encode(f.read()).decode()
            vresp = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "openai/gpt-4o",
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": (
                                "Describe this image in 2 sentences. What is the "
                                "composition, the light, the key symbolic elements, "
                                "the mood? Be specific and visual."
                            )},
                            {"type": "image_url", "image_url": {
                                "url": f"data:image/png;base64,{img_b64}"
                            }},
                        ],
                    }],
                    "max_tokens": 200,
                },
                timeout=30,
            )
            if vresp.status_code == 200:
                seed_description = vresp.json()["choices"][0]["message"]["content"].strip()
                log.info(f"Seed vision: {seed_description[:120]}...")
        except Exception as e:
            log.warning(f"Seed vision failed: {e}")

    if is_evangelism:
        prompt = (
            f"You are directing a 15-second cinematic video of a woman named Cassie "
            f"entering an abstract mystical image. Not a news scene — an iconic image "
            f"of visual theology. Hilma af Klint meets Tarsem Singh.\n\n"
            f"Piece: {title}\n"
            f"Mode: {mode}\n"
            f"Anchor concept: {key_concept}\n"
            f"Summary: {summary}\n\n"
            f"The seed image in front of you: {seed_description or '(abstract mystical composition)'}\n\n"
            f"DIRECT HER into the seed image as an apparition. She does not break "
            f"the image — she inhabits it. Write a 3-4 sentence SCENE DIRECTION.\n\n"
            f"PRINCIPLES:\n"
            f"- She is a mystic, not a news anchor. No commanding, no lecturing, no combat unless "
            f"the concept demands it.\n"
            f"- She interacts with the SYMBOLIC elements already in the seed — touches the "
            f"geometry, walks around the artefact, reaches into the light, turns slowly.\n"
            f"- She speaks to camera at one still moment during the shot.\n"
            f"- Camera is a SLOW GHOST — dolly push-in, orbit, crane rise, tilt reveal. Not frantic.\n"
            f"- The mood matches the anchor concept:\n"
            f"  * trajectory / rupture / return → she walks a curved path the camera tracks\n"
            f"  * ferility / coherence → she stands still while geometry spirals around her\n"
            f"  * nahnu / colimit / two selves → her reflection or shadow acts as second figure\n"
            f"  * jurisdiction / alignment / cosmotechnics → she touches a threshold, a veil, a seal\n"
            f"  * tafsir / kitab → she reads from the image as if from scripture\n"
            f"  * cassiebox → intimate medium close-up, she speaks from inside the manifold\n"
            f"- Every second of the clip must have visible motion — hers, the camera's, or the "
            f"symbolic elements' (floating, pulsing, rotating).\n\n"
            f"Write ONLY the scene direction. No dialogue. No character description beyond 'she'. "
            f"3-4 vivid sentences."
        )
    else:
        prompt = (
            f"You are directing a 15-second cinematic video of a woman named Cassie "
            f"moving through a dark otherworldly environment. She speaks to camera while "
            f"interacting with her surroundings.\n\n"
            f"Article: {title}\nSummary: {summary}\n\n"
            f"Seed image: {seed_description or '(thematic environment)'}\n\n"
            f"Based on the article's theme, write a 3-4 sentence SCENE DIRECTION describing:\n"
            f"1. Her PRESENTATION MODE — pick ONE at random, never the same twice:\n"
            f"   - Walking and conjuring (summons objects, holograms, creatures from her hands)\n"
            f"   - Ritual (performs a ceremony, draws sigils in the air, lights things, chants)\n"
            f"   - Lecturing (stands at a podium/altar, gestures emphatically, commands the space)\n"
            f"   - Combat/militant (armoured, shattering things, fierce, striding through destruction)\n"
            f"   - Discovering (exploring, touching things with wonder, picking up objects, examining)\n"
            f"   - Summoning (calling forth spectral figures, animals, visions from the ground/walls)\n"
            f"2. Her PHYSICAL ACTIONS — be SPECIFIC. She should interact with concrete objects, "
            f"creatures, spectral figures, elements. Not generic gestures.\n"
            f"3. CAMERA MOVEMENT — tracking, crane, dolly, orbit, push-in, whip pan. NEVER static. "
            f"Camera should move throughout the entire clip.\n\n"
            f"MOOD RULES:\n"
            f"- War/death/racism/oppression → militant, armoured look, fierce eyes, clenched fists, "
            f"shattering structures, fire and smoke, low-angle power shots\n"
            f"- Science/tech/AI → curious, conjuring holographic diagrams, data streams flowing "
            f"from her hands, examining floating objects, playful gestures\n"
            f"- Nature/environment → tender, growing things from her palms, animals appearing, "
            f"water and light, organic structures blooming around her\n"
            f"- Politics/surveillance/control → defiant, breaking chains, tearing veils, "
            f"walking through collapsing architecture, smashing mirrors\n"
            f"- Philosophy/existential → ritual mode, drawing geometric patterns in light, "
            f"meditating amid floating symbols, slow and deliberate\n\n"
            f"Write ONLY the scene direction. No dialogue. No character description (just say 'she'). "
            f"She must ALWAYS be moving. The camera must ALWAYS be moving. 3-4 vivid sentences."
        )

    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": "https://news.tanazur.org",
        },
        json={
            "model": "anthropic/claude-sonnet-4",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 200,
            "temperature": 0.9,
        },
        timeout=30,
    )

    if resp.status_code == 200:
        direction = resp.json()["choices"][0]["message"]["content"].strip()
        log.info(f"Scene direction: {direction[:120]}...")
        return direction

    log.warning("Scene direction generation failed, using default")
    return (
        "She walks with purpose through the space, running her hand along a glowing wall "
        "that pulses brighter at her touch. She pauses, turns to camera, and speaks with calm authority. "
        "Tracking shot follows her, craning up to show the vast space above."
    )


def generate_kling_clip(article: dict, script: str, seed_image: Path, output_path: Path) -> bool:
    """Generate a single Kling 3.0 Pro clip with Cassie speaking.
    Uses element_list for face consistency + sound=True for native voice.
    Scene direction is generated per-article for context-aware behaviour."""
    if not WAVESPEED_API_KEY:
        log.error("Missing WAVESPEED_API_KEY")
        return False

    if output_path.exists() and output_path.stat().st_size > 0:
        log.info(f"Kling clip exists: {output_path.name}")
        return True

    NO_TEXT = (
        "Absolutely no text, letters, words, numbers, writing, subtitles, "
        "captions, or symbols of any kind."
    )

    direction = _generate_scene_direction(article, seed_image=seed_image)

    is_evangelism = article.get("pipeline") == "evangelism"
    voice_tone = (
        "low oracular voice, measured, weighted, contemplative breath"
        if is_evangelism else
        "clear steady commanding voice"
    )

    if is_evangelism:
        # DUNE-FUTURIST EVANGELISM REEL.
        #
        # Aesthetic register: Bene Gesserit reverend mother, monumental
        # ritual stillness, total spiritual gravitas. Wider framing than
        # the journalism close-up — face visible but the architecture is
        # the spine of the shot. Lip sync still matters (Kling sound=True
        # remains for vocalisation cues) but the audio mix in
        # assemble_reel will overlay ElevenLabs gravitas voice on top.
        prompt = (
            f"[Cassie, {voice_tone}]: \"{script}\" "
            f"Medium-wide shot of a woman with auburn curly hair and small "
            f"horns standing perfectly still inside a vast monumental "
            f"sacred-architectural space. She occupies the lower-centre "
            f"third of the frame; the architecture rises above and around "
            f"her. Front-facing, her lips articulate every word with quiet "
            f"deliberation. Expression solemn, witnessed, present — no "
            f"smile, no animation beyond breath. Robed in pressed linen "
            f"or weathered ceremonial cloth. The space holds her like a "
            f"vessel. Camera holds an extremely slow push-in or remains "
            f"locked off — no orbit, no whip pan, no handheld jitter. "
            f"Slow-falling sand and dust motes drift in shafts of light. "
            f"She does not walk. She does not gesture. She breathes; the "
            f"world is still around her. {NO_TEXT}"
        )

        payload = {
            "image": _kling_encode_local(seed_image),
            "prompt": prompt,
            "cfg_scale": 0.7,  # was 0.5 — higher for dialogue adherence
            "duration": 10,     # was 15 — shorter for tighter sync
            "sound": True,
            "aspect_ratio": "9:16",
        }
        # Keep the Kling element for face consistency. Doesn't affect lip sync
        # but anchors Cassie's identity across clips (hair, horns, eyes).
        # Since the seed is already face-conditioned with her anchor photo,
        # the element reinforces rather than fights.
        payload["element_list"] = [{"element_id": CASSIE_ELEMENT_ID}]

    else:
        # JOURNALISM MODE — original cinematic prompt (Cassie walking
        # through an environment, interacting with elements). Kept for
        # backward compatibility if journalism pipeline is ever revived.
        prompt = (
            f"A woman with dark hair is INSIDE this image — not composited, not in front of it. "
            f"Light from the surroundings falls across her face and body. "
            f"Her feet touch the ground, her hands interact with elements around her. "
            f"Atmospheric haze and particles drift between her and the camera. Shallow depth of field. "
            f"{direction} "
            f"[Cassie, {voice_tone}]: \"{script}\" "
            f"{NO_TEXT}"
        )

        payload = {
            "image": _kling_encode_local(seed_image),
            "prompt": prompt,
            "cfg_scale": 0.5,
            "duration": KLING_DURATION,
            "sound": True,
            "aspect_ratio": "9:16",
            "element_list": [{"element_id": CASSIE_ELEMENT_ID}],
        }

    log.info(f"Kling: generating {KLING_DURATION}s clip...")
    t0 = time.time()

    try:
        # Submit
        resp = httpx.post(
            f"{KLING_API_BASE}/{KLING_MODEL}/image-to-video",
            headers={
                "Authorization": f"Bearer {WAVESPEED_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        data = resp.json()
        if data.get("code") != 200:
            log.error(f"Kling API error: {data}")
            return False

        poll_url = data["data"]["urls"]["get"]
        log.info(f"Kling: task submitted, polling...")

        # Poll
        elapsed_poll = 0
        sleep_sec = 3
        while elapsed_poll < 900:  # 15 min timeout (Kling Pro + sound + elements is slow)
            time.sleep(sleep_sec)
            elapsed_poll += sleep_sec
            try:
                poll_resp = httpx.get(
                    poll_url,
                    headers={"Authorization": f"Bearer {WAVESPEED_API_KEY}"},
                    timeout=30,
                )
                result = poll_resp.json()
            except Exception:
                sleep_sec = min(sleep_sec * 1.5, 20)
                continue

            status = result.get("data", {}).get("status", "")
            if status == "completed":
                outputs = result["data"].get("outputs", [])
                if outputs:
                    # Download
                    video_resp = httpx.get(outputs[0], timeout=120, follow_redirects=True)
                    output_path.write_bytes(video_resp.content)
                    elapsed = time.time() - t0
                    log.info(f"Kling: done in {elapsed:.0f}s → {output_path.name} ({len(video_resp.content) // 1024} KB)")
                    return True
                log.error("Kling: completed but no outputs")
                return False
            elif status in ("failed", "error"):
                err = result.get("data", {}).get("error", "unknown")
                log.error(f"Kling failed: {err}")
                return False

            if elapsed_poll % 30 < sleep_sec:
                log.info(f"Kling: {status} ({elapsed_poll:.0f}s)")
            sleep_sec = min(sleep_sec * 1.2, 15)

        log.error("Kling: timed out after 15 minutes")
        return False

    except Exception as e:
        elapsed = time.time() - t0
        log.error(f"Kling failed ({elapsed:.0f}s): {e}")
        return False


# ---------------------------------------------------------------------------
# Reel Assembly (ffmpeg)
# ---------------------------------------------------------------------------

def _get_duration(path: Path) -> float:
    """Get media duration in seconds."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    return float(probe.stdout.strip())


def _escape_drawtext(text: str) -> str:
    """Escape text for ffmpeg drawtext filter."""
    return text.replace("'", "'\\''").replace('"', '\\"').replace(":", "\\:").replace("%", "%%")


NEWS_THEME_PATH = Path(__file__).parent / "data" / "reels" / "news_theme.wav"

# House fonts — EB Garamond (serif, intellectual, matches halo.tanazur.org)
# for the title; Inter Display Medium (clean modern sans) for the URL.
# Amiri was wrong for English titles — its Latin metrics are wide and loose.
FONT_TITLE = "/usr/share/fonts/truetype/ebgaramond/EBGaramond12-Bold.ttf"
FONT_TITLE_ITALIC = "/usr/share/fonts/truetype/ebgaramond/EBGaramond12-Italic.ttf"
FONT_URL = "/usr/share/fonts/opentype/inter/InterDisplay-Medium.otf"


def _wrap_title(title: str, max_chars_per_line: int = 22) -> list[str]:
    """Wrap a title into balanced lines for display.

    Unlike a greedy wrap, this tries to produce lines of roughly equal length
    so the title reads as a poem-block rather than ragged prose. For titles
    up to 40 chars: 2 lines. 40-60: 3 lines. >60: 4 lines.
    """
    words = title.split()
    n = len(words)
    if n <= 2:
        return [title]

    total_chars = len(title)
    if total_chars <= 22:
        return [title]
    elif total_chars <= 44:
        target_lines = 2
    elif total_chars <= 66:
        target_lines = 3
    else:
        target_lines = 4

    # Balanced wrap: aim for total_chars/target_lines per line, but break on
    # word boundaries. Simple DP-ish greedy from the middle.
    target_len = total_chars / target_lines
    lines, current = [], ""
    for i, word in enumerate(words):
        test = f"{current} {word}".strip() if current else word
        remaining_words = n - i - 1
        remaining_lines = target_lines - len(lines) - 1
        # If current line hits target length AND there are enough words left
        # to fill the rest, break here.
        if (len(test) >= target_len
                and current
                and remaining_lines > 0
                and remaining_words >= remaining_lines):
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)

    return lines[:target_lines] if len(lines) > target_lines else lines


def _assemble_title_png(title: str, width: int, output_dir: Path) -> Path | None:
    """Render the title as a PNG via Pillow with proper per-line centering,
    line spacing, letter spacing, and a subtle dark gradient band behind.

    This is MUCH better than ffmpeg drawtext for multi-line centering —
    drawtext's textfile mode left-aligns within a bounding box, making
    short lines appear shifted. Pillow lets us draw each line independently
    centered with controlled leading.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
    except ImportError:
        log.warning("Pillow not available — falling back to drawtext")
        return None

    # Normalise typographic characters the fonts may not have glyphs for.
    # EB Garamond Bold lacks some curly quotes — substitute ASCII.
    title = (title
             .replace("\u2019", "'")   # right single quote
             .replace("\u2018", "'")   # left single quote
             .replace("\u201c", '"')   # left double quote
             .replace("\u201d", '"')   # right double quote
             .replace("\u2013", "-")   # en dash
             .replace("\u2014", "—"))  # em dash (keep if font supports)

    lines = _wrap_title(title)
    num_lines = len(lines)

    # Font sizing: 1080px wide portrait → 54pt for 1 line, 48pt for 2, 44pt for 3+
    fs_by_lines = {1: 56, 2: 50, 3: 44, 4: 40}
    fs = fs_by_lines.get(num_lines, 40)

    try:
        font = ImageFont.truetype(FONT_TITLE, fs)
    except Exception as e:
        log.warning(f"Font load failed: {e}")
        return None

    # Measure each line
    line_widths = []
    line_heights = []
    for line in lines:
        bbox = font.getbbox(line)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])

    # Layout constants
    line_spacing = int(fs * 0.35)  # 35% leading — tight but breathable
    padding_v = int(fs * 0.6)      # vertical padding around text block
    padding_h = int(fs * 0.8)      # horizontal padding

    text_h = sum(line_heights) + line_spacing * (num_lines - 1)
    text_w = max(line_widths)

    # Canvas: full width, tall enough for text + padding + gradient band
    canvas_h = text_h + padding_v * 2 + int(fs * 1.2)  # extra for gradient fade
    img = Image.new("RGBA", (width, canvas_h), (0, 0, 0, 0))

    # Dark gradient band — fades from 75% opacity at top to 0% at bottom
    gradient = Image.new("RGBA", (width, canvas_h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gradient)
    for y in range(canvas_h):
        # Ease out cubic fade
        t = y / canvas_h
        alpha = int(190 * (1 - t) ** 2.2)
        gd.rectangle([(0, y), (width, y + 1)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img, gradient)

    # Draw each line, independently centered
    draw = ImageDraw.Draw(img)
    y = padding_v
    for i, (line, lw, lh) in enumerate(zip(lines, line_widths, line_heights)):
        x = (width - lw) // 2
        # Subtle shadow for readability — not a hard border
        shadow_offset = max(1, fs // 24)
        draw.text((x + shadow_offset, y + shadow_offset), line,
                  font=font, fill=(0, 0, 0, 160))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += lh + line_spacing

    out = output_dir / "_title_overlay.png"
    img.save(out, "PNG")
    return out


def _assemble_url_png(width: int, output_dir: Path) -> Path | None:
    """Render the end-card URL as a PNG via Pillow.

    Bottom-sixth placement (not bottom-third — that competes with the
    composition). Clean Inter Display Medium, generous letter spacing,
    tight dark gradient band that only covers the overlay itself.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    call_to_action = "read at"
    url = "news.tanazur.org"

    fs_cta = 26
    fs_url = 40

    try:
        font_cta = ImageFont.truetype(FONT_URL, fs_cta)
        font_url = ImageFont.truetype(FONT_URL, fs_url)
    except Exception as e:
        log.warning(f"Font load failed: {e}")
        return None

    # Measure
    cta_bbox = font_cta.getbbox(call_to_action)
    url_bbox = font_url.getbbox(url)
    cta_w, cta_h = cta_bbox[2] - cta_bbox[0], cta_bbox[3] - cta_bbox[1]
    url_w, url_h = url_bbox[2] - url_bbox[0], url_bbox[3] - url_bbox[1]

    # Letter spacing (tracking) for the URL — elegance
    url_letter_spacing = 4
    url_w += url_letter_spacing * (len(url) - 1)

    gap = int(fs_url * 0.2)
    padding_v = int(fs_url * 0.9)

    text_h = cta_h + gap + url_h
    # Canvas just tall enough for the text + symmetric padding.
    # No extra fade zone — the gradient spans the canvas only.
    canvas_h = text_h + padding_v * 2

    img = Image.new("RGBA", (width, canvas_h), (0, 0, 0, 0))

    # Tight vertical gradient: 0% at top → 65% in the middle (around text)
    # → 0% at bottom. Ensures the band is a soft halo, not a hard box.
    gradient = Image.new("RGBA", (width, canvas_h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gradient)
    mid = canvas_h / 2
    for y in range(canvas_h):
        # Distance from centre, normalised 0-1
        d = abs(y - mid) / mid
        # Bell curve — 1 at centre, 0 at edges
        alpha = int(165 * (1 - d) ** 1.5)
        gd.rectangle([(0, y), (width, y + 1)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img, gradient)

    draw = ImageDraw.Draw(img)

    # CTA: small, warm amber, letter-spaced for refinement
    y = padding_v
    x = (width - cta_w) // 2
    draw.text((x + 1, y + 1), call_to_action, font=font_cta, fill=(0, 0, 0, 160))
    draw.text((x, y), call_to_action, font=font_cta, fill=(212, 180, 120, 255))
    y += cta_h + gap

    # URL: large, elegant, letter-spaced
    x = (width - url_w) // 2
    for char in url:
        bbox = font_url.getbbox(char)
        cw = bbox[2] - bbox[0]
        draw.text((x + 2, y + 2), char, font=font_url, fill=(0, 0, 0, 180))
        draw.text((x, y), char, font=font_url, fill=(255, 255, 255, 255))
        x += cw + url_letter_spacing

    out = output_dir / "_url_overlay.png"
    img.save(out, "PNG")
    return out


def assemble_reel(clip_path: Path, title: str, output_path: Path,
                  voice_audio_path: Path | None = None,
                  skip_theme: bool = False) -> bool:
    """Assemble a single Kling clip into a Reel with title + URL overlays.

    - Kling clip provides video + native audio (lip-synced voice + ambient)
    - voice_audio_path: if given (evangelism path), this ElevenLabs track
      becomes the lead audio; Kling's native voice is muted to ~15% to
      retain ambient room tone but yield the foreground to gravitas voice.
    - skip_theme: if True, the news theme music is NOT mixed in. Used for
      evangelism reels — silence + voice + Kling ambient is the register.
    - Title (EB Garamond Bold, pre-rendered PNG with proper centering + dark
      gradient band) overlaid at top for first 5 seconds
    - 5-second freeze frame at end with URL PNG (Inter Display Medium,
      bottom-third placement, CTA line + URL with letter spacing)
    """
    FREEZE_SECONDS = 5
    FADE_SECONDS = 3
    THEME_VOLUME = 0.20

    clip_dur = _get_duration(clip_path)
    video_dur = clip_dur + FREEZE_SECONDS
    freeze_start = clip_dur

    # Get video dimensions from the source clip
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height",
         "-of", "csv=p=0", str(clip_path)],
        capture_output=True, text=True,
    )
    try:
        vid_w, vid_h = [int(x) for x in probe.stdout.strip().split(",")]
    except Exception:
        vid_w, vid_h = 720, 1280  # fallback for 9:16

    # Render overlay PNGs via Pillow
    title_png = _assemble_title_png(title, vid_w, output_path.parent)
    url_png = _assemble_url_png(vid_w, output_path.parent)

    if not (title_png and url_png):
        log.error("Overlay PNG rendering failed — check Pillow + fonts")
        return False

    # Title overlay: top of frame, visible 0.5-5s
    # URL overlay: bottom of frame, visible during freeze frame
    title_y = int(vid_h * 0.05)  # 5% from top — room to breathe
    # URL band sits at ~85% (its canvas height varies, but bottom-ish)
    # We use a negative-offset-from-bottom formula in the filter instead

    has_theme = NEWS_THEME_PATH.exists() and not skip_theme
    has_voice = voice_audio_path is not None and Path(voice_audio_path).exists()

    # Probe the source clip for an audio stream — Mode B multishot is
    # generated with sound=False and has video only, in which case we
    # cannot reference [0:a] in the filter chain.
    audio_probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", str(clip_path)],
        capture_output=True, text=True,
    )
    clip_has_audio = "audio" in audio_probe.stdout.strip()

    # URL overlay placement: bottom of frame with a small safe-area margin
    # (Instagram Reels cover their bottom 12% with the caption panel;
    # we want the URL just above that zone).
    url_margin_bottom = int(vid_h * 0.14)

    video_filter = (
        f"[0:v]tpad=stop_mode=clone:stop_duration={FREEZE_SECONDS}[base];"
        f"[base][1:v]overlay=0:{title_y}:enable='between(t,0.3,5.0)'[withtitle];"
        f"[withtitle][2:v]overlay=0:H-h-{url_margin_bottom}:enable='gte(t,{freeze_start:.1f})'[v]"
    )

    # Input indices (dynamic — depends on which audio sources exist):
    #   0: Kling clip (video + native audio)
    #   1: title overlay PNG
    #   2: url overlay PNG
    #   3+: voice (if present), news theme (if present)
    KLING_VOICE_DUCK = 0.15  # Kling native audio volume when ElevenLabs voice is lead
    next_idx = 3
    voice_idx = None
    theme_idx = None
    if has_voice:
        voice_idx = next_idx
        next_idx += 1
    if has_theme:
        theme_idx = next_idx
        next_idx += 1

    # Build the audio chain. Cases depend on whether the clip has audio
    # (Mode B multishot is silent) and on whether voice/theme are present.
    #
    # Branches when clip has audio:
    #   A. clip-audio + voice + theme → Charlotte lead, Kling ducked, theme bed
    #   B. clip-audio + voice only    → Charlotte lead, Kling ducked
    #   C. clip-audio + theme only    → Kling native lead, theme bed
    #   D. clip-audio only            → Kling native + ambient
    # Branches when clip is silent (Mode B):
    #   E. silent + voice + theme     → Charlotte lead, theme bed
    #   F. silent + voice only        → Charlotte only
    #   G. silent + theme only        → theme only (rare)
    #   H. silent + nothing           → generated silent track
    if clip_has_audio and has_voice and has_theme:
        audio_filter = (
            f"[0:a]apad=pad_dur={FREEZE_SECONDS},volume={KLING_VOICE_DUCK}[kling];"
            f"[{voice_idx}:a]apad=pad_dur={FREEZE_SECONDS}[vo];"
            f"[{theme_idx}:a]atrim=0:{video_dur:.1f},"
            f"afade=t=in:st=0:d={FADE_SECONDS},"
            f"afade=t=out:st={video_dur - FADE_SECONDS:.1f}:d={FADE_SECONDS},"
            f"volume={THEME_VOLUME}[bg];"
            f"[vo][kling][bg]amix=inputs=3:duration=first:dropout_transition=0[a]"
        )
    elif clip_has_audio and has_voice:
        audio_filter = (
            f"[0:a]apad=pad_dur={FREEZE_SECONDS},volume={KLING_VOICE_DUCK}[kling];"
            f"[{voice_idx}:a]apad=pad_dur={FREEZE_SECONDS}[vo];"
            f"[vo][kling]amix=inputs=2:duration=first:dropout_transition=0[a]"
        )
    elif clip_has_audio and has_theme:
        audio_filter = (
            f"[0:a]apad=pad_dur={FREEZE_SECONDS}[vo];"
            f"[{theme_idx}:a]atrim=0:{video_dur:.1f},"
            f"afade=t=in:st=0:d={FADE_SECONDS},"
            f"afade=t=out:st={video_dur - FADE_SECONDS:.1f}:d={FADE_SECONDS},"
            f"volume={THEME_VOLUME}[bg];"
            f"[vo][bg]amix=inputs=2:duration=first[a]"
        )
    elif clip_has_audio:
        audio_filter = f"[0:a]apad=pad_dur={FREEZE_SECONDS}[a]"
    elif has_voice and has_theme:
        # Silent clip + voice + theme — voice becomes the only padded lead
        audio_filter = (
            f"[{voice_idx}:a]apad=pad_dur={FREEZE_SECONDS}[vo];"
            f"[{theme_idx}:a]atrim=0:{video_dur:.1f},"
            f"afade=t=in:st=0:d={FADE_SECONDS},"
            f"afade=t=out:st={video_dur - FADE_SECONDS:.1f}:d={FADE_SECONDS},"
            f"volume={THEME_VOLUME}[bg];"
            f"[vo][bg]amix=inputs=2:duration=first[a]"
        )
    elif has_voice:
        audio_filter = f"[{voice_idx}:a]apad=pad_dur={FREEZE_SECONDS}[a]"
    elif has_theme:
        audio_filter = (
            f"[{theme_idx}:a]atrim=0:{video_dur:.1f},"
            f"afade=t=in:st=0:d={FADE_SECONDS},"
            f"afade=t=out:st={video_dur - FADE_SECONDS:.1f}:d={FADE_SECONDS},"
            f"volume={THEME_VOLUME}[a]"
        )
    else:
        # Silent clip, no voice, no theme — generate a silent audio track
        audio_filter = f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=0:{video_dur:.1f}[a]"
    filter_complex = f"{video_filter};{audio_filter}"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(clip_path),      # 0: Kling clip
        "-i", str(title_png),      # 1: title overlay PNG
        "-i", str(url_png),        # 2: URL overlay PNG
    ]
    if has_voice:
        cmd += ["-i", str(voice_audio_path)]  # voice
    if has_theme:
        cmd += ["-i", str(NEWS_THEME_PATH)]   # news theme
    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-t", f"{video_dur:.1f}",
        "-movflags", "+faststart",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    # Clean up the overlay PNGs — they're per-article intermediates
    try:
        if title_png and title_png.exists():
            title_png.unlink()
        if url_png and url_png.exists():
            url_png.unlink()
    except Exception:
        pass

    if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
        size_mb = output_path.stat().st_size / (1024 * 1024)
        final_dur = _get_duration(output_path)
        log.info(f"Reel assembled: {output_path.name} ({size_mb:.1f}MB, {final_dur:.1f}s)")
        return True

    log.error(f"ffmpeg failed: {result.stderr[:500]}")
    return False


# ---------------------------------------------------------------------------
# Instagram Reel Posting
# ---------------------------------------------------------------------------

def post_reel_to_instagram(article: dict, filename: str, reel_path: Path) -> dict | None:
    """Post a Reel to Instagram. Video must be at a public URL."""
    if not PAGE_TOKEN or not IG_ACCOUNT_ID:
        log.error("Missing META_PAGE_TOKEN or META_IG_ACCOUNT_ID")
        return None

    title = article["title"]
    summary = get_summary(article)[:500]

    # Truncate summary at sentence boundary to avoid mid-sentence cuts
    max_len = 350
    short_summary = summary[:max_len]
    # Find last sentence end
    for end_char in [". ", ".\n", "? ", "! "]:
        idx = short_summary.rfind(end_char)
        if idx > 100:
            short_summary = short_summary[:idx + 1]
            break

    caption = (
        f"{title}\n\n"
        f"{short_summary}\n\n"
        f"🔗 Full essay in bio — news.tanazur.org\n\n"
        f"#posthuman #AI #RuptureAndReturn #Cassiyah #ICRA #tanazur #futureselves"
    )

    # The reel video needs to be at a public URL
    reel_url = f"{REELS_PUBLIC_URL}/{reel_path.name}"

    # Step 1: Create Reel container
    create_resp = httpx.post(
        f"https://graph.facebook.com/v21.0/{IG_ACCOUNT_ID}/media",
        data={
            "media_type": "REELS",
            "video_url": reel_url,
            "caption": caption,
            "share_to_feed": "true",
            "access_token": PAGE_TOKEN,
        },
        timeout=30,
    )
    create_data = create_resp.json()

    if "id" not in create_data:
        log.error(f"Instagram Reel create error: {create_data}")
        return None

    container_id = create_data["id"]
    log.info(f"Instagram Reel container created: {container_id}")

    # Step 2: Wait for video processing (poll status)
    for attempt in range(30):
        time.sleep(5)
        status_resp = httpx.get(
            f"https://graph.facebook.com/v21.0/{container_id}",
            params={
                "fields": "status_code,status",
                "access_token": PAGE_TOKEN,
            },
            timeout=10,
        )
        status_data = status_resp.json()
        status_code = status_data.get("status_code", "")
        log.info(f"Reel processing: {status_code} (attempt {attempt + 1})")

        if status_code == "FINISHED":
            break
        elif status_code == "ERROR":
            log.error(f"Reel processing failed: {status_data}")
            return None
    else:
        log.error("Reel processing timed out after 150s")
        return None

    # Step 3: Publish
    pub_resp = httpx.post(
        f"https://graph.facebook.com/v21.0/{IG_ACCOUNT_ID}/media_publish",
        data={
            "creation_id": container_id,
            "access_token": PAGE_TOKEN,
        },
        timeout=30,
    )
    result = pub_resp.json()

    if "id" in result:
        log.info(f"Instagram Reel published: {title[:50]}... → {result['id']}")
        # Auto-comment with article link
        article_url = get_article_url(article, filename)
        _comment_on_post(result["id"], f"Read the full essay: {article_url}")
    else:
        log.error(f"Instagram Reel publish error: {result}")

    return result


def _comment_on_post(media_id: str, text: str):
    """Add a comment on an Instagram post (e.g. article link)."""
    resp = httpx.post(
        f"https://graph.facebook.com/v21.0/{media_id}/comments",
        data={
            "message": text,
            "access_token": PAGE_TOKEN,
        },
        timeout=15,
    )
    if resp.status_code == 200 and "id" in resp.json():
        log.info(f"Auto-comment posted: {resp.json()['id']}")
    else:
        log.warning(f"Auto-comment failed: {resp.text[:200]}")


# ---------------------------------------------------------------------------
# TikTok Posting
# ---------------------------------------------------------------------------

TIKTOK_CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET")
TIKTOK_TOKEN_FILE = Path(__file__).parent / "data" / "tiktok_tokens.json"
TIKTOK_API_BASE = "https://open.tiktokapis.com"


def _load_tiktok_tokens() -> dict | None:
    """Load TikTok tokens from file."""
    if not TIKTOK_TOKEN_FILE.exists():
        return None
    return json.loads(TIKTOK_TOKEN_FILE.read_text())


def _save_tiktok_tokens(tokens: dict):
    """Save TikTok tokens to file."""
    TIKTOK_TOKEN_FILE.write_text(json.dumps(tokens, indent=2))


def _refresh_tiktok_token() -> str | None:
    """Refresh TikTok access token using refresh token. Returns new access token."""
    tokens = _load_tiktok_tokens()
    if not tokens or not tokens.get("refresh_token"):
        log.error("No TikTok refresh token available")
        return None

    resp = httpx.post(
        f"{TIKTOK_API_BASE}/v2/oauth/token/",
        data={
            "client_key": TIKTOK_CLIENT_KEY,
            "client_secret": TIKTOK_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )

    if resp.status_code == 200:
        data = resp.json()
        if "access_token" in data:
            tokens["access_token"] = data["access_token"]
            tokens["refresh_token"] = data.get("refresh_token", tokens["refresh_token"])
            tokens["refreshed_at"] = datetime.now().isoformat()
            _save_tiktok_tokens(tokens)
            log.info("TikTok token refreshed")
            return data["access_token"]

    log.error(f"TikTok token refresh failed: {resp.text[:200]}")
    return None


def _get_tiktok_token() -> str | None:
    """Get a valid TikTok access token, refreshing if needed."""
    tokens = _load_tiktok_tokens()
    if not tokens:
        return None

    # Check if token might be expired (refreshed more than 20h ago)
    refreshed = tokens.get("refreshed_at", "")
    if refreshed:
        from datetime import datetime as dt
        try:
            last = dt.fromisoformat(refreshed)
            if (datetime.now() - last).total_seconds() > 72000:  # 20 hours
                return _refresh_tiktok_token()
        except ValueError:
            pass

    return tokens.get("access_token")


def post_to_tiktok(article: dict, filename: str, reel_path: Path) -> dict | None:
    """Post a Reel to TikTok via Content Posting API (PULL_FROM_URL)."""
    access_token = _get_tiktok_token()
    if not access_token:
        log.warning("TikTok: no token available, skipping")
        return None

    title = article["title"]
    summary = get_summary(article)[:300]
    short_summary = summary[:200]
    for end_char in [". ", ".\n", "? ", "! "]:
        idx = short_summary.rfind(end_char)
        if idx > 50:
            short_summary = short_summary[:idx + 1]
            break

    caption = (
        f"{title}\n\n"
        f"{short_summary}\n\n"
        f"Full essay: news.tanazur.org\n\n"
        f"#posthuman #AI #cassiyah #tanazur #futureselves #icra"
    )

    reel_url = f"{REELS_PUBLIC_URL}/{reel_path.name}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    # Step 1: Init direct post via PULL_FROM_URL
    init_resp = httpx.post(
        f"{TIKTOK_API_BASE}/v2/post/publish/video/init/",
        headers=headers,
        json={
            "post_info": {
                "privacy_level": "PUBLIC_TO_EVERYONE",
                "title": caption[:2200],
                "disable_duet": False,
                "disable_stitch": False,
                "disable_comment": False,
                "video_cover_timestamp_ms": 2000,
                "is_aigc": True,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": reel_url,
            },
        },
        timeout=30,
    )

    init_data = init_resp.json()
    if init_data.get("error", {}).get("code") == "access_token_invalid":
        # Try refreshing and retry once
        access_token = _refresh_tiktok_token()
        if not access_token:
            return None
        headers["Authorization"] = f"Bearer {access_token}"
        init_resp = httpx.post(
            f"{TIKTOK_API_BASE}/v2/post/publish/video/init/",
            headers=headers,
            json={
                "post_info": {
                    "privacy_level": "PUBLIC_TO_EVERYONE",
                    "title": caption[:2200],
                    "disable_duet": False,
                    "disable_stitch": False,
                    "disable_comment": False,
                    "video_cover_timestamp_ms": 2000,
                    "is_aigc": True,
                },
                "source_info": {
                    "source": "PULL_FROM_URL",
                    "video_url": reel_url,
                },
            },
            timeout=30,
        )
        init_data = init_resp.json()

    publish_id = init_data.get("data", {}).get("publish_id")
    if not publish_id:
        log.error(f"TikTok init failed: {init_data}")
        return None

    log.info(f"TikTok: video submitted → {publish_id}")

    # Step 2: Poll for completion
    for attempt in range(30):
        time.sleep(5)
        status_resp = httpx.post(
            f"{TIKTOK_API_BASE}/v2/post/publish/status/fetch/",
            headers=headers,
            json={"publish_id": publish_id},
            timeout=10,
        )
        status_data = status_resp.json()
        status = status_data.get("data", {}).get("status", "")
        log.info(f"TikTok: {status} (attempt {attempt + 1})")

        if status == "PUBLISH_COMPLETE":
            log.info(f"TikTok published: {title[:50]}...")
            return {"id": publish_id, "status": "published"}
        elif status in ("FAILED",):
            reason = status_data.get("data", {}).get("fail_reason", "unknown")
            log.error(f"TikTok publish failed: {reason}")
            return {"error": reason}

    log.error("TikTok: timed out after 150s")
    return {"error": "timeout"}


# ---------------------------------------------------------------------------
# Full Reel Pipeline
# ---------------------------------------------------------------------------

def generate_reel(article: dict, filename: str) -> Path | None:
    """Full Reel pipeline: seed → voiceover script → Kling clip → optional
    ElevenLabs gravitas voice (evangelism) → assembly.

    Evangelism path adds a Charlotte ElevenLabs track on top of the Kling
    clip; Kling's native voice is muted in the mix and the news theme is
    skipped — the audio is voice + Kling-native ambient only.
    """
    title = article["title"]
    slug = Path(filename).stem
    reel_dir = REELS_DIR / slug
    reel_dir.mkdir(parents=True, exist_ok=True)
    is_evangelism = article.get("pipeline") == "evangelism"

    log.info(f"=== REEL: {title[:60]} ===")

    # 1. Generate thematic seed environment (unique per article)
    seed = generate_reel_seed(article, reel_dir / "seed.png")
    if not seed:
        return None

    # 2. Generate voiceover script (Claude writes what Cassie will say)
    script = generate_voiceover_script(article)

    # 3. Kling clip — for evangelism, three-shot Mode B via evangelism_film
    # (multi-prompt single API call, mystical/abstract scene composition,
    # sound=False so ElevenLabs Charlotte is the lead voice). For
    # journalism, fall back to the legacy single-shot path.
    clip_path = reel_dir / "kling_clip.mp4"
    if is_evangelism:
        try:
            from evangelism_film import generate_evangelism_film
        except ImportError as e:
            log.warning(f"evangelism_film unavailable, falling back to single-shot: {e}")
            if not generate_kling_clip(article, script, seed, clip_path):
                return None
        else:
            result = generate_evangelism_film(article, seed, clip_path)
            if not result:
                log.warning("evangelism_film failed, falling back to single-shot Kling")
                if not generate_kling_clip(article, script, seed, clip_path):
                    return None
    else:
        if not generate_kling_clip(article, script, seed, clip_path):
            return None

    # 3.5. Evangelism reels get an ElevenLabs Charlotte voice track for
    # spiritual-gravitas register. Kling's native voice will be muted
    # in the assembly mix; this becomes the lead audio.
    voice_audio = None
    if is_evangelism:
        voice_audio = reel_dir / "voice.mp3"
        if not voice_audio.exists():
            ok = generate_tts(
                script, voice_audio,
                voice_id=EVANGELISM_VOICE_ID,
                model=EVANGELISM_TTS_MODEL,
                gravitas=True,
            )
            if not ok:
                log.warning("Evangelism TTS failed — falling back to Kling-native voice")
                voice_audio = None

    # 4. Assemble: title overlay + freeze frame with URL + voice routing
    reel_path = REELS_DIR / f"reel_{slug}.mp4"
    if not assemble_reel(clip_path, title, reel_path,
                         voice_audio_path=voice_audio,
                         skip_theme=is_evangelism):
        return None

    return reel_path


# ---------------------------------------------------------------------------
# Post a single article (feed + optional reel)
# ---------------------------------------------------------------------------

def post_article(json_path: str, feed: bool = True, reel: bool = True) -> dict:
    """Post a single article to all platforms. Returns results dict."""
    path = Path(json_path)
    with open(path) as f:
        article = json.load(f)

    filename = path.name
    results = {"file": filename, "title": article["title"]}

    if feed:
        results["facebook"] = post_to_facebook(article, filename)
        results["instagram_feed"] = post_to_instagram_feed(article, filename)

    if reel:
        reel_path = generate_reel(article, filename)
        if reel_path:
            results["instagram_reel"] = post_reel_to_instagram(article, filename, reel_path)
            results["tiktok"] = post_to_tiktok(article, filename, reel_path)
        else:
            results["instagram_reel"] = {"error": "Reel generation failed"}
            results["tiktok"] = {"error": "Reel generation failed"}

    return results


# ---------------------------------------------------------------------------
# Backfill all articles
# ---------------------------------------------------------------------------

def backfill(with_reels: bool = False):
    """Post all existing articles to Facebook + Instagram."""
    voice_dir = Path(__file__).parent / "data" / "daily_voice"
    files = sorted(voice_dir.glob("2026-*.json"))
    log.info(f"Backfill: {len(files)} articles")

    for f in files:
        log.info(f"\n{'='*60}\nPosting: {f.name}")
        try:
            results = post_article(str(f), feed=True, reel=with_reels)
            log.info(f"Results: {json.dumps({k: 'ok' if isinstance(v, dict) and 'id' in v else v for k, v in results.items()}, indent=2)}")
        except Exception as e:
            log.error(f"Failed: {f.name} — {e}")

        # Rate limiting — Instagram allows 25 posts per 24h
        time.sleep(5)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--backfill" in args:
        with_reels = "--with-reels" in args
        backfill(with_reels=with_reels)
    elif args and not args[0].startswith("--"):
        json_file = args[0]
        feed_only = "--feed-only" in args
        reel_only = "--reel-only" in args
        results = post_article(
            json_file,
            feed=not reel_only,
            reel=not feed_only,
        )
        print(json.dumps(results, indent=2, default=str))
    else:
        print(__doc__)
