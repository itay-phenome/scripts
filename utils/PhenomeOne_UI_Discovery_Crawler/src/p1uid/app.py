"""Entry point: GUI by default, headless CLI for CI (spec 27 - engine works without the GUI).

A password is NEVER accepted as a command-line argument (spec 7). Use the
P1UID_PASSWORD environment variable or the interactive prompt.
"""
from __future__ import annotations

import argparse
import getpass
import os
import queue
import sys
import time

from . import paths
from .logging_setup import get, register_secret, setup

PASSWORD_ENV = "P1UID_PASSWORD"


def _cli(args) -> int:
    from .browser.controller import Engine

    log = get("cli")
    events: "queue.Queue[dict]" = queue.Queue()
    engine = Engine(events, headless=args.headless, remember_session=args.remember,
                    validate_limit=args.validate_limit)
    engine.start()
    rc = 0
    try:
        if args.report_only:
            engine._write_outputs()
            return 0
        if not args.url:
            log.error("--url is required")
            return 2
        password = os.environ.get(args.password_env or PASSWORD_ENV, "")
        if args.user and not password and sys.stdin and sys.stdin.isatty():
            password = getpass.getpass("Password (not echoed, never stored): ")
        register_secret(password)

        if args.manual_login or not (args.user and password):
            engine.call(lambda: engine.op_manual_login(args.url, timeout_s=args.manual_timeout),
                        timeout=args.manual_timeout + 60)
        else:
            engine.call(lambda: engine.op_login(args.url, args.user, password), timeout=180)
        password = ""

        if not engine.authenticated:
            log.error("Not authenticated; aborting before discovery")
            rc = 3
        else:
            engine.call(lambda: engine.op_scan(), timeout=300)
            if args.train_seconds:
                engine.call(lambda: engine.op_start_training(), timeout=120)
                log.info("Training for %d s - drive the application now", args.train_seconds)
                deadline = time.time() + args.train_seconds
                while time.time() < deadline:
                    time.sleep(1)
                engine.call(lambda: engine.op_stop_training(), timeout=300)
        counts = engine.store.counts()
        log.info("Done: %d states, %d elements, %d navigation paths (HIGH=%d MEDIUM=%d LOW=%d)",
                 counts["states"], counts["elements"], counts["navigationPaths"],
                 counts["confidence"].get("HIGH", 0), counts["confidence"].get("MEDIUM", 0),
                 counts["confidence"].get("LOW", 0))
    finally:
        engine.shutdown_blocking()
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="PhenomeOne-UI-Discovery",
                                 description="Deterministic UI discovery for PhenomeOne.")
    ap.add_argument("--cli", action="store_true", help="run without the GUI (CI / Jenkins)")
    ap.add_argument("--url", help="PhenomeOne URL")
    ap.add_argument("--user", help="username (password comes from $" + PASSWORD_ENV + ")")
    ap.add_argument("--password-env", default=PASSWORD_ENV,
                    help="environment variable holding the password (default %(default)s)")
    ap.add_argument("--manual-login", action="store_true", help="authenticate manually in the browser")
    ap.add_argument("--manual-timeout", type=int, default=600)
    ap.add_argument("--train-seconds", type=int, default=0,
                    help="after login, observe for N seconds while you drive the app")
    ap.add_argument("--headless", action="store_true", help="run Chromium headless (CLI only)")
    ap.add_argument("--remember", action="store_true", help="save/reuse the authenticated session")
    ap.add_argument("--validate-limit", type=int, default=500,
                    help="max elements to validate per scan (default %(default)s)")
    ap.add_argument("--report-only", action="store_true",
                    help="regenerate reports from the existing UI map and exit")
    ap.add_argument("--debug", action="store_true", help="verbose logging")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    paths.ensure_dirs()
    setup(debug=args.debug)
    if args.version:
        print(f"{paths.APP_NAME} 1.0.0")
        return 0

    if args.cli or args.report_only:
        return _cli(args)

    from .gui.main_window import run
    return run(debug=args.debug)


if __name__ == "__main__":
    sys.exit(main())
