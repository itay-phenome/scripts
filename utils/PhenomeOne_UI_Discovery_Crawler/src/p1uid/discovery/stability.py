"""Page-settling detection for autonomous discovery.

`wait_stable()` answers "has the UI finished reacting?" using the same
structural signature the trainer already relies on.

Explicitly NOT used:

* fixed sleeps - they are either too short (flaky) or too slow (wasteful);
* `networkidle` - a SaaS SPA with polling, telemetry, or an open socket may
  never reach network idle, and a page can be visually settled long before its
  background requests finish.

Instead the browser watches its own mutations and resolves as soon as there
have been no mutations, and no signature change, for a quiet window.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..logging_setup import get
from . import scanner

log = get("discovery.stability")

WAIT_STABLE_JS = "(o) => window.__p1uidCore.waitStable(o)"

DEFAULT_QUIET_MS = 250
DEFAULT_TIMEOUT_MS = 5000


@dataclass
class Stability:
    stable: bool
    reason: str            # quiet | timeout | navigated | unavailable
    ms: int = 0
    changes: int = 0
    ready_state: str = ""
    signature: str = ""

    def __bool__(self) -> bool:
        return self.stable


async def wait_stable(page: Any, quiet_ms: int = DEFAULT_QUIET_MS,
                      timeout_ms: int = DEFAULT_TIMEOUT_MS,
                      frame: Any = None) -> Stability:
    """Wait until the page stops changing structurally.

    `stable=False` with reason `timeout` means the page was still churning when
    the budget ran out - a crawler should treat that as "do not trust this
    snapshot" rather than retrying blindly.
    """
    target = frame or page.main_frame
    t0 = time.perf_counter()
    opts = {"quietMs": quiet_ms, "timeoutMs": timeout_ms}

    for attempt in (1, 2):
        try:
            if not await scanner.ensure_core(target):
                return Stability(False, "unavailable")
            res = await target.evaluate(WAIT_STABLE_JS, opts)
            return Stability(stable=bool(res.get("stable")), reason=str(res.get("reason", "")),
                             ms=int(res.get("ms", 0)), changes=int(res.get("changes", 0)),
                             ready_state=str(res.get("readyState", "")),
                             signature=str(res.get("signature", "")))
        except Exception as exc:
            # A navigation destroys the execution context mid-wait. That is
            # itself a settling event: wait for the new document, then retry once.
            if attempt == 1:
                log.debug("waitStable interrupted (%s); the page navigated - retrying once",
                          type(exc).__name__)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
                except Exception:
                    pass
                target = frame or page.main_frame
                continue
            log.debug("waitStable failed twice: %s", exc)
            return Stability(False, "navigated", ms=int((time.perf_counter() - t0) * 1000))
    return Stability(False, "unavailable")


async def signature(page: Any, frame: Any = None) -> str:
    """Current structural signature - cheap, for change detection."""
    target = frame or page.main_frame
    try:
        if not await scanner.ensure_core(target):
            return ""
        return str(await target.evaluate("() => window.__p1uidCore.signature()"))
    except Exception:
        return ""
