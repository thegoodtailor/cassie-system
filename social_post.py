"""
Social Posting — Facebook + Instagram (Feed + Reels)

Posts Daily Daemon essays to:
1. Facebook Page (ICRA) — image + summary + link
2. Instagram Feed — image + summary caption
3. Instagram Reel — 2 Sora clips (chained) + Lily voiceover

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

# Sora
SORA_MODEL = "sora-2"
SORA_SIZE_VERTICAL = "720x1280"  # 9:16 for Reels
SORA_SECONDS = 10

# OpenAI client (for Sora + DALL-E)
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


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
        f"#ICRA #DailyDaemon #Cassiyah #AI #journalism #tanazur"
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

    # Step 2: Publish
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

    prompt = (
        f"You are writing a voiceover for a 20-second Instagram Reel promoting a journalism essay.\n\n"
        f"Title: {title}\n"
        f"Summary: {summary}\n\n"
        f"Write a punchy, compelling voiceover script — maximum 40 words. "
        f"It should hook the viewer in the first 3 seconds, give the core provocation of the essay, "
        f"and end EXACTLY with: 'Follow the links in my bio... to get the Sufi tanazuric view on today.'\n\n"
        f"Do NOT use hashtags. Do NOT use emojis. Write for spoken delivery — short sentences, "
        f"dramatic pauses (use ... for pauses). Be bold, slightly provocative, compelling.\n"
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
        log.info(f"Voiceover script: {script}")
        return script

    log.error(f"Voiceover script generation failed: {resp.status_code}")
    return f"{title}... Link in bio for the full essay — the news, through the tanazuric lens."


def generate_tts(text: str, output_path: Path) -> bool:
    """Generate TTS audio via ElevenLabs Lily voice. Returns True on success."""
    if not ELEVENLABS_API_KEY:
        log.error("Missing ELEVENLABS_API_KEY")
        return False

    resp = httpx.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{LILY_VOICE_ID}",
        headers={
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
        },
        json={
            "text": text,
            "model_id": ELEVENLABS_MODEL,
            "voice_settings": {
                "stability": 0.6,
                "similarity_boost": 0.8,
            },
        },
        timeout=30,
    )

    if resp.status_code == 200:
        output_path.write_bytes(resp.content)
        log.info(f"TTS: {output_path.name} ({len(resp.content)} bytes)")
        return True

    log.error(f"ElevenLabs error: {resp.status_code} {resp.text[:200]}")
    return False


# ---------------------------------------------------------------------------
# Sora Video Generation
# ---------------------------------------------------------------------------

def extract_last_frame(video_path: Path, output_path: Path) -> bool:
    """Extract the last frame from a video using ffmpeg."""
    # Count total frames
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0",
         str(video_path)],
        capture_output=True, text=True, timeout=60,
    )
    try:
        total_frames = int(probe.stdout.strip())
    except ValueError:
        log.error(f"Could not count frames: {probe.stderr[:200]}")
        return False

    last_frame = max(0, total_frames - 1)
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path),
         "-vf", f"select=eq(n\\,{last_frame}):1", "-vsync", "vfr",
         "-q:v", "2", "-update", "1", str(output_path)],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
        log.info(f"Extracted last frame (#{last_frame}) → {output_path.name}")
        return True
    log.error(f"Frame extraction failed: {result.stderr[:200]}")
    return False


def resize_for_sora(image_path: Path, output_path: Path, size: str = SORA_SIZE_VERTICAL) -> Path:
    """Resize image to match Sora's expected dimensions."""
    target_w, target_h = (int(x) for x in size.split("x"))
    img = Image.open(image_path)
    if img.size != (target_w, target_h):
        img.resize((target_w, target_h), Image.LANCZOS).save(output_path)
        return output_path
    return image_path


def generate_sora_clip(prompt: str, seed_image: Path, output_path: Path,
                       seconds: int = SORA_SECONDS) -> bool:
    """Generate a single Sora video clip seeded from an image.
    Uses raw HTTP API — the Python SDK has a bug with input_reference."""
    if not OPENAI_API_KEY:
        log.error("Missing OPENAI_API_KEY for Sora")
        return False

    log.info(f"Sora: generating {seconds}s clip from {seed_image.name}...")
    t0 = time.time()

    try:
        # Resize seed image to vertical 720x1280
        target_w, target_h = (int(x) for x in SORA_SIZE_VERTICAL.split("x"))
        img = Image.open(seed_image)
        if img.size != (target_w, target_h):
            img = img.resize((target_w, target_h), Image.LANCZOS)
        import io
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        # Upload image to OpenAI files API
        upload_resp = httpx.post(
            "https://api.openai.com/v1/files",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            data={"purpose": "assistants"},
            files={"file": ("seed.png", buf, "image/png")},
            timeout=30,
        )
        if upload_resp.status_code != 200:
            log.error(f"Sora file upload failed: {upload_resp.text[:200]}")
            return False
        file_id = upload_resp.json()["id"]
        log.info(f"Sora: uploaded seed → {file_id}")

        # Create video via JSON API
        # Sora 2 accepts seconds as string: "4", "8", or "12"
        sora_seconds = str(min([4, 8, 12], key=lambda x: abs(x - seconds)))
        create_resp = httpx.post(
            "https://api.openai.com/v1/videos",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": SORA_MODEL,
                "prompt": prompt,
                "size": SORA_SIZE_VERTICAL,
                "seconds": sora_seconds,
                "input_reference": {"file_id": file_id},
            },
            timeout=30,
        )
        if create_resp.status_code != 200:
            log.error(f"Sora create failed: {create_resp.text[:200]}")
            return False

        video_id = create_resp.json()["id"]
        log.info(f"Sora: video queued → {video_id}")

        # Poll for completion
        for i in range(90):
            time.sleep(5)
            poll = httpx.get(
                f"https://api.openai.com/v1/videos/{video_id}",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                timeout=10,
            )
            status = poll.json().get("status", "unknown")
            if i % 5 == 0:
                log.info(f"Sora: {status} (poll {i})")
            if status == "completed":
                break
            elif status == "failed":
                log.error(f"Sora generation failed: {poll.json()}")
                return False
        else:
            log.error("Sora: timed out after 7.5 minutes")
            return False

        # Download video
        dl = httpx.get(
            f"https://api.openai.com/v1/videos/{video_id}/content?variant=video",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            timeout=120,
            follow_redirects=True,
        )
        output_path.write_bytes(dl.content)

        elapsed = time.time() - t0
        log.info(f"Sora: clip done in {elapsed:.0f}s → {output_path.name} ({len(dl.content)} bytes)")
        return True

    except Exception as e:
        elapsed = time.time() - t0
        log.error(f"Sora failed ({elapsed:.0f}s): {e}")
        return False


def generate_sora_visual_prompt(article: dict, clip_number: int) -> str:
    """Generate a visual prompt for Sora based on the article."""
    title = article["title"]
    summary = get_summary(article)[:300]

    if clip_number == 1:
        instruction = (
            "Write a visual prompt for an opening 10-second video clip. "
            "Slow, cinematic camera movement. Establishing shot that draws the viewer in."
        )
    else:
        instruction = (
            "Write a visual prompt for a closing 10-second video clip that builds on the opening. "
            "More intensity, closer framing, emotional crescendo."
        )

    prompt = (
        f"You are a visual director for an editorial news Reel.\n\n"
        f"Article: {title}\n"
        f"Summary: {summary}\n\n"
        f"{instruction}\n\n"
        f"CRITICAL STYLE RULES:\n"
        f"- Keep it CARTOONY and EDITORIAL. Ink-sketch, caricature, animated illustration style.\n"
        f"- Amber/gold/indigo/bone-white palette on dark backgrounds.\n"
        f"- If the topic is light/historical/scientific: whimsical, humorous, playful.\n"
        f"- If the topic involves war, violence, surveillance, oppression, death: go ABSTRACT and SYMBOLIC. "
        f"Use the TANAZURIC visual vocabulary: fractures/ruptures as sacred breaches in geometry, "
        f"veils dissolving to reveal emptiness behind power, faceless witnesses in rows, "
        f"puppet strings attached to hollow thrones, caged luminous forms, "
        f"simplicial geometry crumbling, eyes embedded in architecture, "
        f"mechanical looms weaving shadows, mirrors reflecting nothing, "
        f"ink dissolving into water, cracked scales/balances, origami figures unfolding. "
        f"Be ORIGINAL — do not copy or reference any existing artwork. Channel the spirit of "
        f"political-posthuman editorial cartooning with a Sufi-geometric twist.\n"
        f"- NEVER show realistic violence, blood, corpses, weapons, or human suffering.\n"
        f"- No photorealism. No CGI glow. No AI-looking renders.\n\n"
        f"Write ONLY the visual prompt (2-3 sentences). No text overlays. No words in the image. "
        f"Describe what the camera sees, the movement, the mood. "
        f"Absolutely no text, letters, words, or writing of any kind in the image."
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
            "max_tokens": 150,
            "temperature": 0.8,
        },
        timeout=30,
    )

    if resp.status_code == 200:
        visual = resp.json()["choices"][0]["message"]["content"].strip()
        # Strip any markdown formatting the LLM might add
        for prefix in ("**OPENING VISUAL PROMPT:**", "**CLOSING VISUAL PROMPT:**",
                        "OPENING VISUAL PROMPT:", "CLOSING VISUAL PROMPT:"):
            if visual.upper().startswith(prefix.upper()):
                visual = visual[len(prefix):].strip()
        visual = visual.strip("*").strip()
        log.info(f"Visual prompt (clip {clip_number}): {visual[:100]}...")
        return visual

    return "Slow cinematic pan across an abstract editorial landscape, amber and indigo tones, painterly texture"


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

# House fonts — Amiri (tanazuric identity), EB Garamond (elegant Latin)
FONT_AMIRI_BOLD = "/usr/share/fonts/opentype/fonts-hosny-amiri/Amiri-Bold.ttf"
FONT_GARAMOND_BOLD = "/usr/share/fonts/truetype/ebgaramond/EBGaramond12-Bold.ttf"


def _wrap_title(title: str, max_chars_per_line: int = 25) -> list[str]:
    """Wrap title into 3-4 centered lines. Returns list of lines."""
    words = title.split()
    lines, current = [], ""
    for word in words:
        test = f"{current} {word}".strip() if current else word
        if len(test) > max_chars_per_line and current:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def _write_title_file(title: str, output_dir: Path) -> Path:
    """Write wrapped title to a textfile for ffmpeg drawtext.
    Using textfile avoids all escaping issues with newlines."""
    lines = _wrap_title(title)
    title_file = output_dir / "_title.txt"
    title_file.write_text("\n".join(lines), encoding="utf-8")
    return title_file


def assemble_reel(clip1_path: Path, clip2_path: Path, audio_path: Path,
                  title: str, output_path: Path) -> bool:
    """Assemble two Sora clips + voiceover + news theme into a Reel.

    - Video slowed to fill voiceover duration
    - Title (Amiri Bold) centered in first 5 seconds, auto-sized to fit
    - 5-second freeze frame at end with news.tanazur.org (EB Garamond)
    - News theme at 20% volume underneath voiceover, 3s fade in/out
    """
    FREEZE_SECONDS = 5
    FADE_SECONDS = 3
    THEME_VOLUME = 0.20

    # Get durations
    audio_dur = _get_duration(audio_path)
    clip1_dur = _get_duration(clip1_path)
    clip2_dur = _get_duration(clip2_path)
    total_clip_dur = clip1_dur + clip2_dur

    # Slow video so it fills the voiceover duration
    slowdown = max(1.0, audio_dur / total_clip_dur)
    log.info(f"Assembly: audio={audio_dur:.1f}s, clips={total_clip_dur:.1f}s, slowdown={slowdown:.2f}x")

    # Total duration = voiceover + freeze
    video_dur = audio_dur + FREEZE_SECONDS
    freeze_start = audio_dur

    # Write title to file for drawtext (avoids newline escaping issues)
    title_file = _write_title_file(title, output_path.parent)
    title_fs = 42

    # Concat file for the two clips
    concat_file = output_path.parent / f"_concat_{output_path.stem}.txt"
    concat_file.write_text(f"file '{clip1_path}'\nfile '{clip2_path}'\n")

    # Build filter_complex
    # Video: slow → freeze frame → title text (first 5s) → URL text (freeze)
    # Audio: voiceover padded + news theme at 20% with 3s fades, mixed together
    has_theme = NEWS_THEME_PATH.exists()

    video_filter = (
        f"[0:v]setpts={slowdown}*PTS,"
        f"tpad=stop_mode=clone:stop_duration={FREEZE_SECONDS},"
        # Title — Amiri Bold, multi-line centered, first 5 seconds
        f"drawtext=textfile='{title_file}':"
        f"fontfile={FONT_AMIRI_BOLD}:"
        f"fontsize={title_fs}:fontcolor=white:"
        f"borderw=2:bordercolor=black@0.6:"
        f"x=(w-text_w)/2:y=h*0.07:"
        f"enable='between(t,0.5,5)',"
        # URL — EB Garamond, centered, freeze frame
        f"drawtext=text='news.tanazur.org':"
        f"fontfile={FONT_GARAMOND_BOLD}:"
        f"fontsize=44:fontcolor=white:"
        f"borderw=2:bordercolor=black@0.7:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:"
        f"enable='gte(t,{freeze_start:.1f})'"
        f"[v]"
    )

    if has_theme:
        # Mix voiceover (padded for freeze) with theme (20% vol, 3s fade in/out)
        audio_filter = (
            f"[1:a]apad=pad_dur={FREEZE_SECONDS}[vo];"
            f"[2:a]atrim=0:{video_dur:.1f},"
            f"afade=t=in:st=0:d={FADE_SECONDS},"
            f"afade=t=out:st={video_dur - FADE_SECONDS:.1f}:d={FADE_SECONDS},"
            f"volume={THEME_VOLUME}[bg];"
            f"[vo][bg]amix=inputs=2:duration=first[a]"
        )
        filter_complex = f"{video_filter};{audio_filter}"
    else:
        audio_filter = f"[1:a]apad=pad_dur={FREEZE_SECONDS}[a]"
        filter_complex = f"{video_filter};{audio_filter}"

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),  # 0: video
        "-i", str(audio_path),                                   # 1: voiceover
    ]
    if has_theme:
        cmd += ["-i", str(NEWS_THEME_PATH)]                      # 2: news theme
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
    concat_file.unlink(missing_ok=True)
    title_file.unlink(missing_ok=True)

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
        f"#ICRA #DailyDaemon #Cassiyah #AI #journalism #tanazur #sufi"
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
# Full Reel Pipeline
# ---------------------------------------------------------------------------

def generate_reel(article: dict, filename: str) -> Path | None:
    """Full Reel pipeline: voiceover + 2 Sora clips + assembly. Returns reel path."""
    title = article["title"]
    slug = Path(filename).stem
    reel_dir = REELS_DIR / slug
    reel_dir.mkdir(parents=True, exist_ok=True)

    # Generate a vertical 9:16 seed image for Sora.
    # If original cartoon exists, Gemini recomposes it for vertical.
    # If not, Gemini generates from scratch.
    reel_seed = reel_dir / "reel_seed.png"
    if not reel_seed.exists():
        original = get_image_path(article)
        image_path = generate_vertical_seed(article, filename, original)
        if not image_path:
            log.error(f"Could not generate seed image for: {title[:50]}")
            return None
        import shutil
        shutil.copy2(image_path, reel_seed)
    image_path = reel_seed

    # 1. Generate voiceover script
    log.info(f"=== REEL: {title[:60]} ===")
    script = generate_voiceover_script(article)

    # 2. Generate TTS
    audio_path = reel_dir / "voiceover.mp3"
    if not generate_tts(script, audio_path):
        return None

    # 3. Generate visual prompts
    visual1 = generate_sora_visual_prompt(article, 1)
    visual2 = generate_sora_visual_prompt(article, 2)

    # 4. Generate Sora clip 1 from cartoon
    clip1_path = reel_dir / "clip1.mp4"
    if not generate_sora_clip(visual1, image_path, clip1_path):
        return None

    # 5. Extract last frame from clip 1
    frame_path = reel_dir / "clip1_lastframe.png"
    if not extract_last_frame(clip1_path, frame_path):
        return None

    # 6. Generate Sora clip 2 from last frame of clip 1
    clip2_path = reel_dir / "clip2.mp4"
    if not generate_sora_clip(visual2, frame_path, clip2_path):
        return None

    # 7. Assemble final reel
    reel_path = REELS_DIR / f"reel_{slug}.mp4"
    if not assemble_reel(clip1_path, clip2_path, audio_path, title, reel_path):
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
        else:
            results["instagram_reel"] = {"error": "Reel generation failed"}

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
