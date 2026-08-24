r"""Authenticated-session persistence (spec §7).

Rules enforced here:
  * The password is NEVER persisted — only Playwright ``storage_state``.
  * Storage state is treated as a secret: DPAPI-encrypted, written only under
    ``sessions\``, never echoed to logs/reports/UI maps.
  * If DPAPI is unavailable the session is simply not saved (fail closed)
    unless the caller explicitly opts into plaintext.
"""
from __future__ import annotations

import json
from typing import Any

from .. import paths
from ..logging_setup import get
from . import dpapi

log = get("security.session")

_MAGIC_DPAPI = b"P1UIDv1\x00"
_MAGIC_PLAIN = b"P1UIDv1P"  # plaintext fallback, opt-in only


class SessionStore:
    def __init__(self, allow_plaintext: bool = False) -> None:
        self.allow_plaintext = allow_plaintext
        self.path = paths.SESSION_FILE

    # -- public API ---------------------------------------------------------
    def exists(self) -> bool:
        return self.path.is_file()

    def save(self, storage_state: dict[str, Any]) -> bool:
        paths.ensure_dirs()
        raw = json.dumps(storage_state, separators=(",", ":")).encode("utf-8")
        try:
            blob = _MAGIC_DPAPI + dpapi.protect(raw)
            mode = "DPAPI-encrypted"
        except OSError as exc:
            if not self.allow_plaintext:
                log.warning("Session NOT saved: DPAPI unavailable (%s) and plaintext is disabled", exc)
                return False
            blob = _MAGIC_PLAIN + raw
            mode = "PLAINTEXT (insecure, explicitly enabled)"
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(blob)
        tmp.replace(self.path)
        self._restrict_permissions()
        log.info("Authenticated session saved [%s] -> %s", mode, paths.rel(self.path))
        return True

    def load(self) -> dict[str, Any] | None:
        if not self.exists():
            return None
        blob = self.path.read_bytes()
        try:
            if blob.startswith(_MAGIC_DPAPI):
                raw = dpapi.unprotect(blob[len(_MAGIC_DPAPI):])
            elif blob.startswith(_MAGIC_PLAIN):
                raw = blob[len(_MAGIC_PLAIN):]
            else:
                log.warning("Saved session has an unrecognised format; ignoring it")
                return None
            state = json.loads(raw.decode("utf-8"))
        except Exception as exc:  # corrupt / wrong user / wrong machine
            log.warning("Saved session could not be decrypted (%s); it will be ignored", type(exc).__name__)
            return None
        log.info("Reusing saved authenticated session (%d cookies)", len(state.get("cookies", [])))
        return state

    def clear(self) -> bool:
        removed = False
        for p in (self.path, self.path.with_suffix(".tmp")):
            if p.is_file():
                try:
                    p.write_bytes(b"\x00" * max(1, p.stat().st_size))  # best-effort overwrite
                except OSError:
                    pass
                p.unlink(missing_ok=True)
                removed = True
        log.info("Saved session cleared" if removed else "No saved session to clear")
        return removed

    # -- internals ----------------------------------------------------------
    def _restrict_permissions(self) -> None:
        """Best-effort: strip inherited ACEs, grant only the current user."""
        import subprocess
        import sys

        if sys.platform != "win32":
            return
        try:
            subprocess.run(["icacls", str(self.path), "/inheritance:r",
                            "/grant:r", "%USERNAME%:(F)"],
                           check=False, capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            pass
