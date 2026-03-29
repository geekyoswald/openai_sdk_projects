"""FastAPI entry for Telegram webhook → ``run_sdr_pipeline``."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request

# Always load .env next to this file (uvicorn cwd is often not the project dir).
load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

log = logging.getLogger("complai_sdr.webhook")

# Drop backlog so restarts don't replay every queued Telegram update at once.
_MAX_SEEN_UPDATE_IDS = 8192
_processed_update_ids: set[int] = set()


def _drop_pending_telegram_updates() -> None:
    """Tell Telegram to clear pending updates (requires public webhook URL in env)."""
    import requests

    from telegram_util import (
        normalize_env_value,
        normalize_telegram_webhook_url,
        redact_telegram_url_for_log,
    )

    raw_url = os.environ.get("TELEGRAM_WEBHOOK_URL") or ""
    hook_url, url_note = normalize_telegram_webhook_url(raw_url)
    if url_note:
        log.warning("%s", url_note)

    token = normalize_env_value(os.environ.get("TELEGRAM_BOT_TOKEN"))
    if not token:
        log.info(
            "setWebhook skipped: TELEGRAM_BOT_TOKEN missing (Telegram outbound/inbound optional)."
        )
        return
    if not hook_url:
        log.info(
            "setWebhook skipped: no valid TELEGRAM_WEBHOOK_URL "
            "(set to your public https://host/telegramwebhook, not the api.telegram.org link)."
        )
        return

    api = f"https://api.telegram.org/bot{token}/setWebhook"
    try:
        r = requests.get(
            api,
            params={"url": hook_url, "drop_pending_updates": True},
            timeout=20,
        )
    except requests.RequestException as ex:
        log.error(
            "setWebhook request failed: %s (target_url=%s)",
            ex,
            redact_telegram_url_for_log(hook_url),
        )
        return

    try:
        data = r.json()
    except Exception as ex:
        log.error(
            "setWebhook: bad response JSON (HTTP %s): %s body=%s",
            r.status_code,
            ex,
            (r.text or "")[:500],
        )
        return

    if data.get("ok"):
        log.info(
            "setWebhook ok url=%s drop_pending_updates=true (HTTP %s)",
            redact_telegram_url_for_log(hook_url),
            r.status_code,
        )
        return

    log.error(
        "setWebhook failed error_code=%s description=%s (HTTP %s) url_param=%s — "
        "check HTTPS certificate, public URL, and that the path matches POST /telegramwebhook",
        data.get("error_code"),
        (data.get("description") or r.text or "")[:500],
        r.status_code,
        redact_telegram_url_for_log(hook_url),
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from telegram_util import configure_complai_logging

    configure_complai_logging()
    log.info("Application starting (env loaded from %s)", Path(__file__).resolve().parent / ".env")
    await asyncio.to_thread(_drop_pending_telegram_updates)
    yield


app = FastAPI(title="ComplAI SDR Telegram demo", lifespan=lifespan)

# One pipeline at a time so Telegram retries / parallel POSTs don't interleave logs and LLM work.
_pipeline_lock = asyncio.Lock()


@app.post("/telegramwebhook")
async def telegram_webhook(req: Request) -> dict[str, bool]:
    try:
        body: dict = await req.json()
    except Exception as ex:
        log.warning("webhook: invalid or missing JSON body: %s", ex)
        return {"ok": True}

    raw_uid = body.get("update_id")
    uid: int | None = raw_uid if isinstance(raw_uid, int) else None
    if uid is not None and uid in _processed_update_ids:
        log.debug("webhook: duplicate update_id=%s ignored", uid)
        return {"ok": True}

    msg = body.get("message") or body.get("edited_message") or {}
    text = ""
    if isinstance(msg, dict):
        text = (msg.get("text") or "").strip()

    if not text:
        keys = [k for k in ("message", "edited_message", "callback_query") if body.get(k)]
        if keys:
            log.info(
                "webhook update_id=%s: no text (keys present: %s) — only plain text messages run the pipeline",
                uid,
                keys,
            )
        else:
            log.debug("webhook update_id=%s: empty update (no message text)", uid)
        return {"ok": True}

    from pipeline import run_sdr_pipeline
    from telegram_util import send_telegram_message

    log.info("webhook update_id=%s: running pipeline (text length=%s)", uid, len(text))
    async with _pipeline_lock:
        if uid is not None and uid in _processed_update_ids:
            log.debug("webhook: duplicate update_id=%s inside lock", uid)
            return {"ok": True}
        try:
            await run_sdr_pipeline(text)
        except Exception as ex:
            log.exception("webhook update_id=%s: pipeline failed", uid)
            send_telegram_message(f"❌ Pipeline error: {ex!s}"[:3800])
        if uid is not None:
            _processed_update_ids.add(uid)
            if len(_processed_update_ids) > _MAX_SEEN_UPDATE_IDS:
                _processed_update_ids.clear()

    return {"ok": True}
