"""Browser controller / discovery engine.

Threading model
---------------
Playwright's **async** API runs on its own asyncio loop in a dedicated thread.
That matters: with the sync API, `expose_binding` callbacks only fire while a
Playwright call is in flight, which would force a polling loop during training.
On the async loop, browser events dispatch the moment they arrive - no polling,
no arbitrary sleeps (spec 28).

The GUI never touches Playwright objects. It submits named operations and reads
events off a plain `queue.Queue`.
"""
from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from typing import Any, Callable

from .. import paths
from ..auth import login as auth_login
from ..discovery import scanner
from ..logging_setup import get, register_secret
from ..navigation import graph as navgraph
from ..reporting import html_report, junit
from ..security.session_store import SessionStore
from ..store.uimap import UIMapStore
from ..training.trainer import Trainer
from .injected import CORE_JS, WANT_OBSERVE_JS

log = get("browser")

BINDING = "__p1uidEmit"


class Engine:
    """Owns the browser, the UI map and the training session."""

    def __init__(self, events: "queue.Queue[dict[str, Any]]", *,
                 headless: bool = False, remember_session: bool = False,
                 validate_limit: int = 500, login_wait_s: float = 20.0,
                 generate_tests: bool = False) -> None:
        self.events = events
        self.headless = headless
        self.remember_session = remember_session
        self.validate_limit = validate_limit
        self.login_wait_s = login_wait_s
        self.generate_tests = generate_tests

        self.loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

        self.store = UIMapStore().load()
        self.sessions = SessionStore()
        self.trainer: Trainer | None = None
        self.origin = ""
        self.base_url = ""
        self.authenticated = False
        self._busy = False
        self._observe_script_added = False
        self.crawl_active = False
        self._cancel_manual = False

    # ------------------------------------------------------------ plumbing
    def emit(self, **payload: Any) -> None:
        try:
            self.events.put_nowait(payload)
        except Exception:
            pass

    def start(self) -> None:
        if self._thread:
            return
        self._thread = threading.Thread(target=self._run_loop, name="p1uid-engine", daemon=True)
        self._thread.start()
        self._ready.wait(10)

    def _run_loop(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._ready.set()
        try:
            self.loop.run_forever()
        finally:
            try:
                self.loop.close()
            except Exception:
                pass

    def submit(self, coro_factory: Callable[[], Any], op: str = "op") -> None:
        """Schedule an operation on the engine loop; result arrives as an event."""
        if not self.loop:
            self.emit(type="error", op=op, msg="engine is not running")
            return

        # A manual-login wait is a wait, not an operation: it must not lock the
        # buttons out for its whole (up to ten minute) duration.
        exclusive = op not in ("stop_training", "shutdown", "manual_login")

        async def runner() -> None:
            if exclusive and self._busy:
                self.emit(type="error", op=op, msg="another operation is still running")
                return
            if exclusive:
                self._busy = True
            try:
                await coro_factory()
            except Exception as exc:                       # never kill the loop
                log.exception("Operation %s failed", op)
                self.emit(type="error", op=op, msg=f"{type(exc).__name__}: {exc}")
            finally:
                if exclusive:
                    self._busy = False
                self.emit(type="idle", op=op)

        asyncio.run_coroutine_threadsafe(runner(), self.loop)

    def call(self, coro_factory: Callable[[], Any], timeout: float = 60) -> Any:
        """Run an operation and block for its result (CLI use)."""
        fut = asyncio.run_coroutine_threadsafe(coro_factory(), self.loop)
        return fut.result(timeout)

    # ------------------------------------------------------------- browser
    async def _teardown(self) -> None:
        """Drop a dead browser so the next operation can start a fresh one."""
        self.trainer = None
        self.crawl_active = False
        self._observe_script_added = False
        for attr in ("context", "browser"):
            obj = getattr(self, attr, None)
            if obj is not None:
                try:
                    await obj.close()
                except Exception:
                    pass
                setattr(self, attr, None)
        if self.playwright is not None:
            try:
                await self.playwright.stop()
            except Exception:
                pass
            self.playwright = None
        self.page = None

    async def _revive(self) -> bool:
        """True if the existing browser is still usable, opening a tab if needed.

        A user closing the browser window is normal, not an error - but every
        later call would raise TargetClosedError unless we notice and rebuild.
        """
        if self.context is None:
            return False
        if self.browser is not None and not self.browser.is_connected():
            log.warning("The browser had been closed; starting a new one")
            await self._teardown()
            self.emit(type="status", browser=False)
            return False
        if self.page is None or self.page.is_closed():
            try:
                self.page = await self.context.new_page()
                self.page.on("close", lambda _p: self.emit(type="page-closed"))
                if self.base_url:
                    # Land back on the application rather than about:blank, so the
                    # next Scan has something real to look at.
                    try:
                        await self.page.goto(self.base_url, wait_until="domcontentloaded",
                                             timeout=30000)
                    except Exception:
                        pass
                log.info("The page had been closed; opened a fresh tab%s",
                         f" at {self.base_url}" if self.base_url else "")
                return True
            except Exception:
                log.warning("The browser context is no longer usable; restarting the browser")
                await self._teardown()
                self.emit(type="status", browser=False)
                return False
        return True

    async def ensure_browser(self) -> None:
        if self.context is not None and await self._revive():
            return
        # PLAYWRIGHT_BROWSERS_PATH must be set before Playwright is imported so
        # the bundled browser folder is the one that gets used.
        where = paths.configure_browser_env()
        from playwright.async_api import async_playwright

        warning = paths.browser_path_warning()
        if warning:
            log.warning("%s", warning)
        log.info("Starting Chromium (%s)", where)
        t0 = time.perf_counter()
        self.playwright = await async_playwright().start()
        launch_kwargs: dict[str, Any] = {
            "headless": self.headless,
            "args": ["--disable-blink-features=AutomationControlled", "--no-first-run",
                     "--no-default-browser-check"],
        }
        if self.headless:
            # channel="chromium" runs headless out of the full Chromium build
            # (new headless mode). Without it Playwright wants the separate
            # 270 MB chromium_headless_shell download, which the portable
            # package deliberately does not ship.
            launch_kwargs["channel"] = "chromium"
        self.browser = await self.playwright.chromium.launch(**launch_kwargs)
        storage = self.sessions.load() if self.remember_session else None
        self.context = await self.browser.new_context(
            no_viewport=not self.headless,
            storage_state=storage,
            ignore_https_errors=True,
            # The tool never wants a file: refusing at the context level means an
            # accidental download link cannot write anything to disk.
            accept_downloads=False,
        )
        await self.context.expose_binding(BINDING, self._on_binding)
        await self.context.add_init_script(script=CORE_JS)
        self.page = await self.context.new_page()
        self.page.on("close", lambda _p: self.emit(type="page-closed"))
        # Registered only now: otherwise our own first tab fires the popup
        # handler and logs a confusing "new browser tab detected".
        self.context.on("page", self._on_new_page)
        log.info("Browser started in %.1f s%s", time.perf_counter() - t0,
                 " (reusing saved session)" if storage else "")
        self.emit(type="status", browser=True)

    def _on_new_page(self, page: Any) -> None:
        if self.crawl_active:
            # During an autonomous crawl a popup is an incident, not a place to
            # go: the crawler's own handler closes it. Never retarget here.
            self.emit(type="log-info", msg="Popup appeared during the crawl; it will be closed")
            return
        # A popup / new tab becomes the active page for observation.
        self.page = page
        self.emit(type="log-info", msg="New browser tab detected; observing it")

    async def _on_binding(self, source: dict[str, Any], payload: dict[str, Any]) -> None:
        """Receives observation events from the injected core."""
        if self.trainer is None:
            return
        try:
            page = source.get("page")
            if page is not None:
                self.page = page
            await self.trainer.on_event(payload, page)
        except Exception:
            log.debug("binding handler failed", exc_info=True)

    async def open_url(self, url: str) -> None:
        await self.ensure_browser()
        self.base_url = url
        log.info("Opening URL...")
        await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self.origin = await self.page.evaluate("() => location.origin")
        self.store.note_environment(self.origin)
        log.info("Loaded %s", self.origin)
        self.emit(type="status", url=self.page.url, origin=self.origin)

    # ---------------------------------------------------------------- auth
    async def op_login(self, url: str, username: str, password: str) -> None:
        register_secret(password)
        self._cancel_manual = True          # supersede any manual-login wait
        await self.open_url(url)

        # The form may render after load, or sit inside an identity-provider
        # iframe, so look across every frame for a while before giving up.
        frame, fields = await auth_login.find_login_form(self.page, timeout_s=self.login_wait_s)

        if frame is None and self.remember_session and self.sessions.exists():
            log.info("No login form present - the saved session appears to be still valid")
            self.authenticated = True
            self.emit(type="status", auth="Connected (saved session)")
            return

        if frame is None:
            # A landing page may hide the form behind a single "Sign in" entry point.
            entry = await auth_login.click_login_entry(self.page)
            if entry:
                log.info("No form yet; clicked the %r entry point and waiting for the form", entry)
                frame, fields = await auth_login.find_login_form(self.page, timeout_s=self.login_wait_s)

        if frame is None:
            log.warning("No login form found after %.0fs. Page structure follows - if this looks "
                        "like the app itself you are already authenticated; otherwise use Manual "
                        "Login.", self.login_wait_s)
            log.warning("Page diagnostics:\n%s", await auth_login.describe_page(self.page))
            self.emit(type="status", auth="No login form found - use Manual Login")
            return

        plan = auth_login.analyse(fields)
        log.info("Login form analysis: confidence=%s (%s)", plan.confidence, "; ".join(plan.reasons))
        if not plan.usable:
            log.error("Automatic login refused - confidence too low. Use Manual Login.")
            self.emit(type="status", auth="Automatic login not possible - use Manual Login")
            return

        outcome = await auth_login.perform_login(frame, self.page, username, password, plan)
        if not outcome.ok:
            log.error("Authentication failed: %s%s", outcome.detail,
                      f" | page message: {outcome.errors[0]}" if outcome.errors else "")
            self.emit(type="status", auth="Authentication failed")
            return

        self.authenticated = True
        log.info("Authentication successful")
        await self._maybe_save_session()
        self.emit(type="status", auth="Connected")

    async def op_manual_login(self, url: str, timeout_s: int = 600) -> None:
        await self.open_url(url)
        self._cancel_manual = False
        self.emit(type="status", auth="Waiting for the sign-in form...")

        # A password field must be SEEN before its absence can mean "signed in".
        # Without this, a slow SPA that has not yet rendered its login form
        # reports success one second after the page loads.
        frame, _fields = await auth_login.find_login_form(self.page, timeout_s=self.login_wait_s)
        if frame is None:
            if await auth_login.looks_authenticated(self.page):
                self.authenticated = True
                log.info("No sign-in form appeared and the application is rendering - "
                         "treating this session as already authenticated")
                await self._maybe_save_session()
                self.emit(type="status", auth="Connected (existing session)")
                return
            log.warning("No sign-in form appeared within %.0f s. If sign-in happens on another "
                        "site or needs longer, complete it in the browser window and press "
                        "Manual Login again.", self.login_wait_s)
            log.warning("Page diagnostics:\n%s", await auth_login.describe_page(self.page))
            self.emit(type="status", auth="No sign-in form detected")
            return

        log.info("Sign-in form is on screen - complete it in the browser window "
                 "(waiting up to %d s)", timeout_s)
        self.emit(type="status", auth="Waiting for you to sign in...")
        ok = await auth_login.wait_until_no_password(
            self.page, timeout_s, should_cancel=lambda: self._cancel_manual)

        if self.page is None or self.page.is_closed():
            log.warning("The browser page was closed before sign-in completed")
            self.emit(type="status", auth="Browser closed before sign-in")
            return
        if not ok:
            if self._cancel_manual:
                log.info("Manual login wait cancelled")
                self.emit(type="status", auth="Manual login cancelled")
            else:
                log.warning("Manual login not detected within the time limit; the browser stays open")
                self.emit(type="status", auth="Manual login not confirmed")
            return
        self.authenticated = True
        log.info("Authentication successful (manual)")
        await self._maybe_save_session()
        self.emit(type="status", auth="Connected (manual)")

    async def _maybe_save_session(self) -> None:
        if not self.remember_session:
            return
        try:
            state = await self.context.storage_state()
        except Exception as exc:
            log.warning("Could not capture session state: %s", type(exc).__name__)
            return
        self.sessions.save(state)          # DPAPI-encrypted; password never stored

    # ---------------------------------------------------------------- scan
    async def op_scan(self) -> None:
        await self.ensure_browser()
        if self.page is None or self.page.is_closed():
            self.emit(type="error", op="scan", msg="no open page to scan")
            return
        # An explicit user scan waits for the page to settle first; training
        # scans do not, because the trainer is already event-driven.
        res = await scanner.scan_page(self.page, self.store, origin=self.origin,
                                      validate_limit=self.validate_limit, stabilise=True)
        if res is None:
            self.emit(type="error", op="scan", msg="nothing analysable on this page")
            return
        self.store.save()
        self.write_outputs()
        self.emit(type="scan", result=res.__dict__, counts=self.store.counts())

    # ------------------------------------------------------------ training
    async def op_start_training(self) -> None:
        await self.ensure_browser()
        if self.trainer is not None:
            return
        self.trainer = Trainer(engine=self, store=self.store)
        if not self._observe_script_added:
            # Init scripts cannot be removed, so add it once per browser session
            # however many times training is started and stopped.
            await self.context.add_init_script(script=WANT_OBSERVE_JS)
            self._observe_script_added = True
        started = 0
        for page in self.context.pages:
            for frame in page.frames:
                if await scanner.ensure_core(frame):
                    try:
                        await frame.evaluate("() => window.__p1uidCore.startObserving()")
                        started += 1
                    except Exception:
                        pass
        await self.trainer.start(self.page)
        log.info("Training started (observing %d frame(s)) - navigate PhenomeOne normally", started)
        self.emit(type="training", active=True)

    async def op_stop_training(self) -> None:
        if self.trainer is None:
            return
        summary = await self.trainer.stop()
        for page in self.context.pages if self.context else []:
            for frame in page.frames:
                try:
                    await frame.evaluate("() => window.__p1uidCore && window.__p1uidCore.stopObserving()")
                except Exception:
                    pass
        self.trainer = None
        log.info("Training stopped. Saving map...")
        self.store.save()
        self.write_outputs(training_summary=summary)
        log.info("Training summary: %d UI states, %d navigation paths, %d elements",
                 summary.get("statesSeen", 0), summary.get("navigationPaths", 0),
                 summary.get("elementsSeen", 0))
        self.emit(type="training", active=False, summary=summary, counts=self.store.counts())

    # --------------------------------------------------------- workflows
    async def op_begin_workflow(self, name: str) -> None:
        if self.trainer is None:
            self.emit(type="error", op="workflow", msg="start training before recording a workflow")
            return
        self.trainer.begin_workflow(name)
        self.emit(type="workflow", active=True, name=name)

    async def op_end_workflow(self) -> None:
        if self.trainer is None:
            return
        entry = self.trainer.end_workflow()
        self.emit(type="workflow", active=False, workflow=entry)

    # -------------------------------------------------------- safe crawl
    async def op_crawl(self, limits: Any = None) -> None:
        """Autonomous, read-only exploration (Safe Crawl)."""
        from ..crawler.bfs import CrawlLimits, SafeCrawler

        await self.ensure_browser()
        if self.trainer is not None:
            self.emit(type="error", op="crawl", msg="stop training before crawling")
            return
        if self.page is None or self.page.is_closed():
            self.emit(type="error", op="crawl", msg="no open page to crawl from")
            return
        if not self.base_url:
            self.base_url = self.page.url

        crawler = SafeCrawler(self, self.store, limits or CrawlLimits())
        self.crawl_active = True
        self.emit(type="crawl", active=True)
        try:
            result = await crawler.run()
        finally:
            self.crawl_active = False
        self.store.save()
        _write_json(paths.CRAWL_SUMMARY_FILE, result.to_json())
        self.write_outputs()
        self.emit(type="crawl", active=False, summary=result.to_json(),
                  counts=self.store.counts())

    # --------------------------------------------------- functional testing
    async def op_run_functional(self, suite: Any, run_id: str | None = None) -> Any:
        """Execute a declarative functional suite against the live application.

        Discovery must have run first: targets and navigation come from the
        existing UI map and navigation graph. Safe Crawl is not involved.
        """
        from ..functional.runner import FunctionalRunner
        from ..reporting import junit_functional

        await self.ensure_browser()
        if self.trainer is not None:
            self.emit(type="error", op="functional", msg="stop training before running tests")
            return None
        if self.page is None or self.page.is_closed():
            self.emit(type="error", op="functional", msg="no open page")
            return None
        if not self.store.data.get("states"):
            self.emit(type="error", op="functional",
                      msg="the UI map is empty - run discovery before functional tests")
            return None

        runner = FunctionalRunner(self, self.store, run_id=run_id)
        self.emit(type="functional", active=True, suite=suite.name, tests=len(suite.tests))
        result = await runner.run_suite(suite)
        result.write(paths.FUNCTIONAL_RESULTS_FILE)
        junit_functional.write(result, paths.FUNCTIONAL_JUNIT_FILE)
        # The UI map may have gained states while navigating; persist it.
        self.store.save()
        self.emit(type="functional", active=False, summary=result.to_json()["totals"],
                  ok=result.ok, leftovers=len(result.leftovers))
        return result

    # -------------------------------------------------------------- output
    def write_outputs(self, training_summary: dict[str, Any] | None = None) -> None:
        paths.ensure_dirs()
        counts = self.store.counts()
        app = {
            "application": "PhenomeOne",
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "tool": {"name": paths.APP_NAME, "schemaVersion": self.store.data["schemaVersion"]},
            "environments": self.store.data["application"].get("environments", []),
            "totals": {k: v for k, v in counts.items() if k != "weak"},
            "states": [
                {"id": sid, "label": st.get("label"), "route": st.get("route"),
                 "elements": len(st.get("elements", {})), "timesSeen": st.get("timesSeen")}
                for sid, st in sorted(self.store.data["states"].items())
            ],
        }
        _write_json(paths.APPLICATION_FILE, app)
        _write_json(paths.NAV_GRAPH_FILE, navgraph.build(self.store))
        if training_summary is not None:
            _write_json(paths.TRAINING_SUMMARY_FILE, training_summary)
        html_report.write(self.store, paths.REPORT_FILE,
                          environments=self.store.data["application"].get("environments", []),
                          training_summary=training_summary)
        junit.write(self.store, paths.JUNIT_FILE)
        if self.generate_tests:
            from .. import codegen
            codegen.generate(self.store.data, paths.GENERATED_DIR,
                             nav_graph=navgraph.build(self.store),
                             source=paths.rel(paths.UI_MAP_FILE))
        log.info("Outputs written to %s and %s", paths.rel(paths.OUTPUT_DIR), paths.rel(paths.REPORTS_DIR))

    # ------------------------------------------------------------ shutdown
    async def op_shutdown(self) -> None:
        if self.trainer is not None:
            await self.op_stop_training()
        for closer in ("context", "browser"):
            obj = getattr(self, closer, None)
            if obj is not None:
                try:
                    await obj.close()
                except Exception:
                    pass
                setattr(self, closer, None)
        if self.playwright is not None:
            try:
                await self.playwright.stop()
            except Exception:
                pass
            self.playwright = None
        self.page = None
        self._observe_script_added = False
        log.info("Browser closed")
        self.emit(type="status", browser=False)

    def shutdown_blocking(self, timeout: float = 20) -> None:
        if not self.loop:
            return
        try:
            asyncio.run_coroutine_threadsafe(self.op_shutdown(), self.loop).result(timeout)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)


def _write_json(path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
