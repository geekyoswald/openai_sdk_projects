"""FastAPI entry for Telegram webhook → ``run_sdr_pipeline``."""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI, Request

load_dotenv(override=True)

app = FastAPI(title="ComplAI SDR Telegram demo")


@app.post("/telegram-webhook")
async def telegram_webhook(req: Request) -> dict[str, bool]:
    try:
        body: dict = await req.json()
    except Exception:
        return {"ok": True}
    msg = body.get("message") or body.get("edited_message") or {}
    text = ""
    if isinstance(msg, dict):
        text = (msg.get("text") or "").strip()

    if text:
        from pipeline import run_sdr_pipeline

        await run_sdr_pipeline(text)

    return {"ok": True}
