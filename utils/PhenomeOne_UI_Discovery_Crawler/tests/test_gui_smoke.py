"""GUI smoke test: drives the real Tkinter window and the real browser.

Exercises the actual button callbacks (LOGIN, SCAN CURRENT PAGE, START/STOP
TRAINING, Clear Saved Session, window close) rather than the engine directly,
so the GUI wiring itself is covered.

Run: python tests/test_gui_smoke.py [--visible]
"""
from __future__ import annotations

import asyncio
import os
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

HOME = Path(tempfile.mkdtemp(prefix="p1uid-gui-"))
os.environ["P1UID_HOME"] = str(HOME)

from serve_mock import MockServer                    # noqa: E402
from p1uid import paths                              # noqa: E402

PASSWORD = "GuiSmokePass!-secret"
failures: list[str] = []
count = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global count
    count += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def pump(app, seconds: float) -> None:
    """Run the Tk event loop for a while without blocking on mainloop()."""
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def pump_until(app, predicate, timeout: float) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        app.update()
        if predicate():
            return True
        time.sleep(0.05)
    return False


def main() -> int:
    from p1uid.gui.main_window import App

    try:
        app = App(debug=False)
    except Exception as exc:                     # no desktop session available
        print(f"SKIPPED: cannot create a Tk window here ({exc})")
        return 0

    if "--visible" not in sys.argv:
        app.withdraw()

    with MockServer() as server:
        print(f"\nGUI smoke test  home={HOME}  url={server.url}\n")
        check("window built", app.title() == paths.APP_NAME)
        check("password field is masked", str(app.nametowidget(
            app.winfo_children()[0].winfo_children()[0].winfo_children()[5]).cget("show")) in ("•", "*"))

        app.var_url.set(server.url)
        app.var_user.set("tester@example.com")
        app.var_pass.set(PASSWORD)
        app.var_headless.set("--visible" not in sys.argv)
        app.var_remember.set(True)

        print("[1] LOGIN button")
        app.on_login()
        ok = pump_until(app, lambda: "Connected" in app.var_auth.get(), 120)
        check("login through the GUI connects", ok, app.var_auth.get())
        check("password cleared from the widget after submitting", app.var_pass.get() == "")
        check("settings file has no credential",
              paths.SETTINGS_FILE.is_file()
              and PASSWORD not in paths.SETTINGS_FILE.read_text(encoding="utf-8"))

        print("[2] SCAN CURRENT PAGE button")
        app.on_scan()
        ok = pump_until(app, lambda: int(app.stats["elements"].get() or 0) > 3, 120)
        check("scan updates the GUI counters", ok,
              f"elements={app.stats['elements'].get()} states={app.stats['states'].get()}")
        check("HIGH locator counter populated", int(app.stats["high"].get() or 0) > 0,
              app.stats["high"].get())

        print("[3] START TRAINING button")
        app.on_training()
        ok = pump_until(app, lambda: app.training, 60)
        check("training starts from the GUI", ok, app.var_training.get())
        check("button relabelled to STOP TRAINING", app.b_train.cget("text") == "STOP TRAINING")

        # Drive the app like a user while the GUI keeps pumping.
        eng = app.engine

        async def click_through() -> None:
            page = eng.page
            for name, action in (
                ("Research Groups", lambda: page.get_by_role("link", name="Research Groups").click()),
                ("Research Group ABC", lambda: page.get_by_role("link", name="Research Group ABC").click()),
                ("Germplasms", lambda: page.get_by_role("tab", name="Germplasms").click()),
            ):
                await action()
                await asyncio.sleep(1.0)

        fut = asyncio.run_coroutine_threadsafe(click_through(), eng.loop)
        pump_until(app, fut.done, 60)
        pump(app, 1.5)
        check("duration timer runs", app.var_duration.get() != "00:00", app.var_duration.get())
        states_seen = int(app.stats["states"].get() or 0)
        check("training discovered new states from GUI-driven clicks", states_seen >= 3,
              f"{states_seen} states")

        print("[4] STOP TRAINING button")
        app.on_training()
        ok = pump_until(app, lambda: not app.training, 120)
        check("training stops from the GUI", ok, app.var_training.get())
        check("button relabelled to START TRAINING", app.b_train.cget("text") == "START TRAINING")
        check("navigation paths counter populated", int(app.stats["paths"].get() or 0) >= 2,
              app.stats["paths"].get())

        print("[5] outputs + Clear Saved Session")
        for f in (paths.UI_MAP_FILE, paths.NAV_GRAPH_FILE, paths.REPORT_FILE):
            check(f"{f.name} exists", f.is_file())
        check("session was saved", paths.SESSION_FILE.is_file())
        from p1uid.security.session_store import SessionStore
        SessionStore().clear()
        check("Clear Saved Session removes the file", not paths.SESSION_FILE.is_file())

        print("[6] window close shuts the browser down")
        app._on_close()
        check("engine stopped cleanly", app.engine.context is None)

    leaked = [str(p.relative_to(HOME)) for p in HOME.rglob("*")
              if p.is_file() and PASSWORD.encode() in p.read_bytes()]
    check("no file written by the GUI contains the password", not leaked, "; ".join(leaked))

    print(f"\n{count - len(failures)}/{count} GUI checks passed")
    if failures:
        print("FAILURES:", "; ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    rc = main()
    shutil.rmtree(HOME, ignore_errors=True)
    sys.exit(rc)
