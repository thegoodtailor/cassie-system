"""Batch generate + post reels for all articles that don't have one yet.
Each reel is posted to Instagram immediately after generation."""

import sys
sys.path.insert(0, "/home/iman/cassie-project/cassie-system")

import json
import logging
import time
from pathlib import Path

import social_post as sp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("batch")

voice_dir = Path("/home/iman/cassie-project/cassie-system/data/daily_voice")
files = sorted(voice_dir.glob("2026-*.json"))

generated = 0
posted = 0
failed = 0
skipped = 0

for f in files:
    slug = f.stem
    reel_path = sp.REELS_DIR / f"reel_{slug}.mp4"

    with open(f) as fh:
        article = json.load(fh)

    # Skip if reel already exists (already posted in earlier runs)
    if reel_path.exists():
        log.info(f"SKIP (exists): {slug} — {article['title'][:50]}")
        skipped += 1
        continue

    log.info(f"\n{'='*60}")
    log.info(f"GENERATING: {slug} — {article['title'][:60]}")
    log.info(f"{'='*60}")

    try:
        result = sp.generate_reel(article, f.name)
        if result:
            log.info(f"REEL READY: {result.name} ({result.stat().st_size / 1024 / 1024:.1f}MB)")
            generated += 1

            # Save updated article JSON (in case seed image was generated)
            with open(f, "w") as fh:
                json.dump(article, fh, indent=2, ensure_ascii=False)

            # Post to Instagram immediately
            log.info(f"POSTING to Instagram...")
            ig_result = sp.post_reel_to_instagram(article, f.name, result)
            if ig_result and "id" in ig_result:
                log.info(f"POSTED: {ig_result['id']}")
                posted += 1
            else:
                log.error(f"POST FAILED: {ig_result}")

            # Also post feed to Facebook
            log.info(f"POSTING to Facebook...")
            fb_result = sp.post_to_facebook(article, f.name)

        else:
            log.error(f"REEL GENERATION FAILED: {slug}")
            failed += 1
    except Exception as e:
        log.error(f"EXCEPTION: {slug} — {e}")
        import traceback
        traceback.print_exc()
        failed += 1

    # Brief pause between articles
    time.sleep(3)

log.info(f"\n{'='*60}")
log.info(f"DONE: {generated} generated, {posted} posted, {failed} failed, {skipped} skipped")
log.info(f"{'='*60}")
