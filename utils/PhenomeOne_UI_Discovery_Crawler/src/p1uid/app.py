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


def _run_functional(args, engine, log) -> int:
    """Execute a functional suite. Returns 6 if any test failed."""
    from .functional.steps import load_suite

    try:
        suite = load_suite(args.run_tests)
    except (OSError, ValueError, KeyError) as exc:
        log.error("Cannot load the functional suite: %s", exc)
        return 2
    suite = suite.select(level=args.test_level, names=args.test_name)
    if not suite.tests:
        log.error("No tests selected from %s (level=%s, names=%s)",
                  args.run_tests, args.test_level, args.test_name)
        return 2
    result = engine.call(lambda: engine.op_run_functional(suite, run_id=args.run_id),
                         timeout=3600)
    if result is None:
        log.error("The functional suite could not be started")
        return 6
    log.info("FUNCTIONAL: %s", result.summary_line())
    for t in result.tests:
        log.info("  %-6s %s (%s)%s", t.status, t.name, t.level,
                 f" - {t.failure}" if t.failure else "")
    if result.leftovers:
        log.error("Leftover test data: %s", ", ".join(result.leftovers))
    return 0 if result.ok else 6


def _ci_gate(args, engine, log) -> int:
    """Jenkins gate: non-zero when the map is not good enough to test against."""
    counts = engine.store.counts()
    low = counts["confidence"].get("LOW", 0)
    if args.fail_on_low >= 0 and low > args.fail_on_low:
        log.error("CI gate FAILED: %d LOW-confidence locator(s) exceeds the allowed %d. "
                  "See reports/junit-discovery.xml for the list and the suggested test ids.",
                  low, args.fail_on_low)
        return 4
    return 0


def _cli(args) -> int:
    from .browser.controller import Engine

    log = get("cli")
    events: "queue.Queue[dict]" = queue.Queue()
    engine = Engine(events, headless=args.headless, remember_session=args.remember,
                    validate_limit=args.validate_limit,
                    generate_tests=args.generate_tests)
    engine.start()
    rc = 0
    try:
        if args.report_only:
            engine.write_outputs()
            return _ci_gate(args, engine, log)
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
                if args.workflow:
                    engine.call(lambda: engine.op_begin_workflow(args.workflow), timeout=60)
                log.info("Training for %d s - drive the application now", args.train_seconds)
                deadline = time.time() + args.train_seconds
                while time.time() < deadline:
                    time.sleep(1)
                engine.call(lambda: engine.op_stop_training(), timeout=300)
            if args.crawl:
                from .crawler.bfs import CrawlLimits
                limits = CrawlLimits(max_states=args.crawl_max_states,
                                     max_actions=args.crawl_max_actions,
                                     max_depth=args.crawl_max_depth,
                                     time_budget_s=args.crawl_seconds)
                engine.call(lambda: engine.op_crawl(limits),
                            timeout=args.crawl_seconds + 300)
        counts = engine.store.counts()
        log.info("Done: %d states, %d elements, %d navigation paths (HIGH=%d MEDIUM=%d LOW=%d)",
                 counts["states"], counts["elements"], counts["navigationPaths"],
                 counts["confidence"].get("HIGH", 0), counts["confidence"].get("MEDIUM", 0),
                 counts["confidence"].get("LOW", 0))
        rc = _ci_gate(args, engine, log) or rc

        if args.run_tests:
            frc = _run_functional(args, engine, log)
            rc = frc or rc
    finally:
        engine.shutdown_blocking()
    return rc


def _diff(args) -> int:
    """Compare two UI maps and write the diff reports. Exit 5 if they differ."""
    from . import diff as uidiff

    log = get("diff")
    baseline, current = args.diff
    try:
        old = uidiff.load_map(baseline)
        new = uidiff.load_map(current)
    except (OSError, ValueError) as exc:
        log.error("%s", exc)
        return 2
    result = uidiff.diff_maps(old, new)
    uidiff.write_reports(result, paths.DIFF_JSON_FILE, paths.DIFF_REPORT_FILE)
    for line in uidiff.render_lines(result):
        print(line)
    s = result["summary"]
    log.info("UI diff: states +%d -%d ~%d | elements +%d -%d ~%d | locators changed %d | "
             "paths +%d -%d", s["statesAdded"], s["statesRemoved"], s["statesChanged"],
             s["elementsAdded"], s["elementsRemoved"], s["elementsChanged"],
             s["locatorsChanged"], s["pathsAdded"], s["pathsRemoved"])
    return 5 if result["hasChanges"] else 0


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
    ap.add_argument("--crawl", action="store_true",
                    help="Safe Crawl: explore read-only navigation autonomously after login")
    ap.add_argument("--crawl-max-states", type=int, default=40)
    ap.add_argument("--crawl-max-actions", type=int, default=250)
    ap.add_argument("--crawl-max-depth", type=int, default=6)
    ap.add_argument("--crawl-seconds", type=float, default=300.0,
                    help="wall-clock budget for the crawl (default %(default)s)")
    ap.add_argument("--workflow", metavar="NAME",
                    help="record the training session as a named workflow")
    ap.add_argument("--generate-tests", action="store_true",
                    help="emit Playwright assets into output/generated/")
    ap.add_argument("--diff", nargs=2, metavar=("BASELINE", "CURRENT"),
                    help="diff two ui-map.json files and exit")
    ap.add_argument("--fail-on-low", type=int, default=-1, metavar="N",
                    help="exit 4 when more than N LOW-confidence locators exist (CI gate)")
    ap.add_argument("--run-tests", metavar="SUITE.json",
                    help="run a declarative functional suite after discovery (exit 6 on failure)")
    ap.add_argument("--test-level", choices=("smoke", "critical", "full"),
                    help="only run tests at this level or below")
    ap.add_argument("--test-name", action="append", metavar="NAME",
                    help="run only the named test (repeatable)")
    ap.add_argument("--run-id", help="override the generated RUN_ID for test data")
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
        print(f"{paths.APP_NAME} 1.2.0")
        return 0

    if args.diff:
        return _diff(args)
    if args.cli or args.report_only:
        return _cli(args)

    from .gui.main_window import run
    return run(debug=args.debug)


if __name__ == "__main__":
    sys.exit(main())
