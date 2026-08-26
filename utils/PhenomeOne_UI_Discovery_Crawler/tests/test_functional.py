"""Phase 1 milestone: a real functional test executed against the mock app.

Proves the whole vertical slice end to end:

    discover -> navigate by state id -> create a record -> verify it ->
    change it -> delete it -> verify the deletion -> clean up

and then proves the guard rails actually hold:

  * a destructive step whose state guard does not match is REFUSED before clicking
  * a destructive step whose target is ambiguous is REFUSED before clicking
  * a genuine failure produces evidence: screenshot, trace, expected vs actual,
    the locator used, and console/page/network errors
  * cleanup runs even when the test fails, and unremoved records are reported
  * functional results are written separately from the discovery-health JUnit

Run: python tests/test_functional.py [--headed] [--debug]
"""
from __future__ import annotations

import asyncio
import copy
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

HOME = Path(tempfile.mkdtemp(prefix="p1uid-func-"))
os.environ["P1UID_HOME"] = str(HOME)

from serve_mock import MockServer                          # noqa: E402
from p1uid import paths                                    # noqa: E402
from p1uid.browser.controller import Engine                # noqa: E402
from p1uid.functional import steps as stepmod              # noqa: E402
from p1uid.functional.data import looks_like_run_id        # noqa: E402
from p1uid.functional.steps import Suite, load_suite       # noqa: E402
from p1uid.logging_setup import setup                      # noqa: E402

SUITE_PATH = ROOT / "tests" / "functional" / "germplasm_crud.json"
PASSWORD = "FunctionalPass!-secret"
failures: list[str] = []
count = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global count
    count += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label + ((" - " + detail) if detail else ""))


def discover(engine: Engine, server) -> None:
    """Teach the tool the route to the Germplasms grid, the normal way."""
    engine.call(lambda: engine.op_login(server.url, "qa@example.com", PASSWORD), timeout=180)
    check("logged into the mock app", engine.authenticated)
    engine.call(lambda: engine.op_scan(), timeout=180)
    engine.call(lambda: engine.op_start_training(), timeout=120)

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
    states = engine.store.data["states"]
    check("discovery learned the Germplasms state", "research-group-germplasms" in states,
          ", ".join(sorted(states)))
    check("discovery learned a navigation route to it",
          any(e["to"] == "research-group-germplasms"
              for e in engine.store.data["navigation"].values()))


def main() -> int:
    setup(debug="--debug" in sys.argv)
    headless = "--headed" not in sys.argv

    with MockServer() as server:
        events: "queue.Queue[dict]" = queue.Queue()
        engine = Engine(events, headless=headless)
        engine.start()
        try:
            print(f"\nFunctional milestone  home={HOME}\n")
            print("[1] discovery first (the functional suite consumes its output)")
            discover(engine, server)

            print("\n[2] the suite loads and is well-formed")
            suite = load_suite(SUITE_PATH)
            check("suite parses", bool(suite.tests), f"{len(suite.tests)} tests")
            crud = suite.tests[0]
            check("destructive steps are explicitly declared",
                  len(crud.destructive_steps) >= 3,
                  f"{len(crud.destructive_steps)} destructive of {len(crud.steps)}")
            check("levels are declared", {t.level for t in suite.tests} == {"critical", "smoke"},
                  str({t.level for t in suite.tests}))
            check("level selection narrows the suite",
                  len(suite.select(level="smoke").tests) == 1)

            print("\n[3] run the suite (create -> verify -> update -> delete -> verify)")
            result = engine.call(lambda: engine.op_run_functional(suite), timeout=900)
            check("the suite ran", result is not None)
            if result is None:
                raise SystemExit(1)

            print()
            for t in result.tests:
                print(f"    {t.status:7} {t.name}  ({t.ms} ms, {len(t.steps)} steps)")
                for s in t.steps:
                    mark = {"PASSED": "ok ", "FAILED": "FAIL", "ERROR": "ERR", "SKIPPED": "skip"}
                    print(f"        {mark.get(s.status, '?'):4} {s.index:2}. {s.description}"
                          + (f"   [{s.error}]" if s.error else ""))
            print()

            check("RUN_ID looks like a run id", looks_like_run_id(result.run_id), result.run_id)
            check("ALL functional tests passed", result.ok,
                  f"{result.passed} passed / {result.failed} failed")
            check("the CRUD test passed", result.tests[0].status == "PASSED",
                  result.tests[0].failure)
            check("no leftover test data", not result.leftovers, str(result.leftovers))
            check("the created record was tracked",
                  bool(result.tests[0].created) and result.run_id in result.tests[0].created[0],
                  str(result.tests[0].created))
            check("every step of the CRUD test ran",
                  len(result.tests[0].steps) == len(crud.steps),
                  f"{len(result.tests[0].steps)}/{len(crud.steps)}")
            destructive_run = [s for s in result.tests[0].steps if s.destructive]
            check("destructive steps were actually performed", len(destructive_run) >= 3,
                  f"{len(destructive_run)}")

            print("[4] the application really changed and was really cleaned up")

            async def grid_rows():
                return await engine.page.evaluate(
                    """() => Array.from(document.querySelectorAll('table[role=grid] tbody tr'))
                                  .map(r => r.getAttribute('data-name'))""")

            rows = engine.call(lambda: grid_rows(), timeout=60) or []
            print(f"    grid now contains: {rows}")
            check("seeded records survived", "GP-001" in rows and "GP-002" in rows, str(rows))
            check("the test record is gone from the app",
                  not [r for r in rows if r and result.run_id in r], str(rows))

            print("\n[5] artefacts are separate from discovery health")
            check("functional-results.json written", paths.FUNCTIONAL_RESULTS_FILE.is_file())
            check("junit-functional.xml written", paths.FUNCTIONAL_JUNIT_FILE.is_file())
            check("discovery JUnit still exists and is untouched by it",
                  paths.JUNIT_FILE.is_file())
            fj = ET.parse(paths.FUNCTIONAL_JUNIT_FILE).getroot()
            dj = ET.parse(paths.JUNIT_FILE).getroot()
            check("the two JUnit files are different suites",
                  fj.get("name") != dj.get("name"),
                  f"{fj.get('name')} vs {dj.get('name')}")
            suite_el = fj.find("testsuite")
            names = [c.get("name") for c in suite_el.findall("testcase")]
            check("functional JUnit lists the tests by name",
                  any("create-verify" in (n or "") for n in names), str(names))
            props = {p.get("name"): p.get("value") for p in suite_el.find("properties")}
            check("functional JUnit carries the run id", props.get("runId") == result.run_id,
                  str(props))
            data = json.loads(paths.FUNCTIONAL_RESULTS_FILE.read_text(encoding="utf-8"))
            check("results JSON has per-step detail",
                  bool(data["tests"][0]["steps"][0].get("action")), str(data["tests"][0].keys()))
            check("no leftovers file when nothing is left",
                  not paths.LEFTOVERS_FILE.exists())

            print("\n[6] FAIL-CLOSED: a destructive step with a wrong state guard is refused")
            bad_state = Suite(name="guard", tests=[stepmod.FunctionalTest(
                name="destructive with wrong state guard", level="critical",
                steps=[
                    stepmod.Step(action="navigate", to_state="research-group-germplasms"),
                    stepmod.Step(action="click", destructive=True,
                                 state="research-group-variables",   # deliberately wrong
                                 target=stepmod.Target(testid="germplasm-add"),
                                 description="click Add while claiming to be elsewhere"),
                ])])
            r2 = engine.call(lambda: engine.op_run_functional(bad_state), timeout=300)
            step = r2.tests[0].steps[-1]
            check("the destructive step was refused", r2.tests[0].status == "FAILED")
            check("it failed on the state guard, before clicking",
                  "state guard failed" in (step.error or ""), step.error)
            check("expected vs actual recorded",
                  step.expected == "research-group-variables" and step.actual,
                  f"{step.expected!r} vs {step.actual!r}")

            print("\n[7] FAIL-CLOSED: an ambiguous destructive target is refused")
            ambiguous = Suite(name="ambiguous", tests=[stepmod.FunctionalTest(
                name="destructive with ambiguous target", level="critical",
                steps=[
                    stepmod.Step(action="navigate", to_state="research-group-germplasms"),
                    stepmod.Step(action="click", destructive=True,
                                 target=stepmod.Target(role="button", name="Delete"),
                                 description="click 'Delete' without saying which row"),
                ])])
            r3 = engine.call(lambda: engine.op_run_functional(ambiguous), timeout=300)
            step = r3.tests[0].steps[-1]
            check("the ambiguous destructive step was refused",
                  r3.tests[0].status == "FAILED")
            check("it refused because the target was not unique",
                  "refusing a destructive action" in (step.error or "")
                  and "matched" in (step.error or ""), step.error)
            rows_after = engine.call(lambda: grid_rows(), timeout=60) or []
            check("nothing was deleted by the refused step",
                  "GP-001" in rows_after and "GP-002" in rows_after, str(rows_after))

            print("\n[8] EVIDENCE on a genuine failure")
            failing = Suite(name="evidence", tests=[stepmod.FunctionalTest(
                name="assert something untrue", level="smoke",
                steps=[
                    stepmod.Step(action="navigate", to_state="research-group-germplasms"),
                    stepmod.Step(action="assert",
                                 target=stepmod.Target(testid="does-not-exist"),
                                 expect=stepmod.Expect(visible=True),
                                 description="assert a control that is not there"),
                ],
                cleanup=[])])
            r4 = engine.call(lambda: engine.op_run_functional(failing), timeout=300)
            t4 = r4.tests[0]
            ev = t4.evidence
            print(f"    evidence keys: {sorted(ev)}")
            check("the failure was reported", t4.status == "FAILED")
            check("evidence names the failed step", ev.get("failedStep") == 2, str(ev.get("failedStep")))
            check("evidence records the action", ev.get("action") == "assert")
            check("evidence records expected vs actual",
                  "expected" in ev and "actual" in ev, str({k: ev.get(k) for k in ("expected", "actual")}))
            check("evidence records the locator used", bool(ev.get("locator")), str(ev.get("locator")))
            check("evidence includes a screenshot",
                  bool(ev.get("screenshot")) and (HOME / ev["screenshot"]).is_file(),
                  str(ev.get("screenshot")))
            check("evidence includes a Playwright trace",
                  bool(ev.get("trace")) and (HOME / ev["trace"]).is_file(),
                  str(ev.get("trace")))
            check("evidence records where the page actually was",
                  bool((ev.get("pageAtFailure") or {}).get("url")), str(ev.get("pageAtFailure")))
            check("functional JUnit failure body carries the diagnosis",
                  "Expected:" in (ET.parse(paths.FUNCTIONAL_JUNIT_FILE).getroot()
                                  .find("testsuite").find("testcase")
                                  .find("failure").text or ""))

            print("\n[9] cleanup runs after a failure, and leftovers are reported")
            leftover_suite = Suite(name="leftover", tests=[stepmod.FunctionalTest(
                name="fails after creating a record", level="critical",
                steps=[
                    stepmod.Step(action="navigate", to_state="research-group-germplasms"),
                    stepmod.Step(action="click", target=stepmod.Target(testid="germplasm-add"),
                                 description="open the dialog"),
                    stepmod.Step(action="fill",
                                 target=stepmod.Target(role="textbox", name="Name"),
                                 value="{record}"),
                    stepmod.Step(action="click", destructive=True,
                                 target=stepmod.Target(testid="germplasm-save"),
                                 creates="{record}", description="create the record"),
                    stepmod.Step(action="assert",
                                 target=stepmod.Target(testid="does-not-exist"),
                                 expect=stepmod.Expect(visible=True),
                                 description="then fail on purpose"),
                ],
                cleanup=[
                    stepmod.Step(action="click", destructive=True, optional=True,
                                 target=stepmod.Target(
                                     role="button", name="Delete",
                                     within=stepmod.Target(role="row", name="{record}",
                                                           exact=False)),
                                 removes="{record}",
                                 description="delete the record even though the test failed"),
                ])])
            r5 = engine.call(lambda: engine.op_run_functional(leftover_suite), timeout=300)
            t5 = r5.tests[0]
            print(f"    status={t5.status} created={t5.created} leftovers={t5.leftovers}")
            check("the test failed as designed", t5.status == "FAILED")
            check("cleanup still ran", bool(t5.cleanup_steps),
                  f"{len(t5.cleanup_steps)} cleanup step(s)")
            check("cleanup removed the record despite the failure", not t5.leftovers,
                  str(t5.leftovers))
            rows_final = engine.call(lambda: grid_rows(), timeout=60) or []
            check("no test record remains in the app",
                  not [r for r in rows_final if r and r5.run_id in r], str(rows_final))

            print("\n[10] Safe Crawl is untouched and still read-only")
            src = (ROOT / "src" / "p1uid" / "crawler" / "bfs.py").read_text(encoding="utf-8")
            safety = (ROOT / "src" / "p1uid" / "crawler" / "safety.py").read_text(encoding="utf-8")
            check("the crawler does not import the functional runner",
                  "functional" not in src)
            check("the safety classifier does not import the functional runner",
                  "functional" not in safety)
            check("auto_clickable is still forced false for DANGEROUS/UNKNOWN",
                  "if classification in (DANGEROUS, UNKNOWN):" in safety)
        finally:
            engine.shutdown_blocking()

    print("\n[11] no secret leaked by the functional layer")
    leaked = [str(p.relative_to(HOME)) for p in HOME.rglob("*")
              if p.is_file() and p.stat().st_size < 40_000_000
              and PASSWORD.encode() in p.read_bytes()]
    check("password appears in no functional artefact", not leaked, "; ".join(leaked))

    print(f"\n{count - len(failures)}/{count} functional checks passed")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    rc = main()
    if "--keep" not in sys.argv:
        shutil.rmtree(HOME, ignore_errors=True)
    else:
        print(f"artifacts kept in {HOME}")
    sys.exit(rc)
