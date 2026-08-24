"""Workflow recording, UI diff, test generation and the Jenkins JUnit report.

These are the "consumer" phases: what the discovery engine hands to the test
suite. Each is checked against real output produced from the mock app, not
fixtures, so a schema change breaks the test rather than the pipeline.

Run: python tests/test_pipeline.py [--headed] [--debug]
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import queue
import shutil
import subprocess
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

HOME = Path(tempfile.mkdtemp(prefix="p1uid-pipe-"))
os.environ["P1UID_HOME"] = str(HOME)

from serve_mock import MockServer                      # noqa: E402
from p1uid import codegen, diff as uidiff, paths       # noqa: E402
from p1uid.browser.controller import Engine            # noqa: E402
from p1uid.logging_setup import setup                  # noqa: E402
from p1uid.reporting import junit                      # noqa: E402

PASSWORD = "PipelinePass!-secret"
failures: list[str] = []
count = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global count
    count += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label + ((" - " + detail) if detail else ""))


# ============================================================== workflows
def phase_workflow(engine: Engine, server) -> None:
    print("\n[1] workflow recording during training")
    engine.call(lambda: engine.op_start_training(), timeout=120)
    engine.call(lambda: engine.op_begin_workflow("Open Germplasms"), timeout=60)

    async def drive() -> None:
        page = engine.page
        for action in (
            lambda: page.get_by_role("link", name="Research Groups").click(),
            lambda: page.get_by_role("link", name="Research Group ABC").click(),
            lambda: page.get_by_role("tab", name="Germplasms").click(),
            lambda: page.get_by_test_id("germplasm-add").click(),
            lambda: page.get_by_role("button", name="Close dialog").click(),
        ):
            await action()
            await asyncio.sleep(1.0)
        await asyncio.sleep(0.8)

    engine.call(lambda: drive(), timeout=180)
    engine.call(lambda: engine.op_end_workflow(), timeout=60)
    engine.call(lambda: engine.op_stop_training(), timeout=180)

    check("workflows.json written", paths.WORKFLOWS_FILE.is_file())
    data = json.loads(paths.WORKFLOWS_FILE.read_text(encoding="utf-8"))
    wf = (data.get("workflows") or {}).get("Open Germplasms")
    check("the named workflow was recorded", wf is not None, str(list(data.get("workflows", {}))))
    if not wf:
        return
    print(f"\n  workflow {wf['name']!r}: {wf['stepCount']} steps "
          f"({wf['startState']} -> {wf['endState']})")
    for st in wf["steps"]:
        print(f"    {st['n']}. {st['kind']:9} {st['label']:24} {st['from']} -> {st['to']}")
    print()
    check("workflow has the steps we performed", wf["stepCount"] >= 3, str(wf["stepCount"]))
    check("workflow steps carry a locator",
          all(s["locator"] for s in wf["steps"]),
          str([s["label"] for s in wf["steps"] if not s["locator"]]))
    check("workflow reached the Germplasms tab",
          any("germplasms" in s["to"] for s in wf["steps"]), wf["endState"])
    check("workflow captured the dialog step",
          any("dialog" in s["to"] for s in wf["steps"]),
          " | ".join(s["to"] for s in wf["steps"]))
    check("no field values were stored in the workflow",
          PASSWORD not in json.dumps(data) and "GP-001" not in json.dumps(data))

    # Re-recording must merge, not duplicate.
    engine.call(lambda: engine.op_start_training(), timeout=120)
    engine.call(lambda: engine.op_begin_workflow("Open Germplasms"), timeout=60)

    async def drive2() -> None:
        await engine.page.get_by_role("link", name="Research Groups").click()
        await asyncio.sleep(1.0)

    engine.call(lambda: drive2(), timeout=120)
    engine.call(lambda: engine.op_stop_training(), timeout=180)
    data2 = json.loads(paths.WORKFLOWS_FILE.read_text(encoding="utf-8"))
    wf2 = data2["workflows"]["Open Germplasms"]
    check("re-recording a workflow merges instead of duplicating",
          len(data2["workflows"]) == 1 and wf2["timesRecorded"] == 2,
          f"{len(data2['workflows'])} workflows, recorded {wf2['timesRecorded']}x")
    check("workflow step-count change is reported", "stepCountChanged" in wf2,
          str(wf2.get("stepCountChanged")))


# =================================================================== diff
def phase_diff() -> None:
    print("[2] UI diff")
    current = json.loads(paths.UI_MAP_FILE.read_text(encoding="utf-8"))

    # Baseline = current with deliberate edits, so every diff kind is exercised.
    baseline = copy.deepcopy(current)
    sids = sorted(baseline["states"])
    removed_state = sids[-1]
    baseline["states"].pop(removed_state)                       # -> appears as ADDED in current
    target = sids[0]
    els = baseline["states"][target]["elements"]
    ghost_key = "button:button:ghost control"
    els[ghost_key] = {"key": ghost_key, "logicalName": "Ghost Button", "type": "button",
                      "confidence": "HIGH", "locator": {"js": "getByRole('button', "
                                                              "{ name: 'Ghost' })"}}
    victim = next(k for k in els if k != ghost_key)
    els[victim] = dict(els[victim])
    els[victim]["locator"] = dict(els[victim].get("locator") or {}, js="locator('#old-selector')")
    els[victim]["confidence"] = "LOW"
    baseline["navigation"] = {}

    base_path = HOME / "baseline-ui-map.json"
    base_path.write_text(json.dumps(baseline), encoding="utf-8")

    d = uidiff.diff_maps(baseline, current)
    s = d["summary"]
    print(f"  summary: {s}")
    check("diff detects the added state", removed_state in d["states"]["added"],
          str(d["states"]["added"]))
    check("diff detects the removed element", s["elementsRemoved"] >= 1, str(s))
    check("diff detects a changed locator", s["locatorsChanged"] >= 1, str(s))
    check("diff detects added navigation paths", s["pathsAdded"] >= 1, str(s))
    check("diff reports changes overall", d["hasChanges"])

    lines = uidiff.render_lines(d)
    print("  --- diff (first 8 lines) ---")
    for line in lines[:8]:
        print("   " + line)
    check("diff renders +/-/~ lines",
          any(l.startswith("+") for l in lines) and any(l.startswith("~") for l in lines))

    uidiff.write_reports(d, paths.DIFF_JSON_FILE, paths.DIFF_REPORT_FILE)
    check("ui-diff.json written", paths.DIFF_JSON_FILE.is_file())
    check("ui-diff.html written", paths.DIFF_REPORT_FILE.is_file())
    html = paths.DIFF_REPORT_FILE.read_text(encoding="utf-8")
    check("diff report is self-contained", "<script" not in html and "http://" not in html)
    check("diff report highlights locator changes", "test-breaking" in html)

    same = uidiff.diff_maps(current, copy.deepcopy(current))
    check("a map does not differ from itself", not same["hasChanges"], str(same["summary"]))

    # CLI wiring + exit codes
    r = subprocess.run([sys.executable, "main.py", "--diff", str(base_path),
                        str(paths.UI_MAP_FILE)], cwd=str(ROOT), capture_output=True, text=True,
                       env={**os.environ, "P1UID_HOME": str(HOME)}, timeout=180)
    check("CLI --diff exits 5 when maps differ", r.returncode == 5, f"rc={r.returncode}")
    r = subprocess.run([sys.executable, "main.py", "--diff", str(paths.UI_MAP_FILE),
                        str(paths.UI_MAP_FILE)], cwd=str(ROOT), capture_output=True, text=True,
                       env={**os.environ, "P1UID_HOME": str(HOME)}, timeout=180)
    check("CLI --diff exits 0 when maps match", r.returncode == 0, f"rc={r.returncode}")


# ================================================================ codegen
def phase_codegen() -> None:
    print("\n[3] test generation")
    ui_map = json.loads(paths.UI_MAP_FILE.read_text(encoding="utf-8"))
    nav = json.loads(paths.NAV_GRAPH_FILE.read_text(encoding="utf-8"))
    stats = codegen.generate(ui_map, paths.GENERATED_DIR, nav_graph=nav)
    print(f"  generated {stats['locators']} locators over {stats['states']} states, "
          f"{stats['skippedLow']} skipped")

    for name in ("ui-map.ts", "navigation.ts", "smoke.spec.ts", "ui_map.py", "README.md"):
        check(f"{name} generated", (paths.GENERATED_DIR / name).is_file())

    ts = (paths.GENERATED_DIR / "ui-map.ts").read_text(encoding="utf-8")
    check("TS map has locators", "getByRole(" in ts or "getByTestId(" in ts)
    check("TS map documents skipped elements", "// SKIPPED" in ts or stats["skippedLow"] == 0)
    check("TS map carries no LOW locator as usable",
          "LOW */" not in ts.replace("- LOW */", "- SKIPPED */"))

    nav_ts = (paths.GENERATED_DIR / "navigation.ts").read_text(encoding="utf-8")
    check("navigation helper generated", "goToState" in nav_ts and "NAV_STEPS" in nav_ts)
    check("navigation includes a real path",
          "germplasms" in nav_ts.lower())

    spec = (paths.GENERATED_DIR / "smoke.spec.ts").read_text(encoding="utf-8")
    check("smoke spec has tests", spec.count("test(") >= 2, str(spec.count("test(")))
    check("smoke spec asserts visibility", "toBeVisible()" in spec)

    py = (paths.GENERATED_DIR / "ui_map.py").read_text(encoding="utf-8")
    check("python page objects generated", "class " in py and "def " in py)
    compiled = True
    try:
        compile(py, "ui_map.py", "exec")
    except SyntaxError as exc:
        compiled = False
        print(f"    python syntax error: {exc}")
    check("generated python is syntactically valid", compiled)

    node = shutil.which("node")
    if node:
        ok = True
        for f in ("ui-map.ts", "navigation.ts", "smoke.spec.ts"):
            # Strip TS-only syntax is overkill; just check balanced braces parse as JS
            # by wrapping in a comment-safe check of bracket balance.
            text = (paths.GENERATED_DIR / f).read_text(encoding="utf-8")
            if text.count("{") != text.count("}") or text.count("(") != text.count(")"):
                ok = False
                print(f"    unbalanced brackets in {f}")
        check("generated TS files are bracket-balanced", ok)
    else:
        print("    (node not found; skipping TS bracket check)")

    check("no secret leaked into generated code",
          PASSWORD not in ts + nav_ts + spec + py)


# ================================================================== junit
def phase_junit(engine: Engine) -> None:
    print("\n[4] Jenkins JUnit report")
    result = junit.write(engine.store, paths.JUNIT_FILE)
    check("junit-discovery.xml written", paths.JUNIT_FILE.is_file())
    tree = ET.parse(paths.JUNIT_FILE)
    root = tree.getroot()
    check("XML parses as testsuites", root.tag == "testsuites", root.tag)
    suite = root.find("testsuite")
    cases = suite.findall("testcase")
    print(f"  {result['tests']} test cases, {result['failures']} failures")
    check("one case per state at least", len(cases) >= 3, str(len(cases)))
    props = {p.get("name"): p.get("value") for p in suite.find("properties")}
    check("properties carry the totals", "states" in props and "locatorsLow" in props, str(props))
    weak = [c for c in cases if c.find("failure") is not None]
    check("weak locators surface as failures", bool(weak) or props["locatorsLow"] == "0",
          f"{len(weak)} failing cases, {props['locatorsLow']} LOW")
    if weak:
        msg = weak[0].find("failure").get("message")
        check("failure message is actionable", "locator" in msg.lower(), msg)
        check("failure body names the element and the fix",
              "data-testid" in (weak[0].find("failure").text or "")
              or "recommendation" in (weak[0].find("failure").text or ""),
              (weak[0].find("failure").text or "")[:120])

    # CI gate exit code
    r = subprocess.run([sys.executable, "main.py", "--cli", "--report-only", "--fail-on-low", "0"],
                       cwd=str(ROOT), capture_output=True, text=True,
                       env={**os.environ, "P1UID_HOME": str(HOME)}, timeout=180)
    low = int(props["locatorsLow"])
    expect = 4 if low > 0 else 0
    check(f"CI gate --fail-on-low 0 exits {expect} (LOW={low})", r.returncode == expect,
          f"rc={r.returncode}")
    r = subprocess.run([sys.executable, "main.py", "--cli", "--report-only",
                        "--fail-on-low", "9999"], cwd=str(ROOT), capture_output=True, text=True,
                       env={**os.environ, "P1UID_HOME": str(HOME)}, timeout=180)
    check("CI gate passes under a generous threshold", r.returncode == 0, f"rc={r.returncode}")


def main() -> int:
    setup(debug="--debug" in sys.argv)
    with MockServer() as server:
        events: "queue.Queue[dict]" = queue.Queue()
        engine = Engine(events, headless="--headed" not in sys.argv, generate_tests=True)
        engine.start()
        try:
            print(f"\nPipeline test  home={HOME}\n")
            engine.call(lambda: engine.op_login(server.url, "t@e.st", PASSWORD), timeout=180)
            check("logged into the mock app", engine.authenticated)
            engine.call(lambda: engine.op_scan(), timeout=180)
            phase_workflow(engine, server)
            phase_diff()
            phase_codegen()
            phase_junit(engine)
            check("engine auto-generated tests when asked",
                  (paths.GENERATED_DIR / "ui-map.ts").is_file())
        finally:
            engine.shutdown_blocking()

    leaked = [str(p.relative_to(HOME)) for p in HOME.rglob("*")
              if p.is_file() and PASSWORD.encode() in p.read_bytes()]
    check("no secret written anywhere in the pipeline", not leaked, "; ".join(leaked))

    print(f"\n{count - len(failures)}/{count} pipeline checks passed")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    rc = main()
    shutil.rmtree(HOME, ignore_errors=True)
    sys.exit(rc)
