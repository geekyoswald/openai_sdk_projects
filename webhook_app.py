"""FastAPI entry for Telegram webhook → ``run_sdr_pipeline``."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request

load_dotenv(override=True)

# Drop backlog so restarts don't replay every queued Telegram update at once.
_MAX_SEEN_UPDATE_IDS = 8192
_processed_update_ids: set[int] = set()


def _drop_pending_telegram_updates() -> None:
    """Tell Telegram to clear pending updates (requires public webhook URL in env)."""
    import requests

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    url = (os.environ.get("TELEGRAM_WEBHOOK_URL") or "").strip()
    if not token or not url:
        return
    try:
        requests.get(
            f"https://api.telegram.org/bot{token}/setWebhook",
            params={"url": url, "drop_pending_updates": True},
            timeout=20,
        )
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(_drop_pending_telegram_updates)
    yield


app = FastAPI(title="ComplAI SDR Telegram demo", lifespan=lifespan)

# One pipeline at a time so Telegram retries / parallel POSTs don't interleave logs and LLM work.
_pipeline_lock = asyncio.Lock()


@app.post("/telegramwebhook")
async def telegram_webhook(req: Request) -> dict[str, bool]:
    try:
        body: dict = await req.json()
    except Exception:
        return {"ok": True}

    raw_uid = body.get("update_id")
    uid: int | None = raw_uid if isinstance(raw_uid, int) else None
    if uid is not None and uid in _processed_update_ids:
        return {"ok": True}

    msg = body.get("message") or body.get("edited_message") or {}
    text = ""
    if isinstance(msg, dict):
        text = (msg.get("text") or "").strip()

    if text:
        from pipeline import run_sdr_pipeline

        async with _pipeline_lock:
            if uid is not None and uid in _processed_update_ids:
                return {"ok": True}
            if uid is not None:
                _processed_update_ids.add(uid)
                if len(_processed_update_ids) > _MAX_SEEN_UPDATE_IDS:
                    _processed_update_ids.clear()
            await run_sdr_pipeline(text)

    return {"ok": True}
