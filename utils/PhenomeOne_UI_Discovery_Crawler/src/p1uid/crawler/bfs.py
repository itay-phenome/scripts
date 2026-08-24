"""Safe Crawl: breadth-first autonomous exploration of read-only UI paths.

What it does
------------
Walks the application clicking ONLY actions the safety classifier marked
`auto_clickable` (SAFE_NAVIGATION, no blocking flags), recording every
state -> action -> state edge into the UI map, until a budget runs out.

What it will not do
-------------------
* click anything DANGEROUS, CONDITIONAL or UNKNOWN;
* accept a native dialog - `confirm()`/`alert()` are always dismissed, and the
  action that raised one is never retried;
* accept a download, follow a cross-origin link, or keep a popup;
* continue after the session is lost (a login form reappearing aborts the run).

How it returns to a state
-------------------------
There is no reliable "go back" in a SPA, so a state is re-reached by replaying
its action path from the start URL. Replay is deterministic: each step is the
same validated locator that was used to discover the edge. If a replay step no
longer resolves, that state is marked unreachable and skipped rather than
guessed at.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..discovery import scanner, stability
from ..locator import validator
from ..logging_setup import get
from ..store.uimap import element_key
from . import safety

log = get("crawler")

# Deterministic exploration order: structural navigation first, so the shape of
# the app is mapped before its leaves.
_TYPE_ORDER = {"tab": 0, "treeitem": 1, "link": 2, "pagination": 3, "menuitem": 4, "button": 5}


@dataclass
class CrawlLimits:
    max_states: int = 40
    max_actions: int = 250
    max_depth: int = 6
    per_state_actions: int = 30
    time_budget_s: float = 300.0
    click_timeout_ms: int = 5000
    settle_timeout_ms: int = 4000


@dataclass
class CrawlResult:
    started_at: str = ""
    duration_s: float = 0.0
    states_visited: int = 0
    new_states: list[str] = field(default_factory=list)
    unreachable_states: list[str] = field(default_factory=list)
    actions_clicked: int = 0
    edges_new: int = 0
    replays: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    incidents: list[dict[str, Any]] = field(default_factory=list)
    aborted: str = ""
    limit_hit: str = ""
    timeline: list[dict[str, Any]] = field(default_factory=list)
    classification_totals: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "startedAt": self.started_at,
            "durationSeconds": round(self.duration_s, 1),
            "statesVisited": self.states_visited,
            "newStates": self.new_states,
            "unreachableStates": self.unreachable_states,
            "actionsClicked": self.actions_clicked,
            "newNavigationPaths": self.edges_new,
            "replays": self.replays,
            "skippedByReason": self.skipped,
            "classificationTotals": self.classification_totals,
            "incidents": self.incidents,
            "abortedBecause": self.aborted,
            "limitHit": self.limit_hit,
            "timeline": self.timeline[-500:],
        }


@dataclass
class _Candidate:
    key: str
    element: dict[str, Any]
    locator: Any                # p1uid.locator.generator.Locator
    frame: Any
    verdict: Any

    @property
    def label(self) -> str:
        return self.element.get("name") or self.element.get("directText") or self.key


class SafeCrawler:
    def __init__(self, engine: Any, store: Any, limits: CrawlLimits | None = None) -> None:
        self.engine = engine
        self.store = store
        self.limits = limits or CrawlLimits()
        self.result = CrawlResult()
        self._start = 0.0
        self._poison: set[tuple[str, str]] = set()      # (state, element) never to click again
        self._tried: set[tuple[str, str]] = set()
        self._dialog_seen: list[str] = []
        self._page = None
        self._handlers: list[tuple[str, Any]] = []

    # ------------------------------------------------------------- budgeting
    def _budget_left(self) -> str:
        if self.result.actions_clicked >= self.limits.max_actions:
            return "max_actions"
        if self.result.states_visited >= self.limits.max_states:
            return "max_states"
        if time.monotonic() - self._start >= self.limits.time_budget_s:
            return "time_budget"
        return ""

    def _skip(self, reason: str) -> None:
        self.result.skipped[reason] = self.result.skipped.get(reason, 0) + 1

    # -------------------------------------------------------------- guards
    def _install_guards(self, page: Any) -> None:
        def on_dialog(dialog: Any) -> None:
            # Never accept. A confirm() that reaches us means the classifier let
            # something through, so record it loudly.
            msg = (dialog.message or "")[:200]
            self._dialog_seen.append(msg)
            self.result.incidents.append({"kind": "native-dialog", "type": dialog.type,
                                          "message": msg})
            log.warning("Native %s dialog appeared and was DISMISSED: %s", dialog.type, msg)
            try:
                dialog.dismiss()
            except Exception:
                pass

        def on_download(dl: Any) -> None:
            self.result.incidents.append({"kind": "download-blocked",
                                          "url": (getattr(dl, "url", "") or "")[:200]})
            log.warning("A download was triggered and refused")

        def on_popup(popup: Any) -> None:
            self.result.incidents.append({"kind": "popup-closed", "url": (popup.url or "")[:200]})
            log.warning("A popup opened during the crawl and was closed")

            async def _close() -> None:
                try:
                    await popup.close()
                except Exception:
                    pass

            import asyncio
            asyncio.ensure_future(_close())

        for event, fn in (("dialog", on_dialog), ("download", on_download), ("popup", on_popup)):
            page.on(event, fn)
            self._handlers.append((event, fn))

    def _remove_guards(self, page: Any) -> None:
        for event, fn in self._handlers:
            try:
                page.remove_listener(event, fn)
            except Exception:
                pass
        self._handlers.clear()

    # ---------------------------------------------------------------- scan
    async def _scan(self) -> Any:
        return await scanner.scan_page(self._page, self.store, origin=self.engine.origin,
                                       validate_limit=self.engine.validate_limit,
                                       validate_new_only=True, keep_rows=True)

    def _candidates(self, res: Any) -> list[_Candidate]:
        """Auto-clickable actions in this state, deterministically ordered."""
        out: list[_Candidate] = []
        seen: set[str] = set()
        totals = self.result.classification_totals
        for frame, el, loc in res.rows:
            verdict = safety.classify(el, origin=self.engine.origin)
            totals[verdict.classification] = totals.get(verdict.classification, 0) + 1
            if not verdict.auto_clickable:
                self._skip(verdict.classification.lower())
                continue
            if loc.matches != 1:
                self._skip("locator-not-unique")
                continue
            if el.get("visible") is not True or el.get("enabled") is not True:
                self._skip("not-actionable")
                continue
            key = element_key(el)
            if key in seen:
                continue
            seen.add(key)
            out.append(_Candidate(key, el, loc, frame, verdict))
        out.sort(key=lambda c: (_TYPE_ORDER.get(c.element.get("type", ""), 9),
                               (c.element.get("name") or "").lower(), c.key))
        return out[: self.limits.per_state_actions]

    # --------------------------------------------------------------- moving
    async def _goto_root(self) -> bool:
        try:
            await self._page.goto(self.engine.base_url, wait_until="domcontentloaded",
                                 timeout=30000)
            await stability.wait_stable(self._page, timeout_ms=self.limits.settle_timeout_ms)
            return True
        except Exception as exc:
            log.warning("Could not return to the start URL: %s", type(exc).__name__)
            return False

    async def _replay(self, path: list[dict[str, Any]]) -> bool:
        """Re-reach a state by replaying its discovered action path from the root."""
        self.result.replays += 1
        if not await self._goto_root():
            return False
        if await self._session_lost():
            return False
        for step in path:
            loc = step["locator"]
            frame_url = step.get("frameUrl") or ""
            frame = self._resolve_frame(frame_url)
            if frame is None:
                log.debug("Replay failed: frame %s is gone", frame_url)
                return False
            try:
                handle = validator.build(frame, loc)
                if await handle.count() != 1:
                    log.debug("Replay failed: %s no longer resolves uniquely", loc.js)
                    return False
                await handle.first.click(timeout=self.limits.click_timeout_ms)
            except Exception as exc:
                log.debug("Replay click failed on %s: %s", loc.js, type(exc).__name__)
                return False
            await stability.wait_stable(self._page, timeout_ms=self.limits.settle_timeout_ms)
        return True

    def _resolve_frame(self, frame_url: str) -> Any:
        if not frame_url:
            return self._page.main_frame
        for f in self._page.frames:
            if f.url == frame_url:
                return f
        return None

    async def _session_lost(self) -> bool:
        from ..auth import login as auth_login
        try:
            for frame in list(self._page.frames):
                fields = await auth_login.read_fields(frame)
                if any(f["type"] == "password" and f["visible"] for f in fields.get("inputs", [])):
                    return True
        except Exception:
            return False
        return False

    # ------------------------------------------------------------------ run
    async def run(self, start_url: str = "") -> CrawlResult:
        self._start = time.monotonic()
        self.result.started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._page = self.engine.page
        if start_url:
            self.engine.base_url = start_url
        if not self.engine.base_url:
            self.engine.base_url = self._page.url

        self._install_guards(self._page)
        log.info("Safe Crawl starting - limits: %d states, %d actions, depth %d, %.0fs",
                 self.limits.max_states, self.limits.max_actions, self.limits.max_depth,
                 self.limits.time_budget_s)
        try:
            await self._crawl()
        finally:
            self._remove_guards(self._page)
            self.result.duration_s = time.monotonic() - self._start

        log.info("Safe Crawl finished: %d states (%d new), %d actions clicked, %d new paths%s",
                 self.result.states_visited, len(self.result.new_states),
                 self.result.actions_clicked, self.result.edges_new,
                 f", ABORTED: {self.result.aborted}" if self.result.aborted else "")
        if self.result.skipped:
            log.info("Not clicked: %s", ", ".join(f"{k}={v}" for k, v in
                                                  sorted(self.result.skipped.items())))
        for inc in self.result.incidents:
            log.warning("Incident: %s", inc)
        return self.result

    async def _crawl(self) -> None:
        await stability.wait_stable(self._page, timeout_ms=self.limits.settle_timeout_ms)
        res = await self._scan()
        if res is None:
            self.result.aborted = "nothing analysable at the start URL"
            return

        root = res.state_id
        queue: list[tuple[str, list[dict[str, Any]]]] = [(root, [])]
        enqueued: set[str] = {root}
        current: str | None = root
        visited: set[str] = set()

        while queue:
            hit = self._budget_left()
            if hit:
                self.result.limit_hit = hit
                log.info("Budget reached (%s); stopping cleanly", hit)
                break

            state_id, path = queue.pop(0)
            if len(path) > self.limits.max_depth:
                self._skip("max-depth")
                continue

            # Get to the state we intend to explore.
            if current != state_id:
                if not await self._replay(path):
                    self.result.unreachable_states.append(state_id)
                    log.warning("State %s could not be re-reached; skipping it", state_id)
                    current = None
                    continue
                probe = await self._scan()
                if probe is None or probe.state_id != state_id:
                    got = probe.state_id if probe else "?"
                    log.warning("Replay of %s landed on %s; skipping", state_id, got)
                    self.result.unreachable_states.append(state_id)
                    current = got if probe else None
                    continue
                res = probe
                current = state_id

            visited.add(state_id)
            self.result.states_visited = len(visited)
            cands = self._candidates(res)
            log.info("Exploring %s (depth %d): %d safe action(s) of %d elements",
                     state_id, len(path), len(cands), res.elements)

            for cand in cands:
                hit = self._budget_left()
                if hit:
                    self.result.limit_hit = hit
                    break
                ident = (state_id, cand.key)
                if ident in self._tried or ident in self._poison:
                    continue
                self._tried.add(ident)

                if current != state_id:
                    if not await self._replay(path):
                        current = None
                        break
                    probe = await self._scan()
                    if probe is None or probe.state_id != state_id:
                        current = probe.state_id if probe else None
                        break
                    res = probe
                    current = state_id
                    fresh = {c.key: c for c in self._candidates(res)}
                    if cand.key not in fresh:
                        self._skip("gone-after-replay")
                        continue
                    cand = fresh[cand.key]

                outcome = await self._click(state_id, path, cand)
                if outcome == "aborted":
                    return
                current = self.result.timeline[-1]["to"] if self.result.timeline else None

                dest = current
                if dest and dest != state_id and dest not in enqueued \
                        and len(path) + 1 <= self.limits.max_depth:
                    enqueued.add(dest)
                    queue.append((dest, path + [{
                        "locator": cand.locator,
                        "frameUrl": "" if cand.frame is self._page.main_frame else cand.frame.url,
                        "label": cand.label,
                        "type": cand.element.get("type"),
                    }]))

    async def _click(self, state_id: str, path: list[dict[str, Any]],
                     cand: _Candidate) -> str:
        """Click one safe candidate and record where it led."""
        before_dialogs = len(self._dialog_seen)
        origin_before = self.engine.origin
        try:
            handle = validator.build(cand.frame, cand.locator)
            if await handle.count() != 1:
                self._skip("vanished-before-click")
                return "skipped"
            await handle.first.click(timeout=self.limits.click_timeout_ms)
            self.result.actions_clicked += 1
        except Exception as exc:
            self._skip("click-failed")
            log.debug("Click failed on %s: %s", cand.locator.js, type(exc).__name__)
            return "skipped"

        await stability.wait_stable(self._page, timeout_ms=self.limits.settle_timeout_ms)

        if len(self._dialog_seen) > before_dialogs:
            # It raised a native dialog: the classifier under-rated it. Never again.
            self._poison.add((state_id, cand.key))
            self._skip("raised-native-dialog")
            log.warning("%r raised a native dialog; poisoned and not retried", cand.label)

        if await self._session_lost():
            self.result.aborted = f"session lost after clicking {cand.label!r}"
            self.result.incidents.append({"kind": "session-lost", "action": cand.label})
            log.error("Session lost after clicking %r - aborting the crawl", cand.label)
            return "aborted"

        try:
            origin_now = await self._page.evaluate("() => location.origin")
        except Exception:
            origin_now = origin_before
        if origin_before and origin_now != origin_before:
            self._poison.add((state_id, cand.key))
            self.result.incidents.append({"kind": "left-origin", "action": cand.label,
                                          "origin": origin_now})
            log.warning("%r left the origin (%s); returning and poisoning it", cand.label, origin_now)
            await self._replay(path)
            return "skipped"

        res = await self._scan()
        if res is None:
            self._skip("unscannable-destination")
            return "skipped"

        dest = res.state_id
        if dest == state_id:
            self._skip("no-state-change")
        else:
            action = {
                "type": cand.element.get("type") or "click",
                "name": cand.label,
                "role": cand.element.get("role") or "",
                "interaction": "crawler-click",
                "trigger": "safe-crawl",
                "safety": cand.verdict.classification,
                "locator": cand.locator.js,
                "locatorSpec": cand.locator.to_json(),
            }
            if self.store.merge_edge(state_id, action, dest):
                self.result.edges_new += 1
            if res.is_new_state:
                self.result.new_states.append(dest)
                log.info("New state discovered by crawl: %s (%s)", dest, res.label)

        self.result.timeline.append({"from": state_id, "action": cand.label,
                                     "type": cand.element.get("type"), "to": dest,
                                     "at": time.strftime("%H:%M:%S")})
        return "clicked"
