"""End-to-end test of the discovery engine against the mock PhenomeOne SPA.

Covers: browser launch, automatic login, Scan Current Page, Training Mode with
real (trusted) user-style input, UI-state fingerprinting across tab switches
that do NOT change the URL, navigation-graph learning, locator validation,
output files, and a secret-leak check over everything written to disk.

Run:  python tests/test_e2e_mock.py [--headed]
"""
from __future__ import annotations

import asyncio
import json
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

HOME = Path(tempfile.mkdtemp(prefix="p1uid-e2e-"))
os.environ["P1UID_HOME"] = str(HOME)

from serve_mock import MockServer                                  # noqa: E402
from p1uid import paths                                            # noqa: E402
from p1uid.logging_setup import setup                              # noqa: E402
from p1uid.browser.controller import Engine                        # noqa: E402

PASSWORD = "MockPassw0rd!-do-not-log"
USERNAME = "tester@example.com"

failures: list[str] = []
checks = 0


def check(label: str, ok: bool, detail: str = "") -> bool:
    global checks
    checks += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label + ((" - " + detail) if detail else ""))
    return ok


async def drive(engine: Engine) -> None:
    """Act like the user: real clicks through the app while training runs."""
    page = engine.page
    steps = [
        ("Research Groups link", lambda: page.get_by_role("link", name="Research Groups").click()),
        ("Research Group ABC link", lambda: page.get_by_role("link", name="Research Group ABC").click()),
        ("Germplasms tab", lambda: page.get_by_role("tab", name="Germplasms").click()),
        ("Add Germplasm button", lambda: page.get_by_test_id("germplasm-add").click()),
        ("Close dialog", lambda: page.get_by_role("button", name="Close dialog").click()),
        ("Variables tab", lambda: page.get_by_role("tab", name="Variables").click()),
        ("Observations tab", lambda: page.get_by_role("tab", name="Observations").click()),
        ("Inventory tab", lambda: page.get_by_role("tab", name="Inventory").click()),
    ]
    for label, action in steps:
        try:
            await action()
        except Exception as exc:
            failures.append(f"driving step '{label}' failed: {exc}")
            print(f"  FAIL  driving step '{label}': {exc}")
            continue
        await asyncio.sleep(1.1)          # let the trainer observe + scan
    await asyncio.sleep(1.0)


def scan_for_secrets(root: Path) -> list[str]:
    """Nothing written to disk may contain the password or a session cookie."""
    hits: list[str] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            blob = p.read_bytes()
        except OSError:
            continue
        for needle in (PASSWORD.encode(), b"MockPassw0rd"):
            if needle in blob:
                hits.append(f"{p.relative_to(root)} contains the password")
        if p.suffix in (".json", ".html", ".log") and b'"cookies"' in blob:
            hits.append(f"{p.relative_to(root)} contains cookie material")
    return hits


def main() -> int:
    headless = "--headed" not in sys.argv
    setup(debug="--debug" in sys.argv)
    print(f"\nE2E: home={HOME}  headless={headless}\n")

    with MockServer() as server:
        events: "queue.Queue[dict]" = queue.Queue()
        engine = Engine(events, headless=headless, remember_session=True)
        engine.start()
        try:
            print("[1] login")
            engine.call(lambda: engine.op_login(server.url, USERNAME, PASSWORD), timeout=180)
            check("automatic login succeeded", engine.authenticated)
            check("session file written (DPAPI)", paths.SESSION_FILE.is_file())

            print("[2] scan current page")
            engine.call(lambda: engine.op_scan(), timeout=180)
            c = engine.store.counts()
            check("scan found interactive elements", c["elements"] > 3, f"{c['elements']} elements")
            check("home state recorded", any("home" in s for s in engine.store.data["states"]),
                  ", ".join(engine.store.data["states"]))

            print("[3] training mode")
            engine.call(lambda: engine.op_start_training(), timeout=120)
            check("trainer active", engine.trainer is not None)
            engine.call(lambda: drive(engine), timeout=180)
            engine.call(lambda: engine.op_stop_training(), timeout=180)

            data = engine.store.data
            states = data["states"]
            nav = data["navigation"]
            print(f"\n  states learned: {len(states)} -> {', '.join(sorted(states))}")
            print(f"  navigation paths: {len(nav)}")

            check("multiple UI states discovered", len(states) >= 5, f"{len(states)}")
            check("navigation edges learned", len(nav) >= 4, f"{len(nav)}")

            ids = " ".join(states)
            check("research-groups state found", "research-groups" in ids)
            check("germplasms tab state found", "germplasms" in ids)
            check("dialog state found", "dialog" in ids, ids)
            check("tab switch created distinct states (URL did not change)",
                  sum(1 for s in states if s.startswith("research-group-")) >= 3,
                  ", ".join(s for s in states if s.startswith("research-group")))

            # A tab click must be attributed to the tab element, with a locator.
            tab_edges = [e for e in nav.values()
                         if e["action"].get("type") == "tab" and e["action"].get("locator")]
            check("tab navigation attributed to the clicked tab", len(tab_edges) >= 2,
                  f"{len(tab_edges)} tab edges")
            germ = [e for e in nav.values() if e["action"].get("name") == "Germplasms"]
            if germ:
                print(f"  example edge: {germ[0]['from']} --[{germ[0]['action'].get('locator')}]--> {germ[0]['to']}")
            check("Germplasms edge uses getByRole tab locator",
                  bool(germ) and "getByRole('tab'" in (germ[0]["action"].get("locator") or ""),
                  germ[0]["action"].get("locator") if germ else "no edge")

            # Locator quality
            conf = engine.store.counts()["confidence"]
            print(f"  locator quality: {conf}")
            check("most locators are HIGH", conf["HIGH"] > conf["LOW"], str(conf))

            testid_elements = [el for st in states.values() for el in st["elements"].values()
                               if (el.get("locator") or {}).get("strategy") == "testid"]
            check("test-id elements got HIGH confidence",
                  bool(testid_elements) and all(e["confidence"] == "HIGH" for e in testid_elements),
                  f"{len(testid_elements)} test-id elements")

            validated = [el for st in states.values() for el in st["elements"].values()
                         if (el.get("locator") or {}).get("matches") is not None]
            check("locators were validated against the live page",
                  len(validated) > 10, f"{len(validated)} validated")

            dup = [el for st in states.values() for el in st["elements"].values()
                   if el.get("name") == "Edit" and el.get("type") == "button"]
            check("ambiguous duplicate buttons flagged LOW + recommendation",
                  bool(dup) and any(e["confidence"] == "LOW" and e.get("recommendation") for e in dup),
                  f"{len(dup)} 'Edit' buttons")

            # Structural-only grid capture
            grids = [el for st in states.values() for el in st["elements"].values() if el.get("grid")]
            check("grid captured as columns + row count only",
                  bool(grids) and all(set(g["grid"]) <= {"columns", "rowCount"} for g in grids),
                  str(grids[0]["grid"]) if grids else "none")
            blob = json.dumps(data)
            check("no business data persisted (grid rows absent)",
                  "GP-001" not in blob and "GP-002" not in blob)

            print("[4] output files")
            for f in (paths.UI_MAP_FILE, paths.NAV_GRAPH_FILE, paths.APPLICATION_FILE,
                      paths.TRAINING_SUMMARY_FILE, paths.REPORT_FILE):
                check(f"{f.name} written", f.is_file(),
                      f"{f.stat().st_size} bytes" if f.is_file() else "missing")
            navjson = json.loads(paths.NAV_GRAPH_FILE.read_text(encoding="utf-8"))
            check("navigation graph has a tree", bool(navjson.get("tree")))
            print("\n  --- learned navigation tree ---")
            for line in navjson.get("tree", [])[:30]:
                print("   " + line)
            print()

            print("[5] incremental merge (second scan must not duplicate)")
            before = len(states)
            elements_before = engine.store.counts()["elements"]
            engine.call(lambda: engine.op_scan(), timeout=180)
            after = engine.store.counts()
            check("re-scanning a known state does not add states",
                  len(engine.store.data["states"]) == before, f"{before} -> {len(engine.store.data['states'])}")
            check("re-scanning does not duplicate elements",
                  after["elements"] == elements_before, f"{elements_before} -> {after['elements']}")
            some = next(iter(engine.store.data["states"].values()))["elements"]
            check("timesSeen incremented on re-scan",
                  any(e.get("timesSeen", 0) >= 2 for e in some.values()))

            print("[6] session reuse across runs")
            state = engine.sessions.load()
            check("saved session decrypts", isinstance(state, dict) and "cookies" in state)

        finally:
            engine.shutdown_blocking()

    print("[7] secret-leak scan over every written file")
    leaks = scan_for_secrets(HOME)
    check("no secrets in any output/report/log file", not leaks, "; ".join(leaks))

    print(f"\n{'=' * 62}\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
    else:
        print("ALL CHECKS PASSED")
    print(f"artifacts kept in: {HOME}")
    return 1 if failures else 0


if __name__ == "__main__":
    rc = main()
    if rc == 0 and "--keep" not in sys.argv:
        shutil.rmtree(HOME, ignore_errors=True)
    sys.exit(rc)
