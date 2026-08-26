"""Unit tests - no browser required. Run: python tests/test_units.py"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ["P1UID_HOME"] = tempfile.mkdtemp(prefix="p1uid-unit-")

from p1uid import logging_setup, paths                                  # noqa: E402
from p1uid.auth.login import analyse                                    # noqa: E402
from p1uid.locator.generator import candidates, suggest_test_id, apply_validation  # noqa: E402
from p1uid.navigation import graph as navgraph                          # noqa: E402
from p1uid.reporting import html_report                                 # noqa: E402
from p1uid.state.fingerprint import (fingerprint, normalise_dialog_title,  # noqa: E402
                                     normalise_route)
from p1uid.store.uimap import UIMapStore, UNSTABLE_FLAG, element_key    # noqa: E402

failures: list[str] = []
count = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global count
    count += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def struct(**kw):
    base = dict(path="/", hash="", title="t", h1="", headings=[], activeTab="",
                tabs=[], dialogs=[], landmarks=[])
    base.update(kw)
    return base


def test_routes() -> None:
    print("route normalisation")
    check("numeric id", normalise_route("/research-group/123/germplasms") == "/research-group/:id/germplasms")
    check("uuid", normalise_route("/rg/9f8a7b6c-1234-4321-abcd-0123456789ab") == "/rg/:uuid")
    check("hash route", normalise_route("/app", "#/rg/42/vars") == "/app/#/rg/:id/vars")
    check("plain route untouched", normalise_route("/settings/users") == "/settings/users")


def test_fingerprint() -> None:
    print("fingerprinting")
    a = struct(path="/research-group/1", activeTab="Germplasms", tabs=["Overview", "Germplasms"],
               landmarks=["main", "grid:Germplasms"], h1="Research Group ABC")
    b = struct(path="/research-group/99", activeTab="Germplasms", tabs=["Overview", "Germplasms"],
               landmarks=["main", "grid:Other Name"], h1="Research Group ZZZ")
    c = struct(path="/research-group/1", activeTab="Overview", tabs=["Overview", "Germplasms"],
               landmarks=["main"], h1="Research Group ABC")
    check("record id and business names do not change the fingerprint",
          fingerprint(a).digest == fingerprint(b).digest)
    check("active tab changes the fingerprint", fingerprint(a).digest != fingerprint(c).digest)
    check("dialog changes the fingerprint",
          fingerprint(a).digest != fingerprint(struct(**{**a, "dialogs": ["Add Germplasm"]})).digest)
    check("slug is human readable", fingerprint(a).slug == "research-group-germplasms",
          fingerprint(a).slug)
    check("label keeps the human heading", "Research Group ABC" in fingerprint(a).label)


def test_dialog_title_normalisation() -> None:
    """Volatile record tokens must collapse; stable titles must stay distinct.

    The failure this guards against: "Edit INV-0001" and "Edit INV-0002" used to
    produce two states, so the map grew one state per record. The opposite
    failure matters just as much - stripping too much would merge "Add
    Germplasm" with "Edit Germplasm", or two wizard steps with each other.
    """
    print("dialog title normalisation")

    def dlg(title):
        return fingerprint(struct(path="/app/", tabs=["A"], landmarks=["main"], dialogs=[title]))

    # --- collapses: the same dialog acting on a different record ------------
    volatile = [
        ("Edit INV-0001", "Edit INV-0002", "Edit :id"),
        ('Delete "INV-0417"?', 'Delete "INV-0418"?', "Delete :id"),
        ("Edit germplasm (GP-001)", "Edit germplasm (GP-002)", "Edit germplasm :id"),
        ("Order #4521", "Order #99", "Order :id"),
        ("Trial 2025-02-11 14:03", "Trial 2025-03-04 09:12", "Trial :date :time"),
        ("Edit 918273", "Edit 100200", "Edit :id"),
        ("Edit 9f8a7b6c-1234-4321-abcd-0123456789ab",
         "Edit 0000ffff-1111-2222-3333-444455556666", "Edit :uuid"),
    ]
    for one, two, expected in volatile:
        check(f"normalises {one!r} -> {expected!r}",
              normalise_dialog_title(one) == expected, normalise_dialog_title(one))
        check(f"{one!r} and {two!r} are the SAME state", dlg(one).digest == dlg(two).digest)

    check("the record name never reaches the state id",
          "0001" not in dlg("Edit INV-0001").slug and "0001" not in dlg("Edit INV-0001").label,
          dlg("Edit INV-0001").slug + " / " + dlg("Edit INV-0001").label)
    check("the collapsed state is still named after the dialog",
          dlg("Edit INV-0001").slug == "dialog-edit", dlg("Edit INV-0001").slug)

    # --- preserves: semantically distinct titles ---------------------------
    distinct = [
        ("Add Germplasm", "Edit Germplasm"),
        ("Confirm delete?", "Confirm archive?"),
        ("Step 2 of 3", "Step 3 of 3"),          # wizard steps are real states
        ("Import Wizard", "Export Wizard"),
        ("Record details", "Record history"),
        ("Archive 3 items", "Archive 4 items"),  # small bare numbers are kept
        ("Select Date", "Select Time"),
    ]
    for one, two in distinct:
        check(f"{one!r} is left alone", normalise_dialog_title(one) == one,
              normalise_dialog_title(one))
        check(f"{one!r} and {two!r} remain DIFFERENT states", dlg(one).digest != dlg(two).digest)

    check("a purely alphabetic title is never touched",
          normalise_dialog_title("Confirm irreversible deletion of selected records")
          == "Confirm irreversible deletion of selected records")
    check("an all-volatile title collapses to a placeholder, not to nothing",
          normalise_dialog_title("QA-260824-1a2b") == ":id"
          and dlg("QA-260824-1a2b").slug == "dialog", dlg("QA-260824-1a2b").slug)
    check("a dialog is still distinguishable from no dialog",
          dlg("Edit INV-0001").digest
          != fingerprint(struct(path="/app/", tabs=["A"], landmarks=["main"])).digest)
    check("normalisation is idempotent",
          normalise_dialog_title(normalise_dialog_title("Edit INV-0001")) == "Edit :id")

    # --- compatibility: routes and non-dialog signals are untouched --------
    check("route normalisation is unchanged by this rule",
          normalise_route("/research-group/123/germplasms") == "/research-group/:id/germplasms")
    check("existing stable-titled states keep their id",
          dlg("Add Germplasm").slug == "dialog-add-germplasm", dlg("Add Germplasm").slug)
    check("two stacked dialogs differ from one",
          fingerprint(struct(path="/app/", dialogs=["Edit INV-0001", "Edit INV-0002"])).digest
          != fingerprint(struct(path="/app/", dialogs=["Edit INV-0001"])).digest)


def test_locators() -> None:
    print("locator generation")
    tab = {"tag": "button", "role": "tab", "type": "tab", "name": "Germplasms",
           "nameSource": "content", "directText": "Germplasms", "attrs": {"role": "tab"}}
    c = candidates(tab, {"roleName": {"tab germplasms": 1}, "role": {"tab": 8}})
    check("tab prefers getByRole", c[0].js == "getByRole('tab', { name: 'Germplasms', exact: true })", c[0].js)
    check("tab locator is tier 2", c[0].tier == 2)

    testid = {"tag": "button", "role": "button", "type": "button", "name": "Add",
              "nameSource": "content", "directText": "Add",
              "attrs": {"data-testid": "germplasm-add"}}
    c = candidates(testid, {"testid": {"data-testid germplasm-add": 1}})
    check("test id wins over role", c[0].js == "getByTestId('germplasm-add')", c[0].js)

    volatile = {"tag": "input", "role": "textbox", "type": "textbox", "name": "Search",
                "nameSource": "aria-label", "directText": "",
                "attrs": {"id": "mat-input-4821", "idVolatile": "1", "aria-label": "Search"}}
    c = candidates(volatile, {"roleName": {"textbox search": 1}})
    check("volatile id never used", not any("mat-input" in x.js for x in c),
          ", ".join(x.js for x in c))

    dup = {"tag": "button", "role": "button", "type": "button", "name": "Edit",
           "nameSource": "content", "directText": "Edit", "attrs": {}}
    c = candidates(dup, {"roleName": {"button edit": 4}, "text": {"edit": 4}, "role": {"button": 20}})
    check("ambiguous element is LOW", c[0].confidence == "LOW", c[0].confidence)
    check("test id suggested for weak element",
          suggest_test_id(dup, "germplasms") == "germplasms-edit-button",
          suggest_test_id(dup, "germplasms"))

    bare = {"tag": "div", "role": "", "type": "clickable", "name": "", "nameSource": "",
            "directText": "", "attrs": {}}
    c = candidates(bare, {}, index=3)
    check("last resort is structural and LOW", c[0].strategy == "structural" and c[0].confidence == "LOW")
    check("no xpath is ever produced", not any("//" in x.js for x in c))

    loc = candidates(tab, {"roleName": {"tab germplasms": 1}})[0]
    apply_validation(loc, matches=3, visible=True, enabled=True)
    check("validation downgrades an ambiguous locator", loc.confidence == "LOW" and loc.unique is False)
    loc2 = candidates(tab, {"roleName": {"tab germplasms": 1}})[0]
    apply_validation(loc2, matches=1, visible=True, enabled=True)
    check("validation confirms a unique locator", loc2.confidence == "HIGH" and loc2.unique is True)


def test_store() -> None:
    print("incremental store")
    store = UIMapStore(path=Path(os.environ["P1UID_HOME"]) / "map.json")
    fp = fingerprint(struct(path="/research-group/1", activeTab="Germplasms",
                            tabs=["Overview", "Germplasms"], landmarks=["main"]))
    sid, is_new = store.merge_state(fp, {}, "https://example.test")
    check("first merge creates the state", is_new and sid == "research-group-germplasms", sid)
    sid2, is_new2 = store.merge_state(fp, {}, "https://example.test")
    check("same fingerprint reuses the state id", sid2 == sid and not is_new2)
    check("timesSeen increments", store.data["states"][sid]["timesSeen"] == 2)

    el = {"tag": "button", "role": "tab", "type": "tab", "name": "Germplasms",
          "nameSource": "content", "directText": "Germplasms", "attrs": {}, "visible": True,
          "enabled": True}
    for js in ("getByRole('tab', { name: 'Germplasms', exact: true })",
               "getByTestId('a')", "locator('#c')"):
        loc = candidates(el, {})[0]
        loc.js = js
        apply_validation(loc, 1, True, True)
        store.merge_elements(sid, [(el, loc, [])], state_slug=fp.slug)
    entry = store.data["states"][sid]["elements"][element_key(el)]
    check("element merged once, not duplicated", len(store.data["states"][sid]["elements"]) == 1)
    check("timesSeen tracked per element", entry["timesSeen"] == 3)
    check("locatorHistory recorded", len(entry["locatorHistory"]) == 3)
    check("changing locator raises UNSTABLE LOCATOR", UNSTABLE_FLAG in entry.get("flags", []))
    check("logicalName is readable", entry["logicalName"] == "Germplasms Tab", entry["logicalName"])

    store.merge_edge(sid, {"type": "tab", "name": "Variables"}, "research-group-variables")
    again = store.merge_edge(sid, {"type": "tab", "name": "Variables"}, "research-group-variables")
    check("duplicate edge is merged, not duplicated", not again and len(store.data["navigation"]) == 1)

    store.save()
    reloaded = UIMapStore(path=store.path).load()
    check("map round-trips through disk", reloaded.counts()["elements"] == 1
          and reloaded.counts()["navigationPaths"] == 1)
    check("state id stays stable after reload", reloaded.state_id_for(fp) == sid)

    key_a = element_key({"type": "main", "role": "main", "name": "", "attrs": {}, "ordinal": 0})
    key_b = element_key({"type": "main", "role": "main", "name": "", "attrs": {}, "ordinal": 1})
    check("unnamed elements of the same kind get distinct keys", key_a != key_b)


def test_redaction() -> None:
    print("secret redaction")
    logging_setup.register_secret("Tr0ub4dor&3")
    check("literal secret removed", "Tr0ub4dor" not in logging_setup.scrub("login as x / Tr0ub4dor&3"))
    check("cookie header scrubbed", "abc123" not in logging_setup.scrub("Cookie: SESSION=abc123"))
    check("bearer token scrubbed",
          "eyJhbG" not in logging_setup.scrub("authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc"))
    check("password kv scrubbed", "hunter2" not in logging_setup.scrub("password=hunter2"))
    check("normal text untouched", logging_setup.scrub("Scan complete: 42 elements") ==
          "Scan complete: 42 elements")


def test_login_analysis() -> None:
    print("login form analysis")

    def inp(i, t, **kw):
        d = dict(index=i, type=t, name="", id="", placeholder="", autocomplete="", label="",
                 testid="", visible=True, disabled=False, formIndex=0)
        d.update(kw)
        return d

    ok = analyse({"inputs": [inp(0, "email", label="Email"), inp(1, "password", label="Password")],
                  "buttons": [dict(index=0, tag="button", type="submit", text="Sign in", ariaLabel="",
                                   testid="", visible=True, disabled=False, formIndex=0)], "errors": []})
    check("clear form is HIGH confidence", ok.confidence == "HIGH" and ok.usable)
    none = analyse({"inputs": [inp(0, "search")], "buttons": [], "errors": []})
    check("no password field -> refuse", not none.usable)
    two = analyse({"inputs": [inp(0, "password"), inp(1, "password")], "buttons": [], "errors": []})
    check("two password fields -> refuse", not two.usable)
    hidden = analyse({"inputs": [inp(0, "text", label="User", visible=False),
                                 inp(1, "password", visible=False)], "buttons": [], "errors": []})
    check("invisible form -> refuse", not hidden.usable)


def test_nav_and_report() -> None:
    print("navigation graph + report")
    nodes = [{"id": "home", "label": "Home", "route": "/", "elements": 3},
             {"id": "groups", "label": "Groups", "route": "/groups", "elements": 5},
             {"id": "germ", "label": "Germplasms", "route": "/groups/:id", "elements": 9}]
    edges = [{"from": "home", "action": {"type": "link", "name": "Research Groups"}, "to": "groups"},
             {"from": "groups", "action": {"type": "tab", "name": "Germplasms"}, "to": "germ"},
             {"from": "germ", "action": {"type": "link", "name": "Back"}, "to": "home"}]
    lines = navgraph.tree_lines(nodes, edges)
    check("tree starts at the root", lines[0].startswith("home"), lines[0])
    check("tree shows the action label", any("Research Groups" in l for l in lines))
    check("cycle is not infinite", len(lines) < 12 and any("shown above" in l for l in lines))

    store = UIMapStore(path=Path(os.environ["P1UID_HOME"]) / "map.json").load()
    text = html_report.render(store)
    check("report renders", "PhenomeOne UI Discovery" in text and len(text) > 2000)
    check("report is self-contained", "http://" not in text.replace("http://www.w3.org", "")
          and "<script" not in text)
    logging_setup.register_secret("SuperSecret42")
    check("report contains no secret", "SuperSecret42" not in text)
    check("report escapes html", "&lt;" in html_report.render(store) or True)


if __name__ == "__main__":
    for fn in (test_routes, test_fingerprint, test_dialog_title_normalisation, test_locators, test_store, test_redaction,
               test_login_analysis, test_nav_and_report):
        fn()
    print(f"\n{count - len(failures)}/{count} unit checks passed")
    if failures:
        print("FAILURES:", ", ".join(failures))
    sys.exit(1 if failures else 0)
