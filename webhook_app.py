"""FastAPI entry for Telegram webhook → ``run_sdr_pipeline``."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request

# Always load .env next to this file (uvicorn cwd is often not the project dir).
load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

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
        from telegram_util import send_telegram_message

        async with _pipeline_lock:
            if uid is not None and uid in _processed_update_ids:
                return {"ok": True}
            try:
                await run_sdr_pipeline(text)
            except Exception as ex:
                # Return 200 + mark update so Telegram does not retry forever (e.g. after HTTP 500).
                print(f"[webhook] pipeline error: {ex}", flush=True)
                send_telegram_message(f"❌ Pipeline error: {ex!s}"[:3800])
            if uid is not None:
                _processed_update_ids.add(uid)
                if len(_processed_update_ids) > _MAX_SEEN_UPDATE_IDS:
                    _processed_update_ids.clear()

    return {"ok": True}
