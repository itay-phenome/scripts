"""JUnit XML for FUNCTIONAL test results.

Deliberately a different file from `junit.py`, which reports discovery health
(weak/unstable locators). Mixing them would let a locator-quality warning look
like a broken feature, or hide a broken feature among locator noise.

    reports/junit-discovery.xml   is the UI map healthy?
    reports/junit-functional.xml  does the application still work?

A failure carries the whole diagnosis in its body: the failed step, the locator
used, expected vs actual, where the page actually was, and any console / page /
network errors - so a Jenkins failure is actionable without re-running.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from ..logging_setup import get
from ..functional.results import ERROR, FAILED, SKIPPED, SuiteResult

log = get("reporting.junit-functional")


def _failure_body(test: Any) -> str:
    lines: list[str] = []
    ev = test.evidence or {}
    if test.failed_step is not None:
        lines.append(f"Failed at step {test.failed_step}: {ev.get('step', '')}")
    if ev.get("action"):
        lines.append(f"Action:   {ev['action']}")
    if ev.get("target"):
        lines.append(f"Target:   {ev['target']}")
    if ev.get("locator"):
        lines.append(f"Locator:  {ev['locator']}")
    if "expected" in ev or "actual" in ev:
        lines.append(f"Expected: {ev.get('expected')!r}")
        lines.append(f"Actual:   {ev.get('actual')!r}")
    if ev.get("error"):
        lines.append(f"Error:    {ev['error']}")
    page = ev.get("pageAtFailure") or {}
    if page:
        lines.append(f"Page:     {page.get('url', '')} | title={page.get('title', '')!r}"
                     f" | heading={str(page.get('heading', ''))[:60]!r}")
    for label, key in (("Console", "console"), ("Page errors", "pageErrors"),
                       ("Network failures", "networkFailures")):
        items = ev.get(key) or []
        if items:
            lines.append(f"{label} ({len(items)}):")
            lines += [f"  {json.dumps(i, ensure_ascii=False)}" for i in items[:10]]
    for label, key in (("Screenshot", "screenshot"), ("Trace", "trace")):
        if ev.get(key):
            lines.append(f"{label}: {ev[key]}")
    if test.leftovers:
        lines.append(f"LEFTOVER TEST DATA: {', '.join(test.leftovers)}")

    lines.append("")
    lines.append("Steps:")
    for s in test.steps:
        mark = {"PASSED": "ok  ", "FAILED": "FAIL", "ERROR": "ERR "}.get(s.status, "    ")
        lines.append(f"  {mark} {s.index}. {s.description} ({s.ms} ms)")
        if s.error:
            lines.append(f"        {s.error}")
    if test.cleanup_steps:
        lines.append("Cleanup:")
        for s in test.cleanup_steps:
            mark = "ok  " if s.status == "PASSED" else "FAIL"
            lines.append(f"  {mark} {s.index}. {s.description}")
            if s.error:
                lines.append(f"        {s.error}")
    return "\n".join(lines)


def build(result: SuiteResult) -> ET.ElementTree:
    suite = ET.Element("testsuite", {
        "name": f"PhenomeOne functional ({result.suite})",
        "tests": str(len(result.tests)),
        "failures": str(result.failed),
        "errors": "0",
        "skipped": str(result.skipped),
        "time": f"{result.ms / 1000:.3f}",
        "timestamp": result.started_at,
        "hostname": "functional",
    })
    props = ET.SubElement(suite, "properties")
    for key, value in (("runId", result.run_id), ("environment", result.environment),
                       ("leftoverRecords", str(len(result.leftovers))),
                       ("passed", str(result.passed)), ("failed", str(result.failed))):
        ET.SubElement(props, "property", {"name": key, "value": value or ""})

    for test in result.tests:
        case = ET.SubElement(suite, "testcase", {
            "classname": f"functional.{test.level}",
            "name": test.name,
            "time": f"{test.ms / 1000:.3f}",
        })
        if test.status in (FAILED, ERROR):
            node = ET.SubElement(case, "failure", {
                "type": "FunctionalFailure" if test.status == FAILED else "ExecutionError",
                "message": (test.failure or "test failed")[:300],
            })
            node.text = _failure_body(test)
        elif test.status == SKIPPED:
            ET.SubElement(case, "skipped", {"message": test.failure or "skipped"})
        elif test.leftovers:
            # The test passed but left residue: surface it without failing the build.
            out = ET.SubElement(case, "system-out")
            out.text = f"LEFTOVER TEST DATA: {', '.join(test.leftovers)}"

    if result.aborted:
        case = ET.SubElement(suite, "testcase",
                             {"classname": "functional", "name": "suite completed"})
        node = ET.SubElement(case, "failure", {"type": "SuiteAborted",
                                               "message": result.aborted})
        node.text = f"The suite stopped early: {result.aborted}"
        suite.set("tests", str(len(result.tests) + 1))
        suite.set("failures", str(result.failed + 1))

    suites = ET.Element("testsuites", {
        "name": "PhenomeOne functional",
        "tests": suite.get("tests", "0"),
        "failures": suite.get("failures", "0"),
        "time": f"{result.ms / 1000:.3f}",
    })
    suites.append(suite)
    return ET.ElementTree(suites)


def write(result: SuiteResult, path: Path) -> dict[str, int]:
    tree = build(result)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tmp = path.with_suffix(".tmp")
    tree.write(tmp, encoding="utf-8", xml_declaration=True)
    tmp.replace(path)
    root = tree.getroot()
    out = {"tests": int(root.get("tests", 0)), "failures": int(root.get("failures", 0))}
    log.info("Functional JUnit -> %s (%d tests, %d failures)", path.name,
             out["tests"], out["failures"])
    return out
