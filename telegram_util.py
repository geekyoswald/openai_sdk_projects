"""Telegram notifications and per-run step logging (console + list + Telegram)."""

from __future__ import annotations

import contextvars
import os
import requests

_steps_cv: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar("sdr_steps", default=None)


def bind_steps_list(steps: list[str]) -> contextvars.Token[list[str] | None]:
    """Call at pipeline start; reset with ``steps_reset`` in ``finally``."""
    return _steps_cv.set(steps)


def steps_reset(token: contextvars.Token[list[str] | None]) -> None:
    _steps_cv.reset(token)


def send_telegram_message(text: str) -> None:
    try:
        token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
        chat_raw = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
        if not token or not chat_raw or not (text or "").strip():
            return
        # Telegram accepts int or string chat_id; normalize numeric strings.
        chat_id: int | str
        if chat_raw.lstrip("-").isdigit():
            chat_id = int(chat_raw)
        else:
            chat_id = chat_raw
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        try:
            data = r.json()
            if not data.get("ok"):
                print(
                    f"[telegram] sendMessage failed: {data.get('description', r.text)[:500]}",
                    flush=True,
                )
        except Exception:
            if r.status_code != 200:
                print(f"[telegram] HTTP {r.status_code}: {r.text[:500]}", flush=True)
    except Exception as ex:
        print(f"[telegram] sendMessage error: {ex}", flush=True)


def log_step(step: str) -> None:
    print(step, flush=True)
    buf = _steps_cv.get()
    if buf is not None:
        buf.append(step)
    send_telegram_message(step)
