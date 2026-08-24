"""Logging with mandatory secret redaction (spec §22).

Secrets are never handed to the logger in the first place; this filter is the
second line of defence. Any string registered with `register_secret()` is
replaced with ``***REDACTED***`` in every record, and a set of key=value
patterns for cookies/tokens/authorization headers is scrubbed unconditionally.
"""
from __future__ import annotations

import logging
import re
import threading
from logging.handlers import RotatingFileHandler
from typing import Callable

from . import paths

_SECRETS: set[str] = set()
_SECRETS_LOCK = threading.Lock()
REDACTED = "***REDACTED***"

# Unconditional scrubbing of secret-looking key/value pairs.
_PATTERNS = [
    re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(authorization|cookie|set-cookie|x-auth-token)\b\s*[:=]\s*[^\n]+"),
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{8,}"),
]


def register_secret(value: str | None) -> None:
    """Mark a literal value as never-loggable (e.g. the in-memory password)."""
    if value and len(value) >= 3:
        with _SECRETS_LOCK:
            _SECRETS.add(value)


def forget_secrets() -> None:
    with _SECRETS_LOCK:
        _SECRETS.clear()


def scrub(text: str) -> str:
    if not text:
        return text
    with _SECRETS_LOCK:
        secrets = tuple(_SECRETS)
    for s in secrets:
        if s in text:
            text = text.replace(s, REDACTED)
    for pat in _PATTERNS:
        text = pat.sub(lambda m: f"{m.group(1)}={REDACTED}", text)
    return text


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        cleaned = scrub(msg)
        if cleaned != msg:
            record.msg = cleaned
            record.args = ()
        return True


class CallbackHandler(logging.Handler):
    """Streams already-redacted lines to the GUI activity log."""

    def __init__(self, callback: Callable[[str, str], None]) -> None:
        super().__init__()
        self._callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._callback(record.levelname, self.format(record))
        except Exception:
            pass


_configured = False


def setup(debug: bool = False, gui_callback: Callable[[str, str], None] | None = None) -> logging.Logger:
    global _configured
    root = logging.getLogger("p1uid")
    if not _configured:
        paths.ensure_dirs()
        root.setLevel(logging.DEBUG if debug else logging.INFO)
        root.propagate = False
        red = RedactionFilter()

        fh = RotatingFileHandler(
            paths.LOGS_DIR / "discovery.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        fh.addFilter(red)
        root.addHandler(fh)

        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
        sh.addFilter(red)
        root.addHandler(sh)
        _configured = True

    root.setLevel(logging.DEBUG if debug else logging.INFO)
    if gui_callback is not None:
        gh = CallbackHandler(gui_callback)
        gh.setFormatter(logging.Formatter("%(message)s"))
        gh.addFilter(RedactionFilter())
        root.addHandler(gh)
    return root


def get(name: str) -> logging.Logger:
    return logging.getLogger(f"p1uid.{name}")
