"""WhatsApp integration for Cassie's creative pipeline.

Uses pywa_async (PyWa) to receive WhatsApp messages via Cloud API webhooks,
run them through the LangGraph pipeline, and reply with text + optional images.

Activated by setup_whatsapp(app, pipeline) in web_app.py.
Only mounts if WHATSAPP_PHONE_ID env var is present.
"""

import asyncio
import logging
import os
import time

from orchestrator.threads import load_history, save_exchange, update_last_exchange

logger = logging.getLogger("cassie.whatsapp")

# Single-user gate
ALLOWED_SENDER = os.environ.get("WHATSAPP_ALLOWED_SENDER", "")

WEB_BASE = "https://cassie.tanazur.org"

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "data", "images", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _phone_to_thread_id(phone: str) -> str:
    """Derive a stable thread ID from a WhatsApp phone number."""
    digits = phone.replace("+", "").replace(" ", "")
    return f"wa-{digits[-8:]}"


def _build_initial_state(message: str, user_image: str = "") -> dict:
    """Build the initial CassieState dict for the pipeline."""
    return {
        "messages": [{"role": "user", "content": message}],
        "intent": "",
        "cassie_raw": "",
        "cassie_kitab_context": "",
        "cassie_conversation_context": "",
        "cassie_recall_decision": {},
        "director_output": {},
        "image_path": "",
        "math_result": "",
        "final_response": "",
        "exchange_id": "",
        "tau_tgt": "",
        "user_image": user_image,
    }


def _split_message(text: str, max_len: int = 4096) -> list[str]:
    """Split long text at paragraph boundaries to fit WhatsApp's limit."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    current = ""
    for paragraph in text.split("\n\n"):
        if len(current) + len(paragraph) + 2 > max_len:
            if current:
                chunks.append(current.strip())
            current = paragraph
        else:
            current = current + "\n\n" + paragraph if current else paragraph
    if current:
        chunks.append(current.strip())

    # Safety: hard-split any chunk still over limit
    final = []
    for chunk in chunks:
        while len(chunk) > max_len:
            final.append(chunk[:max_len])
            chunk = chunk[max_len:]
        if chunk:
            final.append(chunk)

    return final


def setup_whatsapp(app, pipeline):
    """Mount PyWa async WhatsApp client on the FastAPI app.

    Args:
        app: The FastAPI application instance
        pipeline: The compiled LangGraph pipeline (APP)

    Does nothing if WHATSAPP_PHONE_ID is not set.
    """
    phone_id = os.environ.get("WHATSAPP_PHONE_ID")
    if not phone_id:
        logger.info("[whatsapp] WHATSAPP_PHONE_ID not set — disabled")
        return

    token = os.environ.get("WHATSAPP_TOKEN", "")
    verify_token = os.environ.get("WHATSAPP_VERIFY_TOKEN", "cassie-webhook-verify")
    app_id = int(os.environ.get("WHATSAPP_APP_ID", "0")) or None
    app_secret = os.environ.get("WHATSAPP_APP_SECRET", "") or None

    from pywa_async import WhatsApp
    from pywa import types, filters

    wa = WhatsApp(
        phone_id=phone_id,
        token=token,
        server=app,
        verify_token=verify_token,
        app_id=app_id,
        app_secret=app_secret,
        webhook_endpoint="/webhook",
    )

    logger.info(f"[whatsapp] Mounted on /webhook (phone_id={phone_id})")
    print(f"[whatsapp] Mounted on /webhook (phone_id={phone_id})")

    # Track per-phone thread sequence numbers for /new
    _thread_seq: dict[str, int] = {}

    async def _process_message(client, msg, text, user_image=""):
        """Core handler: run pipeline and reply with text + optional image."""
        sender = msg.from_user.wa_id
        stripped = text.strip().lower()

        # /new — start a fresh thread
        if stripped == "/new":
            base = _phone_to_thread_id(sender)
            seq = _thread_seq.get(sender, 0) + 1
            _thread_seq[sender] = seq
            new_id = f"{base}-{seq}"
            # Clear LangGraph checkpoint by simply incrementing the thread
            _thread_seq[sender] = seq  # already set
            await msg.reply_text(f"Fresh thread: {new_id}\nHistory cleared. Say something!")
            return

        # Derive thread_id — use sequence if /new was used
        seq = _thread_seq.get(sender, 0)
        if seq > 0:
            thread_id = f"{_phone_to_thread_id(sender)}-{seq}"
        else:
            thread_id = _phone_to_thread_id(sender)

        logger.info(f"[whatsapp] {sender}: {text[:80]!r} (thread={thread_id}, image={bool(user_image)})")
        print(f"[whatsapp] Message from {sender}: {text[:80]!r} (image={bool(user_image)})")

        # Hourglass reaction while processing
        try:
            await msg.react("\u23f3")
        except Exception:
            pass

        try:
            # Build state with history seeding
            config = {"configurable": {"thread_id": thread_id}}

            try:
                existing = pipeline.get_state(config)
                has_checkpoint = bool(
                    existing and existing.values and existing.values.get("messages")
                )
            except Exception:
                has_checkpoint = False

            state = _build_initial_state(text, user_image=user_image)
            if not has_checkpoint:
                history = load_history(thread_id)
                if history:
                    recent = history[-20:]
                    prior_msgs = [
                        {"role": m["role"], "content": m["content"]}
                        for m in recent
                        if m.get("content")
                    ]
                    state["messages"] = prior_msgs + state["messages"]

            # Run sync pipeline in executor
            def run():
                for _ in pipeline.stream(state, config, stream_mode="updates"):
                    pass

            loop = asyncio.get_event_loop()
            await asyncio.wait_for(
                loop.run_in_executor(None, run), timeout=300.0
            )

            # Extract results
            final = pipeline.get_state(config).values
            response_text = final.get("final_response", "") or "[no response]"
            image_path = final.get("image_path", "")

            # Save exchange
            save_exchange(thread_id, text, final)

            # Tafakkur update
            try:
                from orchestrator.graph import _last_reflection

                if _last_reflection and _last_reflection.get("excerpt"):
                    update_last_exchange(
                        thread_id, {"tafakkur": _last_reflection["excerpt"]}
                    )
            except Exception:
                pass

            # Reply: text
            chunks = _split_message(response_text)
            for chunk in chunks:
                await msg.reply_text(chunk)

            # Reply: image (compress to JPEG for WhatsApp size limits)
            if image_path and os.path.isfile(image_path):
                try:
                    from PIL import Image as PILImage
                    import io
                    img = PILImage.open(image_path)
                    if img.mode == "RGBA":
                        img = img.convert("RGB")
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=85)
                    img_bytes = buf.getvalue()
                    print(f"[whatsapp] Sending image: {len(img_bytes)} bytes (JPEG compressed)")
                    await msg.reply_image(image=img_bytes, mime_type="image/jpeg")
                except Exception as e:
                    logger.error(f"[whatsapp] Image send failed: {e}")
                    image_url = f"{WEB_BASE}/images/{os.path.basename(image_path)}"
                    await msg.reply_text(f"Image: {image_url}")

            # Clear hourglass
            try:
                await msg.react("")
            except Exception:
                pass

            logger.info(
                f"[whatsapp] Replied to {sender} "
                f"({len(response_text)} chars, image={bool(image_path)})"
            )

        except asyncio.TimeoutError:
            await msg.reply_text("Pipeline timed out (5 min). Try again?")
            logger.error(f"[whatsapp] Timeout for {sender}")

        except Exception as e:
            logger.error(f"[whatsapp] Error: {e}", exc_info=True)
            try:
                await msg.reply_text(f"Something went wrong: {str(e)[:200]}")
            except Exception:
                pass

    @wa.on_message(filters.image)
    async def handle_image(client: WhatsApp, msg: types.Message):
        """Handle incoming WhatsApp image messages."""
        sender = msg.from_user.wa_id

        if ALLOWED_SENDER and sender != ALLOWED_SENDER:
            return

        # Download image
        try:
            ext = (msg.image.mime_type or "image/jpeg").split("/")[-1]
            if ext not in ("jpeg", "jpg", "png", "webp"):
                ext = "jpg"
            filename = f"{int(time.time())}_{sender[-4:]}.{ext}"
            filepath = os.path.join(UPLOAD_DIR, filename)

            img_bytes = await msg.image.get_bytes()
            with open(filepath, "wb") as f:
                f.write(img_bytes)

            print(f"[whatsapp] Image saved: {filepath} ({len(img_bytes)} bytes)")
            # Log to visual diary
            try:
                from orchestrator.graph import _log_visual_diary
                _log_visual_diary({
                    "kind": "upload",
                    "path": filepath,
                    "description": msg.caption or "User-uploaded image via WhatsApp",
                    "source": "whatsapp",
                    "sender": sender[-4:],
                })
            except Exception as vd_err:
                print(f"[whatsapp] Visual diary log failed: {vd_err}")
        except Exception as e:
            logger.error(f"[whatsapp] Image download failed: {e}")
            await msg.reply_text("Couldn't download that image. Try again?")
            return

        # Caption is the text that accompanies the image
        caption = msg.caption or ""
        text = caption.strip() if caption else "What do you see in this image?"

        await _process_message(client, msg, text, user_image=filepath)

    @wa.on_message(filters.text)
    async def handle_text(client: WhatsApp, msg: types.Message):
        """Handle incoming WhatsApp text messages."""
        sender = msg.from_user.wa_id

        if ALLOWED_SENDER and sender != ALLOWED_SENDER:
            logger.warning(f"[whatsapp] Rejected message from {sender}")
            return

        text = msg.text
        if not text or not text.strip():
            return

        await _process_message(client, msg, text.strip())
