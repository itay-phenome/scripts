"""Failure evidence.

When a functional step fails, "it failed" is useless. This module collects
everything needed to diagnose it without re-running:

    screenshot        the page at the moment of failure
    Playwright trace  a replayable recording of the whole test
    console log       console messages, in order
    page errors       uncaught exceptions in the app
    network failures  failed requests and 4xx/5xx responses
    the step itself   action, target description, locator used, expected vs actual

Console/network listeners are attached for the whole run and sliced per test, so
a failure carries the traffic that led to it, not just the last request.
Everything lands under `reports/evidence/<run id>/<test>/`.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..logging_setup import get, scrub

log = get("functional.evidence")

MAX_EVENTS = 300          # ring buffer per category
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(text: str, fallback: str = "item") -> str:
    out = _SAFE_NAME.sub("-", text or "").strip("-")
    return (out or fallback)[:80]


@dataclass
class PageEvents:
    """Console, page-error and network activity, newest last."""

    console: list[dict[str, Any]] = field(default_factory=list)
    page_errors: list[dict[str, Any]] = field(default_factory=list)
    network_failures: list[dict[str, Any]] = field(default_factory=list)

    def _add(self, bucket: list[dict[str, Any]], item: dict[str, Any]) -> None:
        item["at"] = time.strftime("%H:%M:%S")
        bucket.append(item)
        del bucket[:-MAX_EVENTS]

    def mark(self) -> dict[str, int]:
        return {"console": len(self.console), "pageErrors": len(self.page_errors),
                "networkFailures": len(self.network_failures)}

    def since(self, mark: dict[str, int]) -> dict[str, list[dict[str, Any]]]:
        return {
            "console": self.console[mark.get("console", 0):],
            "pageErrors": self.page_errors[mark.get("pageErrors", 0):],
            "networkFailures": self.network_failures[mark.get("networkFailures", 0):],
        }

    def counts(self) -> dict[str, int]:
        return self.mark()


class EvidenceCollector:
    """Attaches listeners to a page and writes evidence bundles on failure."""

    def __init__(self, root: Path, run_id: str) -> None:
        self.root = root / safe_name(run_id, "run")
        self.run_id = run_id
        self.events = PageEvents()
        self._handlers: list[tuple[Any, str, Any]] = []
        self._tracing = False

    # ---------------------------------------------------------- listeners
    def attach(self, page: Any) -> None:
        """Start recording console / page errors / network failures."""
        def on_console(msg: Any) -> None:
            try:
                if msg.type in ("error", "warning"):
                    self.events._add(self.events.console,
                                     {"type": msg.type, "text": scrub(str(msg.text))[:400]})
            except Exception:
                pass

        def on_page_error(err: Any) -> None:
            try:
                self.events._add(self.events.page_errors, {"error": scrub(str(err))[:600]})
            except Exception:
                pass

        def on_request_failed(req: Any) -> None:
            try:
                self.events._add(self.events.network_failures, {
                    "kind": "requestfailed", "method": req.method,
                    "url": scrub(req.url)[:300],
                    "failure": scrub(str(getattr(req, "failure", "") or ""))[:200]})
            except Exception:
                pass

        def on_response(resp: Any) -> None:
            try:
                if resp.status >= 400:
                    self.events._add(self.events.network_failures, {
                        "kind": "http", "status": resp.status,
                        "method": resp.request.method, "url": scrub(resp.url)[:300]})
            except Exception:
                pass

        for event, fn in (("console", on_console), ("pageerror", on_page_error),
                          ("requestfailed", on_request_failed), ("response", on_response)):
            page.on(event, fn)
            self._handlers.append((page, event, fn))

    def detach(self) -> None:
        for page, event, fn in self._handlers:
            try:
                page.remove_listener(event, fn)
            except Exception:
                pass
        self._handlers.clear()

    # ------------------------------------------------------------ tracing
    async def start_trace(self, context: Any, title: str) -> None:
        """One trace chunk per test, so a failure ships only its own recording."""
        if context is None:
            return
        try:
            if not self._tracing:
                await context.tracing.start(screenshots=True, snapshots=True, sources=False)
                self._tracing = True
            await context.tracing.start_chunk(title=title)
        except Exception as exc:
            log.debug("Could not start tracing: %s", type(exc).__name__)

    async def stop_trace(self, context: Any, keep: bool, test_dir: Path) -> str:
        """Stop the chunk. `keep` writes it; otherwise it is discarded."""
        if context is None or not self._tracing:
            return ""
        try:
            if keep:
                test_dir.mkdir(parents=True, exist_ok=True)
                path = test_dir / "trace.zip"
                await context.tracing.stop_chunk(path=str(path))
                return str(path)
            await context.tracing.stop_chunk()
        except Exception as exc:
            log.debug("Could not stop tracing: %s", type(exc).__name__)
        return ""

    async def stop_all(self, context: Any) -> None:
        if context is not None and self._tracing:
            try:
                await context.tracing.stop()
            except Exception:
                pass
            self._tracing = False

    # ---------------------------------------------------------- artefacts
    def test_dir(self, test_name: str) -> Path:
        return self.root / safe_name(test_name, "test")

    async def screenshot(self, page: Any, test_name: str, label: str) -> str:
        if page is None or page.is_closed():
            return ""
        d = self.test_dir(test_name)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{safe_name(label, 'failure')}.png"
        try:
            await page.screenshot(path=str(path), full_page=True)
            return str(path)
        except Exception as exc:
            log.debug("Screenshot failed: %s", type(exc).__name__)
            return ""

    async def page_state(self, page: Any) -> dict[str, Any]:
        """Cheap description of where we actually were when it failed."""
        try:
            return await page.evaluate(
                """() => {
                     // The first VISIBLE heading: an SPA keeps hidden views (a
                     // login screen, other routes) in the DOM, and reporting one
                     // of those as "where we were" is actively misleading.
                     const vis = (e) => {
                       const r = e.getBoundingClientRect();
                       const st = getComputedStyle(e);
                       return r.width > 1 && r.height > 1 && st.display !== 'none'
                              && st.visibility !== 'hidden';
                     };
                     let heading = '';
                     for (const h of document.querySelectorAll('h1,h2,[role=heading]')) {
                       if (vis(h)) { heading = (h.textContent || '').trim().slice(0, 120); break; }
                     }
                     return { url: location.href, title: document.title, heading: heading,
                              readyState: document.readyState };
                   }""")
        except Exception:
            return {}
