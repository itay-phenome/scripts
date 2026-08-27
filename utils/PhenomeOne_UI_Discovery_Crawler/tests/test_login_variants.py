"""Login-detection tests for the shapes real SaaS apps actually use.

Regression cover for the case seen against the live PhenomeOne instance, where
a single immediate look at the main frame reported "No login form found":

  1. form renders well after domcontentloaded (slow SPA boot)
  2. form lives in an identity-provider iframe, which page.locator never sees
  3. landing page hides the form behind one "Sign in" entry point
  4. no form at all -> must refuse cleanly AND print useful diagnostics

Run: python tests/test_login_variants.py [--headed]
"""
from __future__ import annotations

import os
import queue
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOME = Path(tempfile.mkdtemp(prefix="p1uid-login-"))
os.environ["P1UID_HOME"] = str(HOME)

from serve_mock import MockServer                     # noqa: E402
from p1uid.auth import login as auth_login            # noqa: E402
from p1uid.browser.controller import Engine           # noqa: E402
from p1uid.logging_setup import setup                 # noqa: E402

PASSWORD = "VariantPass!-secret"
USER = "tester@example.com"
failures: list[str] = []
count = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global count
    count += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def reset_session(engine: Engine, root: str) -> None:
    """The mock keeps a session across reloads (like a real app), so each case
    must start signed out or it would see itself already authenticated."""
    async def _clear() -> None:
        await engine.page.goto(root, wait_until="domcontentloaded")
        await engine.page.evaluate("() => { try { sessionStorage.clear(); "
                                  "localStorage.clear(); } catch (e) {} }")
        # The mock authenticates with a cookie now, the way a real application
        # does, so clearing storage alone no longer signs it out.
        await engine.context.clear_cookies()
    try:
        engine.call(lambda: _clear(), timeout=60)
    except Exception:
        pass


def run_case(engine: Engine, url: str, root: str = "") -> bool:
    if root:
        reset_session(engine, root)
    engine.authenticated = False
    engine.call(lambda: engine.op_login(url, USER, PASSWORD), timeout=180)
    return engine.authenticated


def main() -> int:
    headless = "--headed" not in sys.argv
    setup(debug="--debug" in sys.argv)
    rc = 0

    with MockServer() as server:
        base = server.url                        # http://127.0.0.1:PORT/app/
        root = base.rsplit("/app/", 1)[0] + "/"
        events: "queue.Queue[dict]" = queue.Queue()
        engine = Engine(events, headless=headless, login_wait_s=20.0)
        engine.start()
        try:
            print("\n[1] login form renders 4s after page load")
            check("slow-booting form is found and used", run_case(engine, base + "?delay=4000", root))

            print("\n[2] login form inside an identity-provider iframe")
            ok = run_case(engine, root + "iframe_login.html", root)
            check("form inside an iframe is found and used", ok)
            check("success detected even though the iframe was destroyed", ok)

            print("\n[3] landing page with a single 'Sign in' entry point")
            check("entry point clicked, then the form is used",
                  run_case(engine, base + "?landing=1", root))

            print("\n[4] a page with no login form at all")
            ok = run_case(engine, root + "no_form.html", root)
            check("refuses cleanly instead of typing into random fields", not ok)
            diag = engine.call(lambda: auth_login.describe_page(engine.page), timeout=60)
            print("\n".join("      " + l for l in diag.splitlines()[:6]))
            check("diagnostics report the page structure",
                  "frame[0]" in diag and "inputs=" in diag)

            # Live failure (PhenomeOne, 2026-08-26): the password field became
            # visible 18.1 s after load while #usernameLoginInput was still not
            # visible, so a fillable form was refused with "no username field
            # candidate found". The analysis must let the form finish rendering.
            print("\n[5] username field appears AFTER the password field")
            ok = run_case(engine, base + "?userlate=2500", root)
            check("a late-rendering username field no longer defeats login", ok)
            log_text = (HOME / "logs" / "discovery.log").read_text(encoding="utf-8",
                                                                  errors="replace")
            check("the wait was reported, not silent",
                  "not visible yet" in log_text, "no settle message logged")
            check("and the form was accepted once it rendered",
                  "finished rendering" in log_text, "no resolution message logged")

            print("\n[6] a username field that NEVER appears is still refused")
            ok = run_case(engine, base + "?userlate=600000", root)
            check("fails closed rather than guessing", not ok)
            fields = engine.call(
                lambda: auth_login.read_fields(engine.page.main_frame), timeout=60)
            desc = auth_login.describe_fields(fields)
            print("\n".join("      " + l for l in desc.splitlines()[:5]))
            check("the diagnostic says WHY the field is invisible",
                  "NOT-VISIBLE(" in desc and "display:none" in desc, desc[:200])

            print("\n[7] scanning still works after each of those logins")
            engine.call(lambda: engine.op_scan(), timeout=180)
            check("scan produced elements", engine.store.counts()["elements"] > 3,
                  f"{engine.store.counts()['elements']} elements")
        finally:
            engine.shutdown_blocking()

    leaked = [str(p.relative_to(HOME)) for p in HOME.rglob("*")
              if p.is_file() and PASSWORD.encode() in p.read_bytes()]
    check("password written nowhere", not leaked, "; ".join(leaked))

    print(f"\n{count - len(failures)}/{count} login-variant checks passed")
    if failures:
        print("FAILURES:", "; ".join(failures))
        rc = 1
    return rc


if __name__ == "__main__":
    code = main()
    shutil.rmtree(HOME, ignore_errors=True)
    sys.exit(code)
