"""Functional test execution: replay declarative steps against the live app.

Everything here is built on parts that already exist and are already tested:

    locator.validator.build()   turns a locator spec into a Playwright locator
    discovery.scanner           tells us which UI state we are actually in
    discovery.stability         waits for the UI to settle, without sleeps
    navigation.graph            supplies the clicks that reach a state
    store.uimap                 supplies the validated locator for a control

The runner adds only the things that did not exist: performing actions,
asserting outcomes, and failing closed.

Fail-closed rules for a destructive step (create / update / delete):
  1. the step must declare `destructive: true` - nothing is destructive by accident;
  2. the current UI state must equal the step's declared `state`;
  3. the target must resolve to exactly ONE element;
  4. that element must be visible and enabled.
Any mismatch aborts the step and the test, before the click. Safe Crawl is not
involved and is not modified: it remains read-only.
"""
from __future__ import annotations

import time
from pathlib import Path
from dataclasses import replace
from typing import Any

from .. import paths
from ..discovery import scanner, stability
from ..locator import validator
from ..locator.generator import Locator
from ..logging_setup import get
from ..navigation import graph as navgraph
from .data import LeftoverReport, TestData, new_run_id
from .evidence import EvidenceCollector
from .results import ERROR, FAILED, PASSED, SKIPPED, StepResult, SuiteResult, TestResult
from .steps import ASSERT, CLICK, FILL, NAVIGATE, SELECT, FunctionalTest, Step, Suite, Target

log = get("functional")


class StepFailure(Exception):
    """A step did not do what the test said it should."""

    def __init__(self, message: str, expected: Any = None, actual: Any = None) -> None:
        super().__init__(message)
        self.expected = expected
        self.actual = actual


class FunctionalRunner:
    def __init__(self, engine: Any, store: Any, run_id: str | None = None,
                 evidence_root: Path | None = None) -> None:
        self.engine = engine
        self.store = store
        self.run_id = run_id or new_run_id()
        self.evidence = EvidenceCollector(evidence_root or paths.EVIDENCE_DIR, self.run_id)
        self.leftovers = LeftoverReport(paths.LEFTOVERS_FILE)
        self._state: str | None = None          # last known UI state id

    # ------------------------------------------------------------- helpers
    @property
    def page(self) -> Any:
        return self.engine.page

    async def _settle(self) -> None:
        await stability.wait_stable(self.page, timeout_ms=4000)

    async def _current_state(self, refresh: bool = True) -> str:
        """Which discovered state are we in? Uses the existing scanner."""
        if not refresh and self._state:
            return self._state
        res = await scanner.scan_page(self.page, self.store, origin=self.engine.origin,
                                      validate_limit=self.engine.validate_limit,
                                      validate_new_only=True)
        self._state = res.state_id if res else ""
        return self._state or ""

    # ------------------------------------------------------ target resolution
    def _spec_for(self, target: Target) -> Locator | None:
        """Turn a Target into a locator spec, preferring what discovery validated."""
        if target.locator:
            args = target.locator.get("args") or target.locator
            strategy = target.locator.get("strategy") or "css"
            return Locator(strategy=strategy, tier=1, js=target.locator.get("js", ""),
                           python="", args=dict(args))

        if target.key:
            states = self.store.data.get("states") or {}
            candidates = [target.state] if target.state else list(states)
            for sid in candidates:
                el = ((states.get(sid) or {}).get("elements") or {}).get(target.key)
                if el and el.get("locator", {}).get("args"):
                    loc = el["locator"]
                    return Locator(strategy=loc.get("strategy", "css"), tier=loc.get("tier", 1),
                                   js=loc.get("js", ""), python=loc.get("python", ""),
                                   args=dict(loc["args"]))
            return None

        if target.testid:
            return Locator("testid", 1, f"getByTestId('{target.testid}')",
                           f'get_by_test_id("{target.testid}")',
                           {"attribute": "data-testid", "value": target.testid})
        if target.role:
            args: dict[str, Any] = {"role": target.role, "exact": target.exact}
            if target.name:
                args["name"] = target.name
            return Locator("role", 2, f"getByRole('{target.role}')", "", args)
        if target.text:
            return Locator("text", 5, f"getByText('{target.text}')", "",
                           {"text": target.text, "exact": target.exact})
        return None

    def _resolve(self, target: Target) -> tuple[Any, Locator]:
        """Build a real Playwright locator. `within` scopes it (grid rows)."""
        spec = self._spec_for(target)
        if spec is None:
            raise StepFailure(f"target cannot be resolved: {target.describe()}")
        if target.within is not None:
            parent, _pspec = self._resolve(target.within)
            handle = validator.build(parent, spec)
        else:
            handle = validator.build(self.page.main_frame, spec)
        if target.nth is not None:
            handle = handle.nth(target.nth)
        return handle, spec

    async def _require_single(self, target: Target, step: Step) -> tuple[Any, Locator, int]:
        handle, spec = self._resolve(target)
        count = await handle.count()
        if count != 1:
            if step.destructive:
                raise StepFailure(
                    f"refusing a destructive action: target matched {count} elements, expected "
                    f"exactly 1 ({target.describe()})", expected="exactly 1 match", actual=count)
            if count == 0:
                raise StepFailure(f"target not found: {target.describe()}",
                                  expected="1 match", actual=0)
        return handle, spec, count

    # --------------------------------------------------------------- actions
    async def _do_navigate(self, step: Step, result: StepResult) -> None:
        target_state = step.to_state or (step.target.state if step.target else None)
        if not target_state:
            raise StepFailure("navigate step has no target state")
        current = await self._current_state()
        result.state_before = current
        if current == target_state:
            result.actual = current
            return
        path = navgraph.shortest_path(self.store, target_state, from_state=current)
        if path is None:
            # Try from the application root - the graph may only know that route.
            if not await self._goto_root():
                raise StepFailure(f"cannot reach state {target_state!r}: no route from root")
            current = await self._current_state()
            path = navgraph.shortest_path(self.store, target_state, from_state=current)
        if path is None:
            raise StepFailure(
                f"state {target_state!r} is not reachable in the learned navigation graph. "
                f"Run discovery (training or Safe Crawl) so the route is known.",
                expected=target_state, actual=current)
        for hop in path:
            spec = hop.get("locatorSpec")
            if not spec or not spec.get("args"):
                raise StepFailure(f"navigation step {hop['action']!r} has no validated locator")
            loc = Locator(strategy=spec.get("strategy", "css"), tier=spec.get("tier", 1),
                          js=spec.get("js", ""), python="", args=dict(spec["args"]))
            handle = validator.build(self.page.main_frame, loc)
            if await handle.count() != 1:
                raise StepFailure(
                    f"navigation locator for {hop['action']!r} no longer resolves uniquely",
                    expected="1 match", actual=await handle.count())
            await handle.first.click(timeout=step.timeout_ms)
            await self._settle()
        reached = await self._current_state()
        result.state_after = reached
        result.actual = reached
        if reached != target_state:
            raise StepFailure(f"navigation landed in {reached!r}", expected=target_state,
                              actual=reached)

    async def _goto_root(self) -> bool:
        try:
            await self.page.goto(self.engine.base_url, wait_until="domcontentloaded",
                                 timeout=30000)
            await self._settle()
            self._state = None
            return True
        except Exception:
            return False

    async def _do_click(self, step: Step, result: StepResult) -> None:
        handle, spec, _ = await self._require_single(step.target, step)
        result.locator = spec.js
        if step.destructive:
            if not await handle.first.is_visible(timeout=2000):
                raise StepFailure("refusing a destructive action: target is not visible",
                                  expected="visible", actual="hidden")
            if not await handle.first.is_enabled(timeout=2000):
                raise StepFailure("refusing a destructive action: target is disabled",
                                  expected="enabled", actual="disabled")
            log.warning("DESTRUCTIVE step authorised by test: %s", step.describe())
        try:
            await handle.first.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass                              # not scrollable, or already visible
        await handle.first.click(timeout=step.timeout_ms)
        await self._settle()

    async def _do_fill(self, step: Step, result: StepResult, value: str) -> None:
        handle, spec, _ = await self._require_single(step.target, step)
        result.locator = spec.js
        await handle.first.fill(value, timeout=step.timeout_ms)
        result.actual = "filled"

    async def _do_select(self, step: Step, result: StepResult, value: str) -> None:
        """Choose an option, whether or not the control is a real <select>.

        A component framework usually renders a `role=combobox` whose
        `role=listbox` is portaled to <body> when opened, so the options are not
        children of the control and do not exist at all until it is clicked.
        Both shapes are handled; the wrong one is never guessed at.
        """
        handle, spec, _ = await self._require_single(step.target, step)
        result.locator = spec.js
        try:
            tag = (await handle.first.evaluate("el => el.tagName.toLowerCase()")) or ""
        except Exception:
            tag = ""

        if tag == "select":
            try:
                chosen = await handle.first.select_option(label=value, timeout=step.timeout_ms)
            except Exception:
                chosen = await handle.first.select_option(value=value, timeout=step.timeout_ms)
            if not chosen:
                raise StepFailure(f"option {value!r} could not be selected", expected=value,
                                  actual="no option matched")
            await self._settle()
            result.actual = chosen
            return

        # Custom combobox: open it, then find the option anywhere on the page -
        # the overlay is typically NOT inside the control.
        await handle.first.click(timeout=step.timeout_ms)
        await self._settle()
        option = self.page.get_by_role("option", name=value, exact=True)
        found = await option.count()
        if found == 0:
            option = self.page.get_by_role("option", name=value, exact=False)
            found = await option.count()
        if found == 0:
            await self._dismiss_overlay()
            raise StepFailure(
                f"option {value!r} did not appear after opening the control",
                expected=value, actual="no option in the listbox")
        if found > 1:
            await self._dismiss_overlay()
            raise StepFailure(
                f"option {value!r} is ambiguous ({found} matches) - refusing to guess",
                expected="exactly 1 option", actual=found)
        await option.first.click(timeout=step.timeout_ms)
        await self._settle()

        # Confirm the control actually took the value, rather than trusting the click.
        shown = ""
        try:
            shown = " ".join(((await handle.first.text_content()) or "").split())
        except Exception:
            pass
        result.actual = shown[:80] or "(no text)"
        if value not in shown:
            raise StepFailure("the control does not show the selected option",
                              expected=value, actual=result.actual)

    async def _dismiss_overlay(self) -> None:
        """Close a stray dropdown so a failure does not block the next step."""
        try:
            await self.page.keyboard.press("Escape")
            await self._settle()
        except Exception:
            pass

    async def _do_assert(self, step: Step, result: StepResult) -> None:
        expect = step.expect
        if expect is None:
            raise StepFailure("assert step has no expectation")

        if expect.state is not None:
            actual = await self._current_state()
            result.expected, result.actual = expect.state, actual
            if actual != expect.state:
                raise StepFailure(f"wrong UI state", expected=expect.state, actual=actual)
            return

        handle, spec = self._resolve(step.target) if step.target else (None, None)
        if handle is None:
            raise StepFailure("assert step has no target")
        result.locator = spec.js
        count = await handle.count()

        if expect.count is not None:
            result.expected, result.actual = expect.count, count
            if count != expect.count:
                raise StepFailure("wrong number of matches", expected=expect.count, actual=count)
            return

        if expect.hidden:
            visible = count > 0 and await handle.first.is_visible(timeout=1500)
            result.expected, result.actual = "hidden", "visible" if visible else "hidden"
            if visible:
                raise StepFailure("element is still visible", expected="hidden", actual="visible")
            return

        if expect.visible:
            if count == 0:
                raise StepFailure("element not found", expected="visible", actual="no match")
            visible = await handle.first.is_visible(timeout=step.timeout_ms)
            result.expected, result.actual = "visible", "visible" if visible else "hidden"
            if not visible:
                raise StepFailure("element is not visible", expected="visible", actual="hidden")
            return

        if expect.enabled is not None:
            enabled = count > 0 and await handle.first.is_enabled(timeout=1500)
            result.expected, result.actual = expect.enabled, enabled
            if enabled != expect.enabled:
                raise StepFailure("wrong enabled state", expected=expect.enabled, actual=enabled)
            return

        if expect.text_contains is not None:
            if count == 0:
                raise StepFailure("element not found", expected=expect.text_contains,
                                  actual="no match")
            text = (await handle.first.text_content(timeout=step.timeout_ms)) or ""
            text = " ".join(text.split())
            result.expected, result.actual = expect.text_contains, text[:200]
            if expect.text_contains not in text:
                raise StepFailure("text does not contain the expected value",
                                  expected=expect.text_contains, actual=text[:200])
            return

        raise StepFailure("assert step has no recognised expectation")

    # ----------------------------------------------------------------- step
    async def _run_step(self, step: Step, index: int, data: TestData) -> StepResult:
        # Expand {RUN_ID}/{record} in both the value and the target, so a test can
        # refer to the record it just created.
        target = step.target.substituted(data.substitute) if step.target else None
        step = replace(step, target=target)
        result = StepResult(index=index, action=step.action, description=step.describe(),
                            destructive=step.destructive,
                            target=target.describe() if target else "")
        t0 = time.perf_counter()
        try:
            # Guard: the declared state must be the real one. Mandatory before a
            # destructive step, advisory otherwise.
            if step.state:
                actual = await self._current_state()
                result.state_before = actual
                if actual != step.state:
                    raise StepFailure(
                        f"state guard failed before a {'destructive ' if step.destructive else ''}"
                        f"step", expected=step.state, actual=actual)

            value = data.substitute(step.value)
            if step.action == NAVIGATE:
                await self._do_navigate(step, result)
            elif step.action == CLICK:
                await self._do_click(step, result)
            elif step.action == FILL:
                if value is None:
                    raise StepFailure("fill step has no value")
                await self._do_fill(step, result, value)
            elif step.action == SELECT:
                if value is None:
                    raise StepFailure("select step has no value")
                await self._do_select(step, result, value)
            elif step.action == ASSERT:
                await self._do_assert(step, result)
            else:
                raise StepFailure(f"unsupported action {step.action!r}")

            if step.creates:
                data.note_created(data.substitute(step.creates) or "")
            if step.removes:
                data.note_removed(data.substitute(step.removes) or "")
            result.status = PASSED
        except StepFailure as exc:
            missing = "not found" in str(exc) or "no match" in str(exc)
            result.status = SKIPPED if (step.optional and missing) else FAILED
            result.error = str(exc)
            if exc.expected is not None:
                result.expected = exc.expected
            if exc.actual is not None:
                result.actual = exc.actual
        except Exception as exc:                     # a Playwright/timeout error
            result.status = ERROR
            result.error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:300]}"
        result.ms = int((time.perf_counter() - t0) * 1000)
        return result

    # ----------------------------------------------------------------- test
    async def run_test(self, test: FunctionalTest) -> TestResult:
        data = TestData(run_id=self.run_id, test_name=test.name)
        out = TestResult(name=test.name, level=test.level)
        t0 = time.perf_counter()
        marker = self.evidence.events.mark()
        await self.evidence.start_trace(self.engine.context, test.name)
        log.info("TEST %s (%s) - %d step(s), %d destructive",
                 test.name, test.level, len(test.steps), len(test.destructive_steps))

        failed_at: StepResult | None = None
        for i, step in enumerate(test.steps, 1):
            res = await self._run_step(step, i, data)
            out.steps.append(res)
            log.info("  %-4s step %d/%d %s%s", res.status, i, len(test.steps), res.description,
                     f" -> {res.error}" if res.error else "")
            if res.status != PASSED:
                failed_at = res
                break

        # Cleanup ALWAYS runs, even after a failure: residue is worse than a
        # red test. Cleanup failures do not overwrite the original verdict.
        for j, step in enumerate(test.cleanup, 1):
            res = await self._run_step(step, j, data)
            out.cleanup_steps.append(res)
            log.info("  %-4s cleanup %d/%d %s%s", res.status, j, len(test.cleanup),
                     res.description, f" -> {res.error}" if res.error else "")

        out.created = list(data.created)
        out.leftovers = data.leftovers
        out.ms = int((time.perf_counter() - t0) * 1000)

        if failed_at is not None:
            out.status = failed_at.status
            out.failed_step = failed_at.index
            out.failure = failed_at.error
            out.evidence = await self._collect_evidence(test, failed_at, marker)
        else:
            out.status = PASSED
            await self.evidence.stop_trace(self.engine.context, False,
                                           self.evidence.test_dir(test.name))
        if out.leftovers:
            self.leftovers.add(self.run_id, test.name, out.leftovers,
                               "cleanup did not remove them")
        log.info("TEST %s: %s in %d ms%s", test.name, out.status, out.ms,
                 f" (leftovers: {', '.join(out.leftovers)})" if out.leftovers else "")
        return out

    async def _collect_evidence(self, test: FunctionalTest, failed: StepResult,
                                marker: dict[str, int]) -> dict[str, Any]:
        test_dir = self.evidence.test_dir(test.name)
        shot = await self.evidence.screenshot(self.page, test.name,
                                              f"step-{failed.index}-{failed.action}")
        trace = await self.evidence.stop_trace(self.engine.context, True, test_dir)
        events = self.evidence.events.since(marker)
        page_state = await self.evidence.page_state(self.page)
        bundle: dict[str, Any] = {
            "failedStep": failed.index,
            "action": failed.action,
            "step": failed.description,
            "target": failed.target,
            "locator": failed.locator,
            "expected": failed.expected,
            "actual": failed.actual,
            "error": failed.error,
            "stateExpected": failed.state_before or None,
            "pageAtFailure": page_state,
            "console": events["console"][-20:],
            "pageErrors": events["pageErrors"][-10:],
            "networkFailures": events["networkFailures"][-20:],
        }
        if shot:
            bundle["screenshot"] = paths.rel(shot)
        if trace:
            bundle["trace"] = paths.rel(trace)
        log.error("Evidence for %s step %d: %s", test.name, failed.index,
                  ", ".join(k for k in ("screenshot", "trace") if bundle.get(k)) or "logs only")
        return {k: v for k, v in bundle.items() if v not in (None, [], {}, "")}

    async def _reset_ui(self) -> None:
        """Leave the app usable for the next test.

        A test that fails with a modal open would otherwise poison every later
        test in the suite: everything behind a modal is inert, so the next click
        just times out. Escape first; if the surface is still there, go back to
        the start URL - a known state beats a blocked one.
        """
        if self.page is None or self.page.is_closed():
            return
        probe = """() => {
            const vis = (e) => {
              const r = e.getBoundingClientRect();
              const s = getComputedStyle(e);
              return r.width > 1 && r.height > 1 && s.display !== 'none'
                     && s.visibility !== 'hidden';
            };
            return Array.from(document.querySelectorAll(
              'dialog[open],[role=dialog],[role=alertdialog],[aria-modal="true"],[role=listbox]'
            )).filter(vis).length;
        }"""
        try:
            stuck = await self.page.evaluate(probe)
        except Exception:
            return
        if not stuck:
            return
        log.info("Resetting the UI between tests: %d modal/overlay surface(s) left open", stuck)
        try:
            await self.page.keyboard.press("Escape")
            await self._settle()
            stuck = await self.page.evaluate(probe)
        except Exception:
            stuck = 1
        if stuck and self.engine.base_url:
            log.info("Escape did not clear it; returning to the start URL")
            await self._goto_root()
        self._state = None

    # ---------------------------------------------------------------- suite
    async def run_suite(self, suite: Suite) -> SuiteResult:
        out = SuiteResult(suite=suite.name, run_id=self.run_id,
                          environment=self.engine.origin)
        t0 = time.perf_counter()
        log.info("Functional suite %r: %d test(s), run id %s", suite.name, len(suite.tests),
                 self.run_id)
        self.evidence.attach(self.page)
        try:
            for test in suite.tests:
                if self.page is None or self.page.is_closed():
                    out.aborted = "the browser page was closed"
                    break
                out.tests.append(await self.run_test(test))
                # Isolation: one test's leftover modal must not fail the next.
                await self._reset_ui()
        finally:
            await self.evidence.stop_all(self.engine.context)
            self.evidence.detach()
        out.ms = int((time.perf_counter() - t0) * 1000)
        self.leftovers.write()
        log.info("Functional suite %r: %s", suite.name, out.summary_line())
        return out
