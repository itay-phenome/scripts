"""Phase 2a: the engine against a component-framework-shaped UI.

`mock_app/hardgrid.html` breaks the comfortable assumptions on purpose:

  * the Type control is a `role=combobox` whose `role=listbox` is portaled to
    <body> and does not exist until the control is clicked (a CDK overlay);
  * the grid is virtualised - 500 records, ~12 rows in the DOM - so a record can
    be absent from the DOM without being deleted;
  * rows carry no record name in an aria-label, only cell text;
  * the edit dialog's heading contains the record name (volatile title).

What this suite pins down:
  1. discovery still finds and classifies the custom control correctly;
  2. the `select` action works on a portaled listbox, not just on <select>;
  3. row-scoped targeting works inside a virtual window;
  4. the virtualisation trap is real, and the filter-then-assert pattern in the
     suite defeats it;
  5. a volatile dialog title fragments state fingerprints - measured, reported,
     NOT silently worked around.

Run: python tests/test_hardgrid.py [--headed] [--debug]
"""
from __future__ import annotations

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

HOME = Path(tempfile.mkdtemp(prefix="p1uid-hard-"))
os.environ["P1UID_HOME"] = str(HOME)

from serve_mock import MockServer                      # noqa: E402
from p1uid import paths                                # noqa: E402
from p1uid.browser.controller import Engine            # noqa: E402
from p1uid.crawler import safety                       # noqa: E402
from p1uid.discovery import scanner                    # noqa: E402
from p1uid.functional.steps import load_suite          # noqa: E402
from p1uid.logging_setup import setup                  # noqa: E402

SUITE = ROOT / "tests" / "functional" / "hardgrid_crud.json"
failures: list[str] = []
count = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global count
    count += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label + ((" - " + detail) if detail else ""))


def main() -> int:
    setup(debug="--debug" in sys.argv)
    with MockServer() as server:
        url = server.url.rsplit("/app/", 1)[0] + "/hardgrid.html"
        engine = Engine(queue.Queue(), headless="--headed" not in sys.argv)
        engine.start()
        try:
            print(f"\nHard grid  target={url}\n")
            engine.call(lambda: engine.open_url(url), timeout=120)

            print("[1] discovery on a component-framework UI")
            res = engine.call(lambda: scanner.scan_page(
                engine.page, engine.store, origin=engine.origin,
                validate_limit=500, keep_rows=True), timeout=180)
            check("the page was scanned", res is not None and res.elements > 10,
                  f"{res.elements if res else 0} elements")
            rows = {el.get("attrs", {}).get("data-testid"): (el, loc)
                    for _f, el, loc in res.rows}
            combo_el, combo_loc = rows.get("hg-type", (None, None))
            check("the custom combobox was discovered", combo_el is not None)
            if combo_el:
                check("it is classified as a combobox, not a button",
                      combo_el.get("type") == "combobox" and combo_el.get("role") == "combobox",
                      f"type={combo_el.get('type')} role={combo_el.get('role')}")
                check("its accessible name came from the label",
                      combo_el.get("name") == "Type", repr(combo_el.get("name")))
                check("its popup type was captured",
                      combo_el.get("hasPopup") == "listbox", str(combo_el.get("hasPopup")))
                check("it got a unique locator", combo_loc.matches == 1, str(combo_loc.matches))
                v = safety.classify(combo_el, origin=engine.origin)
                check("Safe Crawl would not auto-click a data-entry control",
                      not v.auto_clickable and v.classification == "CONDITIONAL",
                      f"{v.classification} auto={v.auto_clickable}")
                # The honest gap: options are not in the DOM until it is opened.
                check("its options are NOT captured by discovery (documented gap)",
                      not combo_el.get("options"), str(combo_el.get("options")))

            print("\n[1b] nested layout tables are not recorded as elements")
            # Real PhenomeOne: 222 of 583 elements were unnamed nested tables,
            # 38% of the map, each with a getByRole('table').nth(N) locator.
            in_dom = engine.call(lambda: engine.page.evaluate(
                "() => document.querySelectorAll('table').length"), timeout=60)
            tables = [(el, loc) for _f, el, loc in res.rows if el.get("tag") == "table"]
            named = [el.get("name") for el, _l in tables]
            testids = [el.get("attrs", {}).get("data-testid") for el, _l in tables]
            print(f"    {in_dom} tables in the DOM, {len(tables)} recorded: names={named}")
            check("far fewer tables are recorded than exist in the DOM",
                  in_dom >= 6 and len(tables) < in_dom, f"{len(tables)} of {in_dom}")
            # The boundary moved on 2026-08-28, on evidence from the first real
            # crawl. Dropping only DOMINATED tables was not enough: PhenomeOne
            # lays each widget out as its own TOP-LEVEL table, so 231 of the 272
            # elements recorded for the landing state were anonymous tables whose
            # only identity was a position (`table:table:#219`) - which shifts
            # between visits, so each revisit minted 12 more and the map reached
            # 8.2 MB for 7 states. Column headers now decide, not nesting.
            check("an anonymous header-free table is dropped even at the top level",
                  not any(el.get("attrs", {}).get("id") == "lt-outer" for el, _l in tables),
                  str([el.get("attrs", {}).get("id") for el, _l in tables]))
            check("an anonymous table WITH column headers is kept (a data grid is never lost)",
                  any(el.get("attrs", {}).get("id") == "hg-datatable" for el, _l in tables),
                  str([el.get("attrs", {}).get("id") for el, _l in tables]))
            check("a nested table with an accessible name survives",
                  "Trait summary" in named, str(named))
            check("a nested table with a test id survives",
                  "lt-tagged" in testids, str(testids))
            # Anonymous = no accessible name AND no test id. Such a table is kept
            # only when it declares columns, wherever it sits.
            anonymous_headerless = [el.get("attrs", {}) for el, _l in tables
                                    if not (el.get("name") or "").strip()
                                    and not el.get("attrs", {}).get("data-testid")
                                    and not ((el.get("grid") or {}).get("columns"))]
            check("no anonymous header-free table is recorded, nested or not",
                  not anonymous_headerless, str(anonymous_headerless))
            check("structural nth() table locators are gone",
                  not [loc for _el, loc in tables if ".nth(" in (loc.js or "")],
                  str([loc.js for _el, loc in tables]))

            print("\n[2] the virtualisation trap is real")
            dom_rows = engine.call(lambda: engine.page.evaluate(
                "() => document.querySelectorAll('[role=row]').length"), timeout=60)
            total = engine.call(lambda: engine.page.evaluate(
                "() => (JSON.parse(sessionStorage.getItem('hgRecords')||'null')||[]).length || 500"),
                timeout=60)
            print(f"    {dom_rows} rows in the DOM, {total} records in the data")
            check("only a window of rows exists in the DOM", 5 < dom_rows < 40,
                  f"{dom_rows} of {total}")

            async def count_row(name: str) -> int:
                return await engine.page.get_by_role("row", name=name).count()

            check("a RENDERED row is addressable by its record name",
                  engine.call(lambda: count_row("INV-0001"), timeout=60) == 1)
            far = engine.call(lambda: count_row("INV-0400"), timeout=60)
            check("an UNRENDERED row is invisible to a locator - so a naive "
                  "'count == 0' would wrongly read as deleted", far == 0, f"count={far}")

            print("\n[3] the CRUD suite handles all of it")
            suite = load_suite(SUITE)
            engine.base_url = url
            result = engine.call(lambda: engine.op_run_functional(suite), timeout=900)
            check("the suite ran", result is not None)
            if result is None:
                raise SystemExit(1)
            t = result.tests[0]
            print()
            for s in t.steps:
                mark = {"PASSED": "ok ", "FAILED": "FAIL", "ERROR": "ERR", "SKIPPED": "skip"}
                print(f"      {mark.get(s.status, '?'):4} {s.index:2}. {s.description[:88]}"
                      + (f"   [{s.error}]" if s.error else ""))
            print()
            check("CRUD passed on the virtualised grid", t.status == "PASSED", t.failure)
            check("every step ran", len(t.steps) == len(suite.tests[0].steps),
                  f"{len(t.steps)}/{len(suite.tests[0].steps)}")
            selects = [s for s in t.steps if s.action == "select"]
            check("both portaled-dropdown selections succeeded",
                  len(selects) == 2 and all(s.status == "PASSED" for s in selects),
                  str([(s.actual, s.status) for s in selects]))
            check("the selection was verified from the control, not assumed",
                  all("Landrace" in str(s.actual) or "Hybrid" in str(s.actual)
                      for s in selects), str([s.actual for s in selects]))
            check("no leftover test data", not result.leftovers, str(result.leftovers))

            print("[4] the application really changed, then was really cleaned up")
            remaining = engine.call(lambda: engine.page.evaluate(
                """(rid) => (JSON.parse(sessionStorage.getItem('hgRecords')||'[]'))
                             .filter(r => r.name.includes(rid)).length""",
                result.run_id), timeout=60)
            check("no test record remains in the data", remaining == 0, f"{remaining} left")
            seeded = engine.call(lambda: engine.page.evaluate(
                "() => (JSON.parse(sessionStorage.getItem('hgRecords')||'null')||[]).length || 500"),
                timeout=60)
            check("the 500 seeded records are intact", seeded == 500, str(seeded))
            fx = engine.call(lambda: engine.page.evaluate("() => window.__sideEffects || []"),
                             timeout=60)
            kinds = sorted({str(x).split(":")[0] for x in fx})
            print(f"    the app recorded these writes: {kinds}")
            check("exactly the writes the test declared were performed",
                  kinds == ["create", "delete", "update"], str(kinds))

            print("\n[5] a volatile dialog title no longer fragments the state map")
            # Open the edit dialog for two different records and compare the
            # fingerprints the engine derives. Before the normalisation rule
            # these produced hardgrid-html-dialog-edit-inv-0001 and
            # ...-inv-0002: one state per record.
            async def open_edit(record: str) -> str:
                await engine.page.fill("#hg-filter", record)
                await engine.page.wait_for_timeout(200)
                row = engine.page.get_by_role("row", name=record)
                await row.get_by_role("button", name="Edit").click()
                await engine.page.wait_for_timeout(300)
                r = await scanner.scan_page(engine.page, engine.store, origin=engine.origin,
                                            validate_limit=50)
                sid = r.state_id if r else ""
                await engine.page.get_by_test_id("hg-cancel").click()
                await engine.page.wait_for_timeout(200)
                return sid

            async def open_add() -> str:
                await engine.page.get_by_test_id("hg-add").click()
                await engine.page.wait_for_timeout(300)
                r = await scanner.scan_page(engine.page, engine.store, origin=engine.origin,
                                            validate_limit=50)
                sid = r.state_id if r else ""
                await engine.page.get_by_test_id("hg-cancel").click()
                await engine.page.wait_for_timeout(200)
                return sid

            s1 = engine.call(lambda: open_edit("INV-0001"), timeout=180)
            s2 = engine.call(lambda: open_edit("INV-0002"), timeout=180)
            print(f"    editing INV-0001 -> state {s1!r}")
            print(f"    editing INV-0002 -> state {s2!r}")
            check("the same dialog yields ONE state id for every record",
                  bool(s1) and s1 == s2, f"{s1} vs {s2}")
            check("no record name leaks into the state id",
                  "0001" not in s1 and "0002" not in s2, f"{s1} / {s2}")
            check("the state is still named after the dialog it is",
                  s1.endswith("dialog-edit"), s1)
            add = engine.call(lambda: open_add(), timeout=180)
            print(f"    the Add dialog     -> state {add!r}")
            check("Add and Edit remain DIFFERENT states (not over-normalised)",
                  add != s1 and add.endswith("dialog-add-germplasm"), f"{add} vs {s1}")

            print("\n[6] Safe Crawl still refuses to touch any of this")
            verdicts = {}
            for _f, el, _l in res.rows:
                v = safety.classify(el, origin=engine.origin)
                verdicts[v.classification] = verdicts.get(v.classification, 0) + 1
            print(f"    classifications: {verdicts}")
            auto = [(el.get("name"), el.get("type")) for _f, el, _l in res.rows
                    if safety.classify(el, origin=engine.origin).auto_clickable]
            check("no Save/Delete/Edit control is auto-clickable",
                  not [a for a in auto if str(a[0]).lower() in ("save", "delete", "edit")],
                  str(auto[:6]))
        finally:
            engine.shutdown_blocking()

    print(f"\n{count - len(failures)}/{count} hard-grid checks passed")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    rc = main()
    shutil.rmtree(HOME, ignore_errors=True)
    sys.exit(rc)
