"""Telegram notifications and per-run step logging (console + list + Telegram)."""

from __future__ import annotations

import contextvars
import logging
import os
import re
import requests
from urllib.parse import parse_qs, unquote, urlparse

_steps_cv: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar("sdr_steps", default=None)

log = logging.getLogger("complai_sdr.telegram")


def configure_complai_logging() -> None:
    """Attach a handler so ``complai_sdr.*`` loggers emit to stderr (webhook or CLI)."""
    level_name = (os.environ.get("LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    complai = logging.getLogger("complai_sdr")
    if complai.handlers:
        complai.setLevel(level)
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    complai.addHandler(handler)
    complai.setLevel(level)
    complai.propagate = False


def bind_steps_list(steps: list[str]) -> contextvars.Token[list[str] | None]:
    """Call at pipeline start; reset with ``steps_reset`` in ``finally``."""
    return _steps_cv.set(steps)


def steps_reset(token: contextvars.Token[list[str] | None]) -> None:
    _steps_cv.reset(token)


def normalize_env_value(value: str | None) -> str:
    """Strip whitespace and outer quotes (common mistake in ``.env``)."""
    s = (value or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        s = s[1:-1].strip()
    return s


def _parse_telegram_chat_id(chat_raw: str) -> int | str:
    """Telegram accepts int or string; prefer int for numeric IDs (incl. supergroups ``-100…``)."""
    if chat_raw.lstrip("-").isdigit():
        return int(chat_raw)
    return chat_raw


def redact_telegram_url_for_log(url: str) -> str:
    """Mask bot token in paths like ``/bot123:AA…`` so logs are safe to share."""
    if not url:
        return url
    return re.sub(r"(/bot)(\d+):[^/?#&\s]+", r"\1\2:***", str(url))


def _extract_public_url_from_setwebhook_paste(s: str) -> str | None:
    """
    Parse ``url=`` out of a pasted browser/curl line like
    ``https://api.telegram.org/bot…/setWebhook?url=https%3A%2F%2Fhost%2Fpath``.
    Uses ``parse_qs`` first, then a regex fallback (some .env line wraps break urlparse).
    """
    low = s.lower()
    if "api.telegram.org" not in s or "setwebhook" not in low:
        return None
    parsed = urlparse(s)
    qd = parse_qs(parsed.query)
    inner: str | None = None
    for key, vals in qd.items():
        if key.lower() == "url" and vals:
            inner = vals[0]
            break
    if inner:
        return unquote(inner).strip()
    m = re.search(r"(?i)[?&]url=([^&]+)", s)
    if m:
        return unquote(m.group(1).strip()).strip()
    return None


def normalize_telegram_webhook_url(raw: str) -> tuple[str | None, str | None]:
    """
    Return ``(url_for_setWebhook, remediation_note)``.

    ``remediation_note`` is set when the value was missing, invalid, or a common
    mistake (pasting the full ``api.telegram.org/.../setWebhook?url=`` string).
    """
    s = normalize_env_value(raw)
    if not s:
        return None, "TELEGRAM_WEBHOOK_URL is empty; webhook will not be registered on startup."

    note: str | None = None
    extracted = _extract_public_url_from_setwebhook_paste(s)
    if extracted:
        s = extracted
        note = (
            "TELEGRAM_WEBHOOK_URL was a full setWebhook API URL; using the embedded url= value. "
            "Prefer setting TELEGRAM_WEBHOOK_URL to only your public endpoint "
            "(e.g. https://your.domain/telegramwebhook)."
        )

    if "api.telegram.org" in s:
        return None, (
            "TELEGRAM_WEBHOOK_URL still points at api.telegram.org after normalization; "
            "set it to only your HTTPS public URL, e.g. https://your.domain/telegramwebhook"
        )

    if not s.startswith(("https://", "http://")):
        return (
            None,
            f"TELEGRAM_WEBHOOK_URL must be an absolute URL starting with https:// (received {s[:96]!r}).",
        )

    if s.startswith("http://") and "localhost" not in s and "127.0.0.1" not in s:
        log.warning(
            "TELEGRAM_WEBHOOK_URL uses http://; Telegram production webhooks require https:// "
            "(unless using a local tunnel)."
        )

    return s, note


def send_telegram_message(text: str) -> None:
    """Post a message to TELEGRAM_CHAT_ID; logs precise skip/failure reasons."""
    try:
        token = normalize_env_value(os.environ.get("TELEGRAM_BOT_TOKEN"))
        chat_raw = normalize_env_value(os.environ.get("TELEGRAM_CHAT_ID"))
        if not (text or "").strip():
            log.debug("send_telegram_message skipped: empty text")
            return
        if not token:
            log.warning(
                "sendMessage skipped: TELEGRAM_BOT_TOKEN is missing or empty after trim "
                "(check .env next to webhook_app.py and restart)."
            )
            return
        if not chat_raw:
            log.warning(
                "sendMessage skipped: TELEGRAM_CHAT_ID is missing or empty "
                "(use numeric message.chat.id from an update to this bot)."
            )
            return
        chat_id = _parse_telegram_chat_id(chat_raw)
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        try:
            data = r.json()
        except Exception as ex:
            log.error(
                "sendMessage: could not parse JSON response (HTTP %s): %s — body=%s",
                r.status_code,
                ex,
                (r.text or "")[:500],
            )
            return

        if data.get("ok"):
            log.debug("sendMessage ok chat_id=%s", chat_id)
            return

        desc = (data.get("description") or r.text or "")[:500]
        err_code = data.get("error_code")
        hints: list[str] = []
        low = desc.lower()
        if "chat not found" in low:
            hints.append(
                "TELEGRAM_CHAT_ID must be the chat where this bot can write: same bot token, user sent /start, "
                "id is message.chat.id (private: often 10 digits). Typos (e.g. missing digit) cause this error."
            )
            if isinstance(chat_id, int) and chat_id > 0:
                sd = str(chat_id)
                if len(sd) < 10:
                    hints.append(
                        f"This chat_id has {len(sd)} digits; many Telegram user ids are 10 digits—compare with "
                        "message.chat.id from an update to this bot."
                    )
        if "unauthorized" in low or err_code == 401:
            hints.append("TELEGRAM_BOT_TOKEN is invalid or revoked; get a new token from @BotFather.")
        if "bot was blocked" in low:
            hints.append("User blocked the bot; unblock or use another chat id.")
        if "flood" in low:
            hints.append("Rate limited; wait and retry.")
        hint_txt = (" " + " ".join(hints)) if hints else ""
        log.error(
            "sendMessage failed error_code=%s description=%s chat_id=%s%s",
            err_code,
            desc,
            chat_id,
            hint_txt,
        )
    except requests.RequestException as ex:
        log.error("sendMessage network error: %s", ex)
    except Exception as ex:
        log.exception("sendMessage unexpected error: %s", ex)


def log_step(step: str) -> None:
    log.info("%s", step)
    print(step, flush=True)
    buf = _steps_cv.get()
    if buf is not None:
        buf.append(step)
    send_telegram_message(step)
