"""Artifact validation + execution of the generated Playwright Python.

Two things no other suite does:

1. Enumerates **every file the tool writes** and asserts the exact set - nothing
   missing, nothing unexpected - then validates each one parses and carries the
   keys a consumer depends on. (Earlier versions of this test asserted files that
   the tool never produced; this one derives the list from the run.)
2. **Runs the generated `ui_map.py` against the live mock** with real Playwright,
   proving the emitted locators are not just syntactically valid but actually
   resolve to the intended single element.

Run: python tests/test_artifacts.py [--debug]
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import queue
import shutil
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOME = Path(tempfile.mkdtemp(prefix="p1uid-artifacts-"))
os.environ["P1UID_HOME"] = str(HOME)

from serve_mock import MockServer                      # noqa: E402
from p1uid import paths                                # noqa: E402
from p1uid.browser.controller import Engine            # noqa: E402
from p1uid.crawler.bfs import CrawlLimits              # noqa: E402
from p1uid.logging_setup import setup                  # noqa: E402

PASSWORD = "ArtifactPass!-secret"
USERNAME = "tester@example.com"
failures: list[str] = []
count = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global count
    count += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label + ((" - " + detail) if detail else ""))


# Exactly what a full run must produce. Anything else appearing here is either a
# new artifact (update this list deliberately) or a bug.
EXPECTED = {
    "output/ui-map.json",
    "output/navigation-graph.json",
    "output/application.json",
    "output/training-summary.json",
    "output/crawl-summary.json",
    "output/workflows.json",
    "output/generated/ui-map.ts",
    "output/generated/navigation.ts",
    "output/generated/smoke.spec.ts",
    "output/generated/ui_map.py",
    "output/generated/README.md",
    "reports/discovery-report.html",
    "reports/junit-discovery.xml",
    "logs/discovery.log",
    "config/settings.json",
    "sessions/session.bin",
}
OPTIONAL = {"output/ui-diff.json", "reports/ui-diff.html"}


def produce(server) -> Engine:
    events: "queue.Queue[dict]" = queue.Queue()
    engine = Engine(events, headless="--headed" not in sys.argv,
                    remember_session=True, generate_tests=True)
    engine.start()
    engine.call(lambda: engine.op_login(server.url, USERNAME, PASSWORD), timeout=180)
    check("logged in", engine.authenticated)
    engine.call(lambda: engine.op_scan(), timeout=180)

    # a short training session with a named workflow
    engine.call(lambda: engine.op_start_training(), timeout=120)
    engine.call(lambda: engine.op_begin_workflow("Reach Germplasms"), timeout=60)

    async def drive() -> None:
        page = engine.page
        for act in (lambda: page.get_by_role("link", name="Research Groups").click(),
                    lambda: page.get_by_role("link", name="Research Group ABC").click(),
                    lambda: page.get_by_role("tab", name="Germplasms").click()):
            await act()
            await asyncio.sleep(1.0)
        await asyncio.sleep(0.6)

    engine.call(lambda: drive(), timeout=180)
    engine.call(lambda: engine.op_stop_training(), timeout=180)

    # and a small crawl, so crawl-summary.json exists too
    engine.call(lambda: engine.op_crawl(CrawlLimits(max_states=6, max_actions=15,
                                                    max_depth=3, time_budget_s=90)),
                timeout=300)
    # settings.json is written by the GUI; the CLI path never touches it
    paths.SETTINGS_FILE.write_text(json.dumps({"url": server.url, "username": USERNAME,
                                               "rememberSession": True}, indent=2),
                                   encoding="utf-8")
    return engine


def phase_artifacts() -> None:
    print("\n[1] the artifact set")
    found = {str(p.relative_to(HOME)).replace("\\", "/")
             for p in HOME.rglob("*") if p.is_file()}
    found = {f for f in found if not f.endswith(".tmp")
             and not f.startswith("sessions/DO-NOT")}
    missing = sorted(EXPECTED - found)
    unexpected = sorted(found - EXPECTED - OPTIONAL)
    for f in sorted(found):
        size = (HOME / f).stat().st_size
        print(f"    {f:44} {size:>9,} bytes")
    check("every expected artifact exists", not missing, "missing: " + ", ".join(missing))
    check("no unexpected files written", not unexpected, "unexpected: " + ", ".join(unexpected))

    print("\n[2] each artifact parses and carries what consumers need")
    m = json.loads(paths.UI_MAP_FILE.read_text(encoding="utf-8"))
    check("ui-map.json: schema + states + navigation",
          m.get("schemaVersion") == 1 and m.get("states") and "navigation" in m)
    st = next(iter(m["states"].values()))
    check("ui-map state: fingerprint/route/elements",
          all(k in st for k in ("fingerprint", "route", "elements", "timesSeen")), str(list(st)))
    el = next(iter(st["elements"].values()))
    check("ui-map element: locator with js/python/matches/confidence",
          all(k in (el.get("locator") or {}) for k in ("js", "python", "confidence"))
          and "confidence" in el, str(list(el.get("locator", {}))))

    g = json.loads(paths.NAV_GRAPH_FILE.read_text(encoding="utf-8"))
    check("navigation-graph.json: nodes/edges/tree/roots",
          all(k in g for k in ("nodes", "edges", "tree", "roots")), str(list(g)))
    a = json.loads(paths.APPLICATION_FILE.read_text(encoding="utf-8"))
    check("application.json: environments + totals",
          "environments" in a and "totals" in a, str(list(a)))
    t = json.loads(paths.TRAINING_SUMMARY_FILE.read_text(encoding="utf-8"))
    check("training-summary.json: duration/states/timeline",
          all(k in t for k in ("durationSeconds", "statesSeen", "timeline")), str(list(t)))
    c = json.loads(paths.CRAWL_SUMMARY_FILE.read_text(encoding="utf-8"))
    check("crawl-summary.json: clicks/skips/incidents/classifications",
          all(k in c for k in ("actionsClicked", "skippedByReason", "incidents",
                               "classificationTotals")), str(list(c)))
    w = json.loads(paths.WORKFLOWS_FILE.read_text(encoding="utf-8"))
    check("workflows.json: the recorded workflow with steps",
          bool(w.get("workflows")) and
          all("steps" in v for v in w["workflows"].values()), str(list(w.get("workflows", {}))))

    import re as _re
    html = paths.REPORT_FILE.read_text(encoding="utf-8")
    # Self-contained means it LOADS nothing externally. An environment URL
    # printed as text is data, not a dependency.
    resources = _re.findall(r'(?:src|href)\s*=\s*["\']([^"\']+)', html)
    check("discovery-report.html loads no external resource",
          "<script" not in html and not resources and "@import" not in html,
          f"script={'<script' in html} resources={resources[:3]}")
    root = ET.parse(paths.JUNIT_FILE).getroot()
    check("junit-discovery.xml is valid JUnit", root.tag == "testsuites"
          and root.find("testsuite") is not None)

    for name in ("ui-map.ts", "navigation.ts", "smoke.spec.ts", "ui_map.py", "README.md"):
        f = paths.GENERATED_DIR / name
        check(f"generated/{name} non-empty", f.is_file() and f.stat().st_size > 40,
              f"{f.stat().st_size if f.is_file() else 0} bytes")


def phase_run_generated(url: str) -> None:
    """Execute the generated Python against the live mock with real Playwright."""
    print("\n[3] executing generated/ui_map.py against the mock")
    sys.path.insert(0, str(paths.GENERATED_DIR))
    for mod in ("ui_map",):
        if mod in sys.modules:
            del sys.modules[mod]
    try:
        ui_map = importlib.import_module("ui_map")
    except Exception as exc:
        check("generated ui_map.py imports", False, f"{type(exc).__name__}: {exc}")
        return
    check("generated ui_map.py imports", True)
    states = getattr(ui_map, "STATES", {})
    check("generated STATES registry is populated", bool(states), f"{len(states)} states")

    target = next((s for s in states if "germplasms" in s and "dialog" not in s), None)
    check("a Germplasms page object was generated", target is not None, str(sorted(states)))
    if target is None:
        return

    from playwright.sync_api import sync_playwright

    checked = ok = 0
    detail = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless="--headed" not in sys.argv, channel="chromium")
        page = browser.new_page()
        try:
            # sign in and reach the state the page object describes
            page.goto(url, wait_until="domcontentloaded")
            page.fill("#user", USERNAME)
            page.fill("#pw", PASSWORD)
            page.get_by_test_id("login-submit").click()
            page.get_by_role("link", name="Research Groups").click()
            page.get_by_role("link", name="Research Group ABC").click()
            page.get_by_role("tab", name="Germplasms").click()
            page.wait_for_timeout(400)

            po = states[target](page)
            props = [n for n in dir(type(po)) if not n.startswith("_")]
            check("page object exposes locator properties", len(props) >= 5, f"{len(props)} props")

            needs_opening = set(getattr(ui_map, "NEEDS_OPENING", {}).get(target, []))
            check("the generated module declares which locators need opening first",
                  hasattr(ui_map, "NEEDS_OPENING"), "NEEDS_OPENING missing")

            errors, zero, deferred_zero = [], [], 0
            for name in props:
                doc = (getattr(type(po), name).__doc__ or "")
                hidden = name in needs_opening or "NOT VISIBLE" in doc
                try:
                    n = getattr(po, name).count()
                except Exception as exc:
                    errors.append(f"{name}: {type(exc).__name__}")
                    continue
                if hidden:
                    deferred_zero += 1
                    continue                      # cannot resolve until opened
                checked += 1
                if n == 1:
                    ok += 1
                else:
                    zero.append(f"{name}: matched {n}")
            detail = (f"{ok}/{checked} live locators unique; "
                      f"{deferred_zero} deferred (dialog/menu closed)")
            check("no generated locator raises when executed", not errors,
                  "; ".join(errors[:6]))
            check("EVERY live-validated generated locator resolves uniquely",
                  checked > 0 and ok == checked, detail + " | " + "; ".join(zero[:6]))

            # and one of them is genuinely usable for a test assertion
            visible = 0
            for name in props[:12]:
                try:
                    if getattr(po, name).first.is_visible(timeout=1000):
                        visible += 1
                except Exception:
                    pass
            check("generated locators find visible controls", visible >= 1, f"{visible} visible")
        finally:
            browser.close()
    print(f"    {detail}")


def phase_leaks() -> None:
    print("\n[4] secret / sensitive-data leak scan across every artifact")
    session_blob = paths.SESSION_FILE.read_bytes() if paths.SESSION_FILE.is_file() else b""
    needles = {
        "the password": PASSWORD.encode(),
        "a cookie container": b'"cookies"',
        "a localStorage container": b'"localStorage"',
        "grid row data (GP-001)": b"GP-001",
    }
    scanned = 0
    hits: list[str] = []
    for p in sorted(HOME.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(HOME)).replace("\\", "/")
        if rel.startswith("sessions/"):
            continue                       # the session file is the secret, by design
        blob = p.read_bytes()
        scanned += 1
        for what, needle in needles.items():
            if needle in blob:
                hits.append(f"{rel} contains {what}")
    print(f"    scanned {scanned} files outside sessions/")
    check("no password anywhere", not [h for h in hits if "password" in h], "; ".join(hits))
    check("no cookie/localStorage container in any output",
          not [h for h in hits if "cookie" in h or "localStorage" in h], "; ".join(hits))
    check("no grid row data persisted", not [h for h in hits if "GP-001" in h], "; ".join(hits))

    check("the session file is encrypted, not JSON",
          session_blob.startswith(b"P1UIDv1\x00") and b'"cookies"' not in session_blob,
          f"{len(session_blob)} bytes, prefix={session_blob[:8]!r}")
    log = (HOME / "logs" / "discovery.log").read_text(encoding="utf-8", errors="replace")
    for token in ("Set-Cookie", "Authorization", "Bearer "):
        check(f"log contains no {token!r}", token not in log)
    check("settings.json holds no credential",
          PASSWORD not in paths.SETTINGS_FILE.read_text(encoding="utf-8"))


def main() -> int:
    setup(debug="--debug" in sys.argv)
    with MockServer() as server:
        engine = produce(server)
        try:
            phase_artifacts()
        finally:
            engine.shutdown_blocking()
        phase_run_generated(server.url)
        phase_leaks()

    print(f"\n{count - len(failures)}/{count} artifact checks passed")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    rc = main()
    shutil.rmtree(HOME, ignore_errors=True)
    sys.exit(rc)
