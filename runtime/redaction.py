"""Redact credentials from text before it reaches a log, a DB row or a console.

The bot handles a Telegram bot token and a Vietcap authorization/cookie/device
ID. None of them may appear in logs, persisted ``error_reason`` values, script
output or chat replies. Redaction here is defence in depth: adapters already
avoid stringifying headers, but exception text from third-party libraries
(``requests``, ``httpx``, ``python-telegram-bot``) can embed a request URL such
as ``https://api.telegram.org/bot<TOKEN>/getMe``.

Two mechanisms are combined:

* exact-value masking of the secrets actually present in the environment;
* pattern masking for shapes that are always sensitive (bot tokens, bearer
  tokens, ``Authorization``/``Cookie`` header lines).
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
import os
import re

REDACTED = "<redacted>"

#: Environment variables whose values are credentials.
SECRET_ENV_NAMES = (
    "TELEGRAM_BOT_TOKEN",
    "VIETCAP_AUTHORIZATION",
    "VIETCAP_COOKIE",
    "VIETCAP_DEVICE_ID",
)

#: Values shorter than this are never used for exact masking; masking a 3
#: character value would corrupt unrelated text.
_MIN_SECRET_LENGTH = 8

_TELEGRAM_TOKEN = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")
_BOT_URL = re.compile(r"(/bot)\d+:[^/\s\"'?]+")
_BEARER = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{8,}")
_HEADER_LINE = re.compile(
    r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie|x-api-key|device-id)"
    r"(\s*[:=]\s*)[^\r\n,;}]+"
)


def _secret_values(environ: Mapping[str, str] | None) -> tuple[str, ...]:
    source = os.environ if environ is None else environ
    values = []
    for name in SECRET_ENV_NAMES:
        value = (source.get(name) or "").strip()
        if len(value) >= _MIN_SECRET_LENGTH:
            values.append(value)
    # Longest first so a value containing another is masked whole.
    return tuple(sorted(set(values), key=len, reverse=True))


def redact_secrets(text: object, *, environ: Mapping[str, str] | None = None) -> str:
    """Return ``text`` (stringified) with credentials replaced by ``<redacted>``."""
    result = text if isinstance(text, str) else str(text)
    for value in _secret_values(environ):
        result = result.replace(value, REDACTED)
    result = _TELEGRAM_TOKEN.sub(REDACTED, result)
    result = _BOT_URL.sub(r"\1" + REDACTED, result)
    result = _BEARER.sub(r"\1 " + REDACTED, result)
    result = _HEADER_LINE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", result)
    return result


def safe_reason(text: object, *, limit: int = 300, environ: Mapping[str, str] | None = None) -> str:
    """Redacted, single-line, length-bounded text safe to persist as a reason."""
    cleaned = " ".join(redact_secrets(text, environ=environ).split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


class SecretRedactingFilter(logging.Filter):
    """Mask credentials in every record that passes through a handler/logger."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # a malformed record must never break logging
            return True
        redacted = redact_secrets(message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        if record.exc_info and record.exc_info[1] is not None:
            # Exception text is rendered later by the formatter; pre-render it
            # redacted so a traceback cannot carry a token URL.
            record.exc_text = redact_secrets(
                logging.Formatter().formatException(record.exc_info)
            )
        return True


def configure_logging(level: str | None = None) -> None:
    """Root logging with redaction on every handler and quiet HTTP clients.

    ``httpx`` logs each request URL at INFO, and Telegram request URLs contain
    the bot token, so its loggers are pinned to WARNING regardless of
    ``LOG_LEVEL``.
    """
    resolved = (level or os.getenv("LOG_LEVEL", "INFO")).strip().upper()
    numeric = getattr(logging, resolved, logging.INFO)
    if not isinstance(numeric, int):
        numeric = logging.INFO
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    redactor = SecretRedactingFilter()
    for handler in logging.getLogger().handlers:
        if not any(isinstance(item, SecretRedactingFilter) for item in handler.filters):
            handler.addFilter(redactor)
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
