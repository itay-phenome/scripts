"""Regression tests for the four failures seen against the live PhenomeOne
instance (eksdemo-helm, 2026-08-24 23:12):

  1. Manual Login reported "Authentication successful (manual)" one second after
     the page loaded, because the SPA had not rendered its login form yet, so
     "no visible password field" was read as "signed in".
  2. Closing the browser window left the engine holding a dead handle: every
     later LOGIN/SCAN failed with TargetClosedError instead of restarting.
  3. Pressing LOGIN during a manual-login wait was rejected with "another
     operation is still running" for up to ten minutes.
  4. The engine's own first tab triggered the popup handler
     ("New browser tab detected; observing it").

Run: python tests/test_recovery.py [--headed] [--debug]
"""
from __future__ import annotations

import asyncio
import os
import queue
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOME = Path(tempfile.mkdtemp(prefix="p1uid-recover-"))
os.environ["P1UID_HOME"] = str(HOME)

from serve_mock import MockServer                      # noqa: E402
from p1uid.browser.controller import Engine            # noqa: E402
from p1uid.logging_setup import setup                  # noqa: E402

PASSWORD = "RecoveryPass!-secret"
failures: list[str] = []
count = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global count
    count += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label + ((" - " + detail) if detail else ""))


def drain(events: "queue.Queue[dict]") -> list[dict]:
    out = []
    while True:
        try:
            out.append(events.get_nowait())
        except queue.Empty:
            return out


def reset_session(engine: Engine, root: str) -> None:
    async def _c() -> None:
        await engine.page.goto(root, wait_until="domcontentloaded")
        await engine.page.evaluate("() => { try { sessionStorage.clear(); } catch (e) {} }")
    try:
        engine.call(lambda: _c(), timeout=60)
    except Exception:
        pass


def main() -> int:
    setup(debug="--debug" in sys.argv)
    headless = "--headed" not in sys.argv

    with MockServer() as server:
        base = server.url
        root = base.rsplit("/app/", 1)[0] + "/"
        events: "queue.Queue[dict]" = queue.Queue()
        engine = Engine(events, headless=headless, login_wait_s=6.0)
        engine.start()
        try:
            print("\n[1] Manual Login must not claim success before a form exists")
            # 8s boot delay > the 6s login_wait_s: the form is NOT there in time.
            engine.authenticated = False
            engine.call(lambda: engine.op_manual_login(base + "?delay=8000", timeout_s=5),
                        timeout=120)
            statuses = [e.get("auth") for e in drain(events) if e.get("type") == "status"]
            check("no false 'authenticated' when the form has not rendered",
                  not engine.authenticated, f"authenticated={engine.authenticated}")
            check("status says the form was not found",
                  any("No sign-in form" in str(s) for s in statuses), str(statuses))

            print("\n[2] Manual Login succeeds once the form is completed")
            reset_session(engine, root)
            engine.authenticated = False

            def manual() -> None:
                engine.submit(lambda: engine.op_manual_login(base, timeout_s=60),
                              op="manual_login")

            manual()

            async def human_signs_in() -> None:
                # Give the tool time to find the form, then sign in like a user.
                await asyncio.sleep(3.0)
                page = engine.page
                await page.fill("#user", "tester@example.com")
                await page.fill("#pw", PASSWORD)
                await page.get_by_test_id("login-submit").click()

            engine.call(lambda: human_signs_in(), timeout=120)
            deadline = time.time() + 40
            while time.time() < deadline and not engine.authenticated:
                time.sleep(0.5)
            check("manual login is confirmed after the form is completed", engine.authenticated)
            statuses = [e.get("auth") for e in drain(events) if e.get("type") == "status"]
            check("status reports a manual connection",
                  any("manual" in str(s).lower() for s in statuses), str(statuses))

            print("\n[3] a LOGIN during a manual-login wait is not rejected")
            reset_session(engine, root)
            engine.authenticated = False
            engine.submit(lambda: engine.op_manual_login(base, timeout_s=120), op="manual_login")
            time.sleep(4)                      # let the wait get going
            drain(events)
            engine.submit(lambda: engine.op_login(base, "tester@example.com", PASSWORD),
                          op="login")
            deadline = time.time() + 60
            evs: list[dict] = []
            while time.time() < deadline:
                evs += drain(events)
                if engine.authenticated:
                    break
                time.sleep(0.4)
            busy = [e for e in evs if e.get("type") == "error"
                    and "another operation" in str(e.get("msg"))]
            check("LOGIN is not blocked by the manual-login wait", not busy, str(busy))
            check("the automatic login went through", engine.authenticated)

            print("\n[4] closing the browser must not break the next operation")
            engine.call(lambda: engine.op_scan(), timeout=180)
            before = engine.store.counts()["elements"]
            check("a scan worked before closing the browser", before > 0, str(before))

            async def close_browser() -> None:
                # Exactly what the user did: close the window.
                await engine.browser.close()

            engine.call(lambda: close_browser(), timeout=60)
            check("browser is really gone", not engine.browser.is_connected())

            drain(events)
            engine.authenticated = False
            engine.call(lambda: engine.op_login(base, "tester@especial.test", PASSWORD),
                        timeout=180)
            errs = [e for e in drain(events) if e.get("type") == "error"]
            check("LOGIN after closing the browser does not raise TargetClosedError",
                  not [e for e in errs if "TargetClosed" in str(e.get("msg"))], str(errs))
            check("the engine restarted the browser by itself",
                  engine.browser is not None and engine.browser.is_connected())
            check("and authenticated again", engine.authenticated)

            engine.call(lambda: engine.op_scan(), timeout=180)
            check("scanning works after the recovery",
                  engine.store.counts()["elements"] >= before,
                  f"{before} -> {engine.store.counts()['elements']}")

            print("\n[5] closing only the tab is recovered too")

            async def close_tab() -> None:
                await engine.page.close()

            engine.call(lambda: close_tab(), timeout=60)
            engine.call(lambda: engine.op_scan(), timeout=180)
            check("a closed tab is replaced without restarting the browser",
                  engine.page is not None and not engine.page.is_closed())

            print("\n[6] our own first tab is not reported as a popup")
            log_text = (HOME / "logs" / "discovery.log").read_text(encoding="utf-8",
                                                                  errors="replace")
            check("no spurious 'New browser tab detected' at startup",
                  "New browser tab detected" not in log_text,
                  "found the popup message in the log")

            # Live-log failure, 2026-08-26: pressing Manual Login twice while the
            # first wait was running made the second press re-navigate, which
            # destroyed the form the first press was waiting for; the first press
            # then reported "No sign-in form appeared" about a page that no longer
            # existed. A second press must supersede, not sabotage.
            print("\n[7] pressing Manual Login twice must not sabotage the first wait")
            reset_session(engine, root)
            engine.authenticated = False
            drain(events)
            log_before = (HOME / "logs" / "discovery.log").stat().st_size

            # The form takes 4 s to render; the first press is mid-wait when the
            # second arrives.
            # The second press lands at ~3 s. That timing is deliberate: with the
            # old behaviour the reload would push the form out to ~7 s, past the
            # 6 s login_wait_s, so the first attempt would log its stale verdict -
            # which is exactly what this section asserts must not happen.
            slow = base + "?delay=4000"
            engine.submit(lambda: engine.op_manual_login(slow, timeout_s=45), op="manual_login")
            time.sleep(3.0)
            check("a manual-login wait is marked active", engine._manual_active)
            gen_before = engine._manual_gen
            engine.submit(lambda: engine.op_manual_login(slow, timeout_s=45), op="manual_login")
            time.sleep(2.0)
            check("the second press superseded the first",
                  engine._manual_gen > gen_before, f"{gen_before} -> {engine._manual_gen}")

            async def human_signs_in_again() -> None:
                await engine.page.wait_for_selector("#pw", timeout=30000)
                await engine.page.fill("#user", "tester@example.com")
                await engine.page.fill("#pw", PASSWORD)
                await engine.page.get_by_test_id("login-submit").click()

            engine.call(lambda: human_signs_in_again(), timeout=120)
            deadline = time.time() + 60
            while time.time() < deadline and not engine.authenticated:
                time.sleep(0.5)
            check("the surviving attempt still completes the sign-in", engine.authenticated)

            new_log = (HOME / "logs" / "discovery.log").read_text(
                encoding="utf-8", errors="replace")[log_before:]
            check("the superseded wait reported no false 'no sign-in form'",
                  "No sign-in form appeared within" not in new_log,
                  "the stale verdict was logged anyway")
            check("the second press did not reload the page",
                  "not reloading the page" in new_log, "no supersede message in the log")
            check("the wait flag is released once the attempt finishes",
                  not engine._manual_active)

            # Control: prove the in-progress guard is what prevents the reload.
            # Clearing the flag makes op_manual_login take the pre-fix branch, so
            # a second press navigates again - the sabotage this section exists
            # to stop. If this check fails, the assertions above are toothless.
            reset_session(engine, root)
            engine.authenticated = False
            mark = (HOME / "logs" / "discovery.log").stat().st_size
            engine.submit(lambda: engine.op_manual_login(slow, timeout_s=20), op="manual_login")
            time.sleep(3.0)
            engine._manual_active = False           # simulate the pre-fix state
            engine.submit(lambda: engine.op_manual_login(slow, timeout_s=20), op="manual_login")
            time.sleep(3.0)
            control = (HOME / "logs" / "discovery.log").read_text(
                encoding="utf-8", errors="replace")[mark:]
            check("without the guard the page IS reloaded (so the guard is load-bearing)",
                  "not reloading the page" not in control and "Opening URL" in control,
                  control[-200:].replace("\n", " | "))
            # Drain the orphaned waits before teardown, or asyncio complains that
            # a pending task was destroyed.
            engine._cancel_manual = True
            drain_deadline = time.time() + 30
            while time.time() < drain_deadline and engine._manual_active:
                time.sleep(0.5)
            check("the control's waits drained before teardown", not engine._manual_active)
        finally:
            engine.shutdown_blocking()

    leaked = [str(p.relative_to(HOME)) for p in HOME.rglob("*")
              if p.is_file() and PASSWORD.encode() in p.read_bytes()]
    check("no secret written during recovery", not leaked, "; ".join(leaked))

    print(f"\n{count - len(failures)}/{count} recovery checks passed")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    rc = main()
    shutil.rmtree(HOME, ignore_errors=True)
    sys.exit(rc)
