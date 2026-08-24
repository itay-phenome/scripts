"""Training mode (spec 5, 13, 15, 16).

The user drives PhenomeOne; this class only listens. Browser-side listeners
report *what was clicked* and *that the UI changed*; here those two facts are
correlated into navigation edges:

    source UI state  --(user action)-->  destination UI state

Efficiency (spec 13): the browser only reports a change when its cheap
structural signature actually changes; Python then debounces bursts and enforces
a minimum interval between full scans, so a flurry of DOM mutations costs one
scan, not hundreds.

Nothing is ever clicked by this module (spec 23).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from ..logging_setup import get
from ..locator.generator import LOW, MEDIUM, candidates
from ..store.uimap import element_key
from .workflows import Workflow, WorkflowStore

log = get("training")

DEBOUNCE_S = 0.20          # collapse bursts of change events
MIN_SCAN_INTERVAL_S = 0.35  # never rescan more often than this
ACTION_TTL_S = 10.0        # a click older than this no longer explains a state change
FALLBACK_TTL_S = 3.0       # window for attributing a cause-less change to the last click


class Trainer:
    def __init__(self, engine: Any, store: Any) -> None:
        self.engine = engine
        self.store = store
        self.page = None

        self.started_at = 0.0
        self.stopped_at = 0.0
        self.current_sid: str | None = None
        self.pending_action: dict[str, Any] | None = None
        self.last_action: dict[str, Any] | None = None

        self.states_seen: set[str] = set()
        self.new_states: list[str] = []
        self.new_edges = 0
        self.edges_seen: set[str] = set()
        self.actions_observed = 0
        self.scans = 0
        self.scan_ms_total = 0
        self.timeline: list[dict[str, Any]] = []

        self._dirty_reason = ""
        self._pending_rescan = ""
        self._timer: asyncio.TimerHandle | None = None
        self._scan_lock = asyncio.Lock()
        self._last_scan_at = 0.0
        self._stopped = False
        self.workflow: Workflow | None = None
        self.workflow_store = WorkflowStore().load()

    # -------------------------------------------------------------- control
    async def start(self, page: Any) -> None:
        self.page = page
        self.started_at = time.time()
        await self._scan_now("training-started")

    async def stop(self) -> dict[str, Any]:
        self._stopped = True
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        async with self._scan_lock:
            pass                      # let an in-flight scan finish
        self.end_workflow()
        self.stopped_at = time.time()
        return self.summary()

    # ------------------------------------------------------------ workflows
    def begin_workflow(self, name: str) -> None:
        if self.workflow is not None:
            self.end_workflow()
        self.workflow = Workflow(name=name, start_state=self.current_sid or "")
        log.info("Recording workflow %r from state %s", name, self.current_sid or "(unknown)")

    def end_workflow(self) -> dict[str, Any] | None:
        wf = self.workflow
        self.workflow = None
        if wf is None:
            return None
        if not wf.steps:
            log.warning("Workflow %r had no steps; not saved", wf.name)
            return None
        entry = self.workflow_store.merge(wf)
        self.workflow_store.save()
        log.info("Workflow %r recorded: %d steps (%s -> %s)", wf.name, len(wf.steps),
                 wf.start_state or "?", entry.get("endState") or "?")
        return entry

    def _workflow_step(self, action: dict[str, Any], from_sid: str, to_sid: str) -> None:
        if self.workflow is None:
            return
        kind = "navigate" if from_sid != to_sid else "activate"
        if action.get("interaction") == "change":
            kind = "fill"
        self.workflow.add_step(kind, action.get("name") or action.get("type") or "?",
                               from_sid, to_sid, action.get("locator") or "",
                               action.get("type") or "")

    def summary(self) -> dict[str, Any]:
        dur = max(0.0, (self.stopped_at or time.time()) - self.started_at)
        counts = self.store.counts()
        return {
            "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.started_at)),
            "stoppedAt": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.stopped_at or time.time())),
            "durationSeconds": round(dur, 1),
            "statesSeen": len(self.states_seen),
            "newStates": self.new_states,
            "navigationPaths": counts["navigationPaths"],
            "newNavigationPaths": self.new_edges,
            "elementsSeen": counts["elements"],
            "actionsObserved": self.actions_observed,
            "scans": self.scans,
            "avgScanMs": int(self.scan_ms_total / self.scans) if self.scans else 0,
            "timeline": self.timeline[-400:],
            "mapTotals": {k: v for k, v in counts.items() if k != "weak"},
            "workflows": self.workflow_store.names(),
        }

    # --------------------------------------------------------------- events
    async def on_event(self, ev: dict[str, Any], page: Any) -> None:
        if self._stopped:
            return
        if page is not None:
            self.page = page
        kind = ev.get("kind")
        if kind == "action":
            self._on_action(ev)
        elif kind == "route":
            # Informational only. A route change also flips the browser-side
            # signature, so the authoritative `state-changed` event follows -
            # and only that one carries the causing action. Scanning here too
            # would race it and lose the attribution.
            log.debug("SPA route change via %s", ev.get("via"))
        elif kind == "state-changed":
            cause = ev.get("cause")
            if cause and cause.get("element"):
                self._set_cause(cause)
            self._schedule_scan(ev.get("reason") or kind)

    @staticmethod
    def _sanitise(el: dict[str, Any]) -> dict[str, Any]:
        if el.get("type") == "password":
            return {**el, "name": "password", "directText": ""}   # never describe secrets
        return el

    def _on_action(self, ev: dict[str, Any]) -> None:
        el = self._sanitise(ev.get("element") or {})
        self.actions_observed += 1
        # Fallback attribution: used only if a state change arrives without a
        # cause (e.g. the change was detected by a different frame).
        self.last_action = {"element": el, "action": ev.get("action", "click"),
                            "at": time.monotonic()}
        label = el.get("name") or el.get("directText") or el.get("type") or "element"
        log.info("User %s: %s (%s)", ev.get("action", "click"), label, el.get("type") or "?")

    def _set_cause(self, cause: dict[str, Any]) -> None:
        self.pending_action = {"element": self._sanitise(cause.get("element") or {}),
                               "action": cause.get("action", "click"),
                               "at": time.monotonic(), "from": self.current_sid}

    # ----------------------------------------------------------- scheduling
    def _schedule_scan(self, reason: str) -> None:
        """Debounced, coalescing trigger - a burst of events costs one scan."""
        self._dirty_reason = reason
        loop = asyncio.get_running_loop()
        if self._timer is not None:
            self._timer.cancel()
        delay = DEBOUNCE_S
        since = time.monotonic() - self._last_scan_at
        if since < MIN_SCAN_INTERVAL_S:
            delay = max(delay, MIN_SCAN_INTERVAL_S - since)
        self._timer = loop.call_later(delay, lambda: asyncio.ensure_future(self._fire()))

    async def _fire(self) -> None:
        self._timer = None
        if self._stopped:
            return
        await self._scan_now(self._dirty_reason or "change")

    async def _scan_now(self, reason: str) -> None:
        if self._scan_lock.locked():
            # Never drop a change: remember it and rescan once the current
            # scan finishes, otherwise fast navigation loses UI states.
            self._pending_rescan = reason
            return
        async with self._scan_lock:
            page = self.page
            if page is None or page.is_closed():
                return
            from ..discovery import scanner
            self._last_scan_at = time.monotonic()
            res = await scanner.scan_page(page, self.store, origin=self.engine.origin,
                                          validate_limit=self.engine.validate_limit,
                                          validate_new_only=True)
            if res is None:
                return
            self.scans += 1
            self.scan_ms_total += res.timings_ms.get("total", 0)
            prev = self.current_sid
            self.current_sid = res.state_id
            self.states_seen.add(res.state_id)

            if res.is_new_state:
                self.new_states.append(res.state_id)
                log.info("New state discovered: %s  (%s)", res.state_id, res.label)
                log.info("Elements discovered: %d", res.elements)
            elif prev != res.state_id:
                log.info("Returned to known state: %s", res.state_id)

            if prev and prev != res.state_id:
                self._link(prev, res.state_id, reason)

            self.engine.emit(type="training-progress", summary=self.summary(),
                             counts=self.store.counts(), state=res.state_id,
                             scan_ms=res.timings_ms.get("total", 0))

        if self._pending_rescan and not self._stopped:
            reason, self._pending_rescan = self._pending_rescan, ""
            self._schedule_scan(reason)

    # ---------------------------------------------------------- graph edges
    def _link(self, from_sid: str, to_sid: str, reason: str) -> None:
        act = self.pending_action
        if act is None and self.last_action and (time.monotonic() - self.last_action["at"]) <= FALLBACK_TTL_S:
            act = self.last_action
            self.last_action = None      # consume it: never attribute one click twice
        if act is None or (time.monotonic() - act["at"]) > ACTION_TTL_S:
            action = {"type": "unknown", "name": "", "trigger": reason,
                      "note": "state changed without an observed user action"}
        else:
            el = act["element"]
            action = {
                "type": el.get("type") or "click",
                "name": el.get("name") or el.get("directText") or "",
                "role": el.get("role") or "",
                "interaction": act["action"],
                "trigger": reason,
            }
            loc = self._locator_for(from_sid, el)
            if loc:
                action["locator"] = loc["js"]
                action["locatorSpec"] = loc
            self.pending_action = None

        is_new = self.store.merge_edge(from_sid, action, to_sid)
        if is_new:
            self.new_edges += 1
        key = f"{from_sid}->{action.get('name')}->{to_sid}"
        self.edges_seen.add(key)
        self.timeline.append({"from": from_sid, "action": action, "to": to_sid,
                              "at": time.strftime("%H:%M:%S")})
        self._workflow_step(action, from_sid, to_sid)
        log.info("Navigation learned%s: %s --[%s %s]--> %s", "" if is_new else " (already known)",
                 from_sid, action.get("type"), action.get("name") or "?", to_sid)

    def _locator_for(self, sid: str, el: dict[str, Any]) -> dict[str, Any] | None:
        """Prefer the already-validated locator from the source state's scan."""
        state = self.store.data["states"].get(sid) or {}
        entry = (state.get("elements") or {}).get(element_key(el))
        if entry and entry.get("locator"):
            return entry["locator"]
        cands = candidates(el, {})           # no page counts available for a click event
        if not cands:
            return None
        loc = cands[0]
        if loc.confidence != LOW:
            loc.confidence = MEDIUM
            loc.notes.append("generated from the click event; uniqueness not validated")
        return loc.to_json()
