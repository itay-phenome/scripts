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
* accept a download, or stay on a surface that is not the application;
* continue after the session is lost (a login form reappearing aborts the run).

How it decides what an action did
---------------------------------
Nothing is predicted from the control's attributes. The action is performed, the
browser is observed, and `outcomes.classify()` turns what happened into a set of
facts: a new state, a surface change with no new state (an opened menu), a new
browsing context and whether it belongs to the application, a native dialog, an
off-origin navigation, a lost session, or nothing at all. See `surfaces.py` for
how a new tab or window is judged to be ours.

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
from . import outcomes, safety, surfaces

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
    # A global control (the "Home" link in the banner, say) exists in every
    # state. Clicking it from all of them costs O(states^2) clicks and teaches
    # nothing new after the first few, so cap how often one control is retried.
    max_repeats_per_element: int = 3


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
    back_navigations: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    inert_elements: int = 0
    incidents: list[dict[str, Any]] = field(default_factory=list)
    aborted: str = ""
    limit_hit: str = ""
    timeline: list[dict[str, Any]] = field(default_factory=list)
    classification_totals: dict[str, int] = field(default_factory=dict)
    # What actions actually did, counted by observed outcome rather than by the
    # kind of control that was clicked.
    outcome_totals: dict[str, int] = field(default_factory=dict)
    surfaces_opened: int = 0
    surface_changes: int = 0
    surfaces: list[dict[str, Any]] = field(default_factory=list)

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
            "backNavigations": self.back_navigations,
            "skippedByReason": self.skipped,
            "inertElements": self.inert_elements,
            "classificationTotals": self.classification_totals,
            "outcomeTotals": self.outcome_totals,
            "surfacesOpened": self.surfaces_opened,
            "surfaceChanges": self.surface_changes,
            "surfaces": self.surfaces,
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
        self._clicks_per_element: dict[str, int] = {}
        self._noop_elements: set[str] = set()      # inert in >= 2 distinct states
        self._noop_seen: dict[str, set[str]] = {}  # element -> states where it did nothing
        self._dialog_seen: list[str] = []
        self._page = None
        self._handlers: list[tuple[Any, str, Any]] = []
        # Browsing contexts that appeared during the action currently in flight.
        # Collected by the popup listener, classified in `_click`.
        self._pending_pages: list[Any] = []
        self.registry: surfaces.SurfaceRegistry | None = None
        # Extra origins the caller declares as part of the application.
        self.extra_origins: tuple[str, ...] = ()

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
            # COLLECT, do not decide. Closing a popup here was a fixed rule that
            # made any part of the application opening in a new browsing context
            # unreachable - and it closed asynchronously, racing the scan that
            # followed. What this is gets decided in `_click`, from its URL.
            self._pending_pages.append(popup)

        for event, fn in (("dialog", on_dialog), ("download", on_download), ("popup", on_popup)):
            page.on(event, fn)
            self._handlers.append((page, event, fn))

    def _remove_guards(self, page: Any = None) -> None:
        """Detach every listener we installed, on every surface."""
        for owner, event, fn in self._handlers:
            try:
                owner.remove_listener(event, fn)
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
            if key in self._noop_elements:
                # Proven inert elsewhere (a "Refresh" that redraws the same
                # state): clicking it again cannot discover anything.
                self._skip("known-no-op")
                continue
            if self._clicks_per_element.get(key, 0) >= self.limits.max_repeats_per_element:
                self._skip("repeat-limit")
                continue
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

    async def _go_back_to(self, state_id: str) -> Any:
        """Cheap return path: one history step. Returns the scan if it worked."""
        try:
            await self._page.go_back(timeout=5000, wait_until="domcontentloaded")
        except Exception:
            return None
        await stability.wait_stable(self._page, timeout_ms=self.limits.settle_timeout_ms)
        try:
            probe = await self._scan()
        except Exception:
            return None
        if probe is not None and probe.state_id == state_id:
            self.result.back_navigations += 1
            return probe
        return None

    async def _return_to(self, state_id: str, path: list[dict[str, Any]]) -> Any:
        """Get back to `state_id`, cheaply if possible. Returns its scan or None."""
        probe = await self._go_back_to(state_id)
        if probe is not None:
            return probe
        if not await self._replay(path):
            return None
        probe = await self._scan()
        if probe is None or probe.state_id != state_id:
            return None
        return probe

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
        """A login form is only a lost session if the app has stopped rendering.

        An embedded sign-in widget (an identity-provider iframe on a settings
        page, say) must not abort a crawl that is still perfectly authenticated.
        """
        from ..auth import login as auth_login
        try:
            found = False
            for frame in list(self._page.frames):
                fields = await auth_login.read_fields(frame)
                if any(f["type"] == "password" and f["visible"] for f in fields.get("inputs", [])):
                    found = True
                    break
            if not found:
                return False
            return not await auth_login.looks_authenticated(self._page)
        except Exception:
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

        self.registry = surfaces.SurfaceRegistry(self.engine.base_url, self.extra_origins)
        self.registry.register(self._page, kind=surfaces.MAIN, scope=surfaces.IN_SCOPE)

        self._install_guards(self._page)
        log.info("Safe Crawl starting - limits: %d states, %d actions, depth %d, %.0fs",
                 self.limits.max_states, self.limits.max_actions, self.limits.max_depth,
                 self.limits.time_budget_s)
        try:
            await self._crawl()
        finally:
            self._remove_guards()
            self.result.inert_elements = len(self._noop_elements)
            self.result.duration_s = time.monotonic() - self._start
            if self.registry is not None:
                self.result.surfaces = self.registry.to_json()

        log.info("Safe Crawl finished: %d states (%d new), %d actions clicked, %d new paths%s",
                 self.result.states_visited, len(self.result.new_states),
                 self.result.actions_clicked, self.result.edges_new,
                 f", ABORTED: {self.result.aborted}" if self.result.aborted else "")
        if self.result.outcome_totals:
            log.info("What actions did: %s", ", ".join(
                f"{k}={v}" for k, v in sorted(self.result.outcome_totals.items())))
        if self.result.skipped:
            log.info("Not clicked: %s", ", ".join(f"{k}={v}" for k, v in
                                                  sorted(self.result.skipped.items())))
        for inc in self.result.incidents:
            log.warning("Incident: %s", inc)
        return self.result

    async def _crawl(self) -> None:
        # Always start from the start URL so the root state is reproducible and
        # re-reachable; otherwise replay can never return to it.
        if not await self._goto_root():
            self.result.aborted = "could not open the start URL"
            return
        if await self._session_lost():
            self.result.aborted = "not authenticated at the start URL"
            return
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
                probe = await self._return_to(state_id, path)
                if probe is None:
                    self.result.unreachable_states.append(state_id)
                    log.warning("State %s could not be re-reached; skipping it", state_id)
                    current = None
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
                    probe = await self._return_to(state_id, path)
                    if probe is None:
                        current = None
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

    # ------------------------------------------------------------- surfaces
    def _page_ids(self) -> set[int]:
        try:
            return {id(p) for p in self.engine.context.pages}
        except Exception:
            return set()

    async def _await_new_context(self, before: set[int], budget_ms: int = 600) -> None:
        """Give a browsing context a bounded moment to attach.

        `window.open()` returns before Playwright has a Page for the new target,
        so a diff taken immediately after the settle wait sometimes missed it -
        and the context was then found during the NEXT action and credited to the
        wrong control. Waiting here makes the attribution correct by
        construction; it exits as soon as something appears, so an action that
        opens nothing pays only the first poll.
        """
        waited = 0
        while waited < budget_ms:
            if self._page_ids() - before:
                return
            await self._page.wait_for_timeout(100)
            waited += 100

    async def _collect_new_surfaces(self, before: set[int]) -> list[tuple[Any, str]]:
        """Resolve the scope of every browsing context this action opened.

        A new context needs a moment to have a real URL: `window.open()` starts
        at about:blank and navigates immediately afterwards, so classifying it
        the instant the event fires would call the application UNKNOWN.
        """
        # The popup event can be delivered after the settle wait, which made
        # detection timing-dependent: the same click reported a new surface on one
        # run and nothing on the next. So the event is a hint, and the authority
        # is the context's own page list - a browsing context that exists and is
        # not in the registry is new, however it was opened.
        pending: list[Any] = list(self._pending_pages)
        try:
            for page in self.engine.context.pages:
                if page is self._page or id(page) in before:
                    continue                      # existed before this action
                if self.registry is not None and self.registry.find(page) is not None:
                    continue
                if not any(page is p for p in pending):
                    pending.append(page)
        except Exception:
            log.debug("Could not enumerate browsing contexts")

        found: list[tuple[Any, str]] = []
        for page in pending:
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=4000)
            except Exception:
                pass                      # a slow or already-closed context
            scope = await surfaces.scope_of(page, self.engine.base_url, self.extra_origins)
            found.append((page, scope))
        self._pending_pages.clear()
        return found

    async def _dispose_surface(self, page: Any, why: str, action: str) -> None:
        """Close a context that is not ours, without disturbing the parent."""
        url = ""
        try:
            url = page.url or ""
        except Exception:
            pass
        self.result.incidents.append({"kind": f"surface-{why}", "action": action,
                                      "url": url[:200]})
        log.info("A %s surface opened via %r (%s); closing it and continuing",
                 why, action, url[:80] or "unknown url")
        try:
            if not page.is_closed():
                await page.close()
        except Exception:
            log.debug("Could not close a %s surface", why)

    async def _handle_new_surfaces(self, obs: outcomes.Observation, state_id: str,
                                   cand: _Candidate) -> list[str]:
        """Register application surfaces, dispose of the rest.

        Returns the states discovered on child surfaces. The parent surface is
        untouched throughout: `self._page` only ever moves inside
        `_explore_surface`, which restores it.
        """
        discovered: list[str] = []
        for page, scope in obs.new_surfaces:
            if scope != surfaces.IN_SCOPE:
                await self._dispose_surface(page, scope, cand.label)
                continue
            if self.registry is None:
                continue
            kind = surfaces.TAB if (cand.element.get("type") == "link") else surfaces.POPUP
            surface = self.registry.register(page, kind=kind, scope=scope,
                                             opened_by_state=state_id,
                                             opened_by_action=cand.label)
            self.result.surfaces_opened += 1
            log.info("A surface of the application opened via %r: %s",
                     cand.label, surface.describe())
            discovered += await self._explore_surface(surface, state_id, cand)
        return discovered

    async def _explore_surface(self, surface: Any, parent_state: str,
                               cand: _Candidate) -> list[str]:
        """Scan a child surface, record the parent -> action -> child edge.

        The child is explored while we are on it and then closed: a child tab is
        not re-reachable by replaying from the start URL, so exploring it later
        would mean re-opening it, and its state may not survive that. Recording
        the relationship now keeps the graph honest either way.
        """
        found: list[str] = []
        parent_page = self._page
        installed = False
        try:
            self._page = surface.page
            # The guards belong to whatever surface we are working on: a native
            # dialog or a download raised on a child is exactly as dangerous as
            # on the parent, and without this the child would have none.
            self._install_guards(surface.page)
            installed = True

            # A child that is a sign-in gate is not explorable content. Recording
            # it and moving on is the honest outcome - crawling a login form would
            # be both useless and a good way to lock an account.
            if await self._session_lost():
                self.result.incidents.append({
                    "kind": "surface-unauthenticated", "action": cand.label,
                    "url": (surface.url or "")[:200]})
                log.warning("The %s surface opened by %r is a sign-in gate, not "
                            "application content; leaving it alone", surface.kind, cand.label)
                self._skip("surface-unauthenticated")
                return found

            res = await self._scan()
            if res is None:
                self._skip("unscannable-surface")
                return found
            surface.visited.add(res.state_id)
            found.append(res.state_id)
            action = {
                "type": cand.element.get("type") or "click",
                "name": cand.label,
                "role": cand.element.get("role") or "",
                "interaction": "crawler-click",
                "trigger": "safe-crawl",
                "safety": cand.verdict.classification,
                "locator": cand.locator.js,
                "locatorSpec": cand.locator.to_json(),
                # How this state is reached matters to anyone replaying it: the
                # child lives in its own browsing context, not in the parent.
                "opensSurface": {"kind": surface.kind, "scope": surface.scope},
            }
            if self.store.merge_edge(parent_state, action, res.state_id):
                self.result.edges_new += 1
            if res.is_new_state:
                self.result.new_states.append(res.state_id)
                log.info("New state discovered on a %s surface: %s (%s)",
                         surface.kind, res.state_id, res.label)

            # Now CRAWL it, not just look at it. A germplasm detail tab has its
            # own tabs and controls; scanning the landing state and closing the
            # tab would map the door and none of the rooms.
            found += await self._crawl_surface(surface, res)
        except Exception as exc:
            log.warning("Could not explore the %s surface: %s", surface.kind, type(exc).__name__)
        finally:
            if installed:
                self._remove_guards()
                self._install_guards(parent_page)     # hand the guards back
            self._page = parent_page
            try:
                if not surface.page.is_closed():
                    await surface.page.close()
            except Exception:
                pass
            if self.registry is not None:
                self.registry.forget(surface)
        return found

    async def _crawl_surface(self, surface: Any, res: Any) -> list[str]:
        """Explore within one child surface, one level deep.

        Deliberately not a full BFS: a child context cannot be re-reached by
        replaying from the start URL, so there is nothing to return *to* if we
        wander. Each safe action on the child is clicked once, the resulting
        state recorded, and exploration stops the moment the surface stops being
        ours - closed by the application, navigated off-origin, or showing a
        sign-in form.
        """
        found: list[str] = []
        state_id = res.state_id
        clicked = 0
        for child_cand in self._candidates(res):
            if clicked >= self.limits.per_surface_actions:
                break
            hit = self._budget_left()
            if hit:
                self.result.limit_hit = hit
                break
            if surface.page.is_closed():
                # The application closed its own window mid-exploration. Not an
                # error: record it, stop, and let the parent carry on.
                self.result.incidents.append({"kind": "surface-closed-by-app",
                                              "url": (surface.url or "")[:200]})
                log.info("The %s surface closed itself; returning to the parent", surface.kind)
                break

            next_res = await self._click_on_surface(surface, state_id, child_cand)
            clicked += 1
            if next_res is None:
                continue
            if next_res.state_id != state_id:
                surface.visited.add(next_res.state_id)
                found.append(next_res.state_id)
                # Explore from the state we actually landed on, so a two-step
                # path inside the child is still reachable.
                state_id = next_res.state_id
                res = next_res
        return found

    async def _click_on_surface(self, surface: Any, state_id: str,
                                cand: _Candidate) -> Any:
        """One click on a child surface. No replay: there is nowhere to replay to.

        Returns the scan of where it landed, or None if nothing usable happened.
        """
        before_dialogs = len(self._dialog_seen)
        try:
            handle = validator.build(cand.frame, cand.locator)
            if await handle.count() != 1:
                self._skip("vanished-before-click")
                return None
            await handle.first.click(timeout=self.limits.click_timeout_ms)
            self.result.actions_clicked += 1
        except Exception as exc:
            self._skip("click-failed")
            log.debug("Click failed on a surface: %s", type(exc).__name__)
            return None

        try:
            await stability.wait_stable(surface.page, timeout_ms=self.limits.settle_timeout_ms)
        except Exception:
            pass
        if surface.page.is_closed():
            self.result.incidents.append({"kind": "surface-closed-by-app",
                                          "action": cand.label})
            log.info("%r closed the %s surface", cand.label, surface.kind)
            return None

        if len(self._dialog_seen) > before_dialogs:
            self._skip("raised-native-dialog")
            log.warning("%r raised a native dialog on a %s surface", cand.label, surface.kind)

        # Still ours? A child that navigates away stops being explorable content.
        scope = await surfaces.scope_of(surface.page, self.engine.base_url, self.extra_origins)
        if scope != surfaces.IN_SCOPE:
            self.result.incidents.append({"kind": "surface-left-scope", "action": cand.label,
                                          "scope": scope})
            log.info("%r took the %s surface out of scope (%s); stopping there",
                     cand.label, surface.kind, scope)
            return None
        if await self._session_lost():
            self.result.incidents.append({"kind": "surface-unauthenticated",
                                          "action": cand.label})
            return None

        res = await self._scan()
        if res is None:
            self._skip("unscannable-surface")
            return None
        if res.state_id != state_id:
            action = {
                "type": cand.element.get("type") or "click",
                "name": cand.label,
                "role": cand.element.get("role") or "",
                "interaction": "crawler-click",
                "trigger": "safe-crawl",
                "safety": cand.verdict.classification,
                "locator": cand.locator.js,
                "locatorSpec": cand.locator.to_json(),
                "onSurface": {"kind": surface.kind, "openedBy": surface.opened_by_action},
            }
            if self.store.merge_edge(state_id, action, res.state_id):
                self.result.edges_new += 1
            if res.is_new_state:
                self.result.new_states.append(res.state_id)
                log.info("New state discovered inside a %s surface: %s (%s)",
                         surface.kind, res.state_id, res.label)
        return res

    async def _click(self, state_id: str, path: list[dict[str, Any]],
                     cand: _Candidate) -> str:
        """Click one safe candidate, observe what happened, and record it."""
        before_dialogs = len(self._dialog_seen)
        origin_before = self.engine.origin
        sig_before = await stability.visible_signature(self._page)
        self._pending_pages.clear()      # only contexts from THIS action count
        pages_before = self._page_ids()  # so a new context is attributed correctly
        try:
            handle = validator.build(cand.frame, cand.locator)
            if await handle.count() != 1:
                self._skip("vanished-before-click")
                return "skipped"
            await handle.first.click(timeout=self.limits.click_timeout_ms)
            self.result.actions_clicked += 1
            self._clicks_per_element[cand.key] = self._clicks_per_element.get(cand.key, 0) + 1
        except Exception as exc:
            self._skip("click-failed")
            log.debug("Click failed on %s: %s", cand.locator.js, type(exc).__name__)
            return "skipped"

        await stability.wait_stable(self._page, timeout_ms=self.limits.settle_timeout_ms)

        # ---- observe, then classify. No decision is taken from the control's
        # ---- attributes: only from what the browser actually did.
        obs = outcomes.Observation(
            state_before=state_id,
            signature_before=sig_before,
            dialogs_raised=len(self._dialog_seen) - before_dialogs,
            origin_before=origin_before,
            session_lost=await self._session_lost(),
        )
        try:
            obs.origin_after = await self._page.evaluate("() => location.origin")
        except Exception:
            obs.origin_after = origin_before
        await self._await_new_context(pages_before)
        obs.new_surfaces = await self._collect_new_surfaces(pages_before)

        res = await self._scan()
        obs.scannable = res is not None
        if res is not None:
            obs.state_after = res.state_id
            obs.signature_after = await stability.visible_signature(self._page)

        verdict = outcomes.classify(obs)
        self.result.outcome_totals[verdict.primary] = \
            self.result.outcome_totals.get(verdict.primary, 0) + 1

        if outcomes.SESSION_LOST in verdict:
            self.result.aborted = f"session lost after clicking {cand.label!r}"
            self.result.incidents.append({"kind": "session-lost", "action": cand.label})
            log.error("Session lost after clicking %r - aborting the crawl", cand.label)
            return "aborted"

        if outcomes.NATIVE_DIALOG in verdict:
            self._skip("raised-native-dialog")
            log.warning("%r raised a native dialog; poisoned and not retried", cand.label)

        # New browsing contexts: keep the ones that are the application, dispose
        # of the rest - and never let either break the parent crawl.
        child_states = await self._handle_new_surfaces(obs, state_id, cand)

        if outcomes.LEFT_ORIGIN in verdict:
            self.result.incidents.append({"kind": "left-origin", "action": cand.label,
                                          "origin": obs.origin_after})
            log.warning("%r left the origin (%s); returning and poisoning it",
                        cand.label, obs.origin_after)
            await self._replay(path)

        if verdict.poisons:
            self._poison.add((state_id, cand.key))

        if outcomes.UNSCANNABLE in verdict:
            self._skip("unscannable-destination")
            return "skipped"

        dest = res.state_id
        if outcomes.SURFACE_CHANGED in verdict:
            # The DOM moved but no fingerprint input did - an opened menu, an
            # expanded panel, an iframe that filled in. This is NOT inert, so the
            # control must never be pruned; the newly revealed controls are picked
            # up because the re-scan above merged them into this same state.
            self.result.surface_changes += 1
            log.info("%r changed the surface without changing the state", cand.label)

        if dest == state_id and not verdict.productive:
            self._skip("no-state-change")
            # Inert HERE is not proof it is inert everywhere: a "Details" button
            # can do nothing on an empty grid and open a panel elsewhere. Only
            # prune globally once it has done nothing in two distinct states.
            seen_in = self._noop_seen.setdefault(cand.key, set())
            seen_in.add(state_id)
            if len(seen_in) >= 2:
                self._noop_elements.add(cand.key)
        elif dest != state_id:
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
