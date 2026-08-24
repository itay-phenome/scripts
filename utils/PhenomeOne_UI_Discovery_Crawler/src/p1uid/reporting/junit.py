"""JUnit XML for Jenkins (spec 29).

Turns discovery health into something a CI job can trend and fail on:

* one test case per UI state (passes when every element resolved uniquely);
* a failure per LOW-confidence locator, carrying the recommended `data-testid`;
* a failure per UNSTABLE LOCATOR (it changed between runs);
* skipped cases for locators that could not be validated because the element
  was hidden at scan time.

Jenkins then shows "12 new weak locators in this build" without anyone reading
a JSON file.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from ..logging_setup import get
from ..store.uimap import UNSTABLE_FLAG

log = get("reporting.junit")


def build(store: Any, suite_name: str = "PhenomeOne UI Discovery") -> ET.ElementTree:
    counts = store.counts()
    states: dict[str, Any] = store.data.get("states") or {}

    tests = failures = skipped = 0
    suite = ET.Element("testsuite", {
        "name": suite_name,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "hostname": "discovery",
    })

    props = ET.SubElement(suite, "properties")
    for key, value in (("states", counts["states"]), ("elements", counts["elements"]),
                       ("navigationPaths", counts["navigationPaths"]),
                       ("locatorsHigh", counts["confidence"].get("HIGH", 0)),
                       ("locatorsMedium", counts["confidence"].get("MEDIUM", 0)),
                       ("locatorsLow", counts["confidence"].get("LOW", 0))):
        ET.SubElement(props, "property", {"name": key, "value": str(value)})

    for sid, st in sorted(states.items()):
        els: dict[str, Any] = st.get("elements") or {}
        classname = f"ui-map.{sid}"

        low = [e for e in els.values() if e.get("confidence") == "LOW"]
        unstable = [e for e in els.values() if UNSTABLE_FLAG in (e.get("flags") or [])]
        deferred = [e for e in els.values()
                    if (e.get("locator") or {}).get("validation") == "deferred-hidden"]

        tests += 1
        case = ET.SubElement(suite, "testcase",
                             {"classname": classname, "name": f"state has usable locators "
                                                              f"({len(els)} elements)"})
        if low:
            failures += 1
            detail = "\n".join(
                f"{e.get('logicalName')} [{e.get('type')}]: {(e.get('locator') or {}).get('js')} "
                f"matched {(e.get('locator') or {}).get('matches')} - "
                f"{e.get('recommendation') or 'no recommendation'}"
                for e in sorted(low, key=lambda x: str(x.get("logicalName")))[:50])
            fail = ET.SubElement(case, "failure", {
                "type": "WeakLocator",
                "message": f"{len(low)} element(s) in {sid} have no unique, stable locator"})
            fail.text = detail

        if unstable:
            tests += 1
            ucase = ET.SubElement(suite, "testcase",
                                  {"classname": classname, "name": "locators are stable"})
            failures += 1
            f2 = ET.SubElement(ucase, "failure", {
                "type": "UnstableLocator",
                "message": f"{len(unstable)} locator(s) in {sid} changed between runs"})
            f2.text = "\n".join(
                f"{e.get('logicalName')}: " + " -> ".join(h.get("js", "") for h in
                                                          (e.get("locatorHistory") or [])[-3:])
                for e in unstable[:50])

        if deferred:
            tests += 1
            dcase = ET.SubElement(suite, "testcase",
                                  {"classname": classname, "name": "all locators validated live"})
            skipped += 1
            ET.SubElement(dcase, "skipped", {
                "message": f"{len(deferred)} locator(s) not validated: the element was hidden "
                           f"at scan time (open the dialog/menu and re-scan to confirm)"})

    suite.set("tests", str(tests))
    suite.set("failures", str(failures))
    suite.set("errors", "0")
    suite.set("skipped", str(skipped))
    suites = ET.Element("testsuites", {"name": suite_name, "tests": str(tests),
                                       "failures": str(failures)})
    suites.append(suite)
    return ET.ElementTree(suites)


def write(store: Any, path: Path) -> dict[str, int]:
    tree = build(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tmp = path.with_suffix(".tmp")
    tree.write(tmp, encoding="utf-8", xml_declaration=True)
    tmp.replace(path)
    root = tree.getroot()
    result = {"tests": int(root.get("tests", 0)), "failures": int(root.get("failures", 0))}
    log.info("JUnit report written -> %s (%d tests, %d failures)", path.name,
             result["tests"], result["failures"])
    return result
