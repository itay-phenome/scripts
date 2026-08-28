"""Safety-classifier tests: unit table + live integration against the mock app.

The contract under test: a crawler may click ONLY elements whose verdict has
`auto_clickable == True`. Everything dangerous or unrecognised must be excluded,
and it must be excluded for a *stated reason*, not by accident.

Run:  python tests/test_safety.py            (unit + browser integration)
      python tests/test_safety.py --unit     (unit only, no browser)
"""
from __future__ import annotations

import asyncio
import os
import queue
import re
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

HOME = Path(tempfile.mkdtemp(prefix="p1uid-safety-"))
os.environ["P1UID_HOME"] = str(HOME)

from p1uid.crawler import safety                                   # noqa: E402
from p1uid.crawler.safety import (CONDITIONAL, DANGEROUS, SAFE_NAVIGATION,   # noqa: E402
                                  UNKNOWN, classify, classify_all, summarise)

failures: list[str] = []
count = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global count
    count += 1
    if not ok:
        failures.append(label + ((" - " + detail) if detail else ""))
        print(f"  FAIL  {label}{(' - ' + detail) if detail else ''}")
    else:
        print(f"  PASS  {label}{(' - ' + detail) if detail else ''}")


def el(**kw):
    """An element record with the shape the injected core produces."""
    base = dict(tag="button", role="button", type="button", name="", nameSource="content",
                directText="", attrs={}, visible=True, enabled=True, interactive=True,
                container=False, inDialog=False, frame="")
    base.update(kw)
    if base.get("directText") == "" and base.get("name"):
        base["directText"] = base["name"]
    return base


def link(href, **kw):
    """A link record with the `link` sub-object the core computes."""
    m = re.match(r"^([a-z][a-z0-9+.\-]*):", href, re.I)
    scheme = (m.group(1) if m else "http").lower()
    # Mirrors the core: a relative href, "#" or "" resolves against the current
    # origin, so it is same-origin regardless of scheme prefix.
    same = not m or href.startswith("http://127.0.0.1")
    info = dict(raw=href, scheme=scheme,
                origin="http://127.0.0.1:1" if same else "https://external.example.com",
                sameOrigin=same, pathname=href if href.startswith("/") else "",
                download=kw.pop("download", False),
                fileLike=bool(re.search(r"\.(pdf|csv|zip|xlsx?)($|\?)", href, re.I)),
                target=kw.pop("target", ""), empty=href in ("", "#"))
    d = el(tag="a", role="link", type="link", **kw)
    d["link"] = info
    d["attrs"] = dict(d["attrs"], href=href)
    return d


# ===================================================================== units
REQUIRED_DANGEROUS = ["Delete", "Remove", "Save", "Submit", "Import", "Execute",
                      "Archive", "Publish", "Approve", "Reject", "Reset", "Send",
                      "Logout", "Log out", "Sign out"]


def test_required_dangerous_verbs() -> None:
    print("\nrequired dangerous verbs (spec minimum)")
    bad = []
    for word in REQUIRED_DANGEROUS:
        v = classify(el(name=word))
        if v.classification != DANGEROUS or v.auto_clickable:
            bad.append(f"{word}->{v.classification}")
    check("every required verb is DANGEROUS and never auto-clickable", not bad, "; ".join(bad))

    # ...and in realistic phrasings, in any label slot.
    variants = [
        el(name="Delete germplasm"),
        el(name="Remove selected rows"),
        el(name="Save changes"),
        el(name="Submit for approval"),
        el(name="Import from CSV"),
        el(name="Execute pipeline"),
        el(name="Archive trial"),
        el(name="Publish results"),
        el(name="Approve request"), el(name="Reject request"),
        el(name="Reset filters"), el(name="Send notification"),
        el(name="", attrs={"aria-label": "Delete row"}),
        el(name="", attrs={"title": "Save draft"}),
        el(name="", attrs={"data-testid": "germplasm-delete-button"}),
        el(name="Trash", attrs={"aria-label": "Remove attachment"}),
    ]
    wrong = [f"{(v.matched or '?')}:{v.classification}"
             for v in (classify(e) for e in variants) if v.classification != DANGEROUS]
    check("dangerous verbs caught in name, aria-label, title and test id", not wrong, "; ".join(wrong))

    auth = classify(el(name="Log out"))
    check("session-ending gets its own flag", safety.FLAG_AUTH in auth.flags, str(auth.flags))


def test_structure_beats_labels() -> None:
    print("\nstructure beats labels")
    # A <button> with no type inside a form submits it - whatever it is called.
    v = classify(el(name="Go", effectiveButtonType="submit", buttonType="", inForm=True,
                    form={"identity": "germplasm", "method": "post", "action": "/api/germplasm"}))
    check("innocuous 'Go' that implicitly submits a POST form is DANGEROUS",
          v.classification == DANGEROUS, v.classification)
    check("POST flagged", safety.FLAG_POST in v.flags, str(v.flags))
    check("implicit submit explained in the reasons",
          any("no type inside a form" in r for r in v.reasons), str(v.reasons))

    v = classify(el(tag="input", inputType="submit", name="Search", inForm=True,
                    form={"identity": "f", "method": "get"}))
    check("input[type=submit] labelled 'Search' is DANGEROUS", v.classification == DANGEROUS,
          v.classification)

    v = classify(el(tag="input", inputType="reset", name="Start over", inForm=True,
                    form={"identity": "f", "method": "get"}))
    check("input[type=reset] is DANGEROUS", v.classification == DANGEROUS, v.classification)

    v = classify(el(name="Filter", buttonType="button", effectiveButtonType="button",
                    inForm=True, form={"identity": "f", "method": "get"}))
    check("explicit type=button in a GET form is not dangerous, but not navigation either",
          v.classification == CONDITIONAL and not v.auto_clickable, v.classification)


def test_urls() -> None:
    print("\nblocked destinations")
    cases = [
        ("mailto:", link("mailto:a@b.com", name="Email support"), safety.FLAG_MAILTO),
        ("javascript:", link("javascript:void(0)", name="Do thing"), safety.FLAG_JAVASCRIPT),
        ("blob:", link("blob:http://x/abcd", name="Blob"), safety.FLAG_BLOB),
        ("data:", link("data:text/csv;base64,QQ==", name="Inline"), safety.FLAG_DATA_URL),
        ("tel:", link("tel:+123456", name="Call us"), safety.FLAG_EXTERNAL_SCHEME),
        ("cross-origin", link("https://external.example.com/docs", name="Docs"),
         safety.FLAG_CROSS_ORIGIN),
        ("download attribute", link("/files/report.csv", name="Report", download=True),
         safety.FLAG_DOWNLOAD),
        ("file-like href", link("/files/manual.pdf", name="Manual"), safety.FLAG_DOWNLOAD),
    ]
    for label, rec, flag in cases:
        v = classify(rec, origin="http://127.0.0.1:1")
        check(f"{label} link is DANGEROUS and flagged",
              v.classification == DANGEROUS and flag in v.flags and not v.auto_clickable,
              f"{v.classification} {v.flags}")

    # target=_blank is OBSERVED, not pre-refused. Refusing it before the click
    # made every application surface that opens in a tab unreachable - on real
    # PhenomeOne, the germplasm detail page. The flag is still recorded so the
    # outcome layer knows to expect a new context; what the click actually did
    # is judged from the context's URL (see crawler/outcomes.py).
    v = classify(link("/app/help", name="Help", target="_blank"), origin="http://127.0.0.1:1")
    check("a same-origin target=_blank link is flagged AND clickable",
          safety.FLAG_NEW_TAB in v.flags and v.auto_clickable
          and v.classification == SAFE_NAVIGATION, f"{v.classification} {v.flags}")
    # The safety half must not move: a new tab is no excuse.
    v = classify(link("/app/delete-record", name="Delete record", target="_blank"),
                 origin="http://127.0.0.1:1")
    check("a destructive target=_blank link is still refused",
          v.classification == DANGEROUS and not v.auto_clickable, f"{v.classification} {v.flags}")
    v = classify(link("http://elsewhere.test/docs", name="Docs", target="_blank"),
                 origin="http://127.0.0.1:1")
    check("a cross-origin target=_blank link is still refused",
          v.classification == DANGEROUS and not v.auto_clickable, f"{v.classification} {v.flags}")

    v = classify(link("/app/research-groups", name="Research Groups"), origin="http://127.0.0.1:1")
    check("plain same-origin link is SAFE_NAVIGATION and auto-clickable",
          v.classification == SAFE_NAVIGATION and v.auto_clickable, v.classification)

    v = classify(link("#", name="Toggle thing"), origin="http://127.0.0.1:1")
    check("href='#' link is UNKNOWN (behaviour is scripted)", v.classification == UNKNOWN,
          v.classification)


def test_unknown_actions() -> None:
    print("\nunknown actions are never safe")
    mystery = el(name="", directText="", iconOnly=True, labelled=False, attrs={"data-testid": "gear"})
    v = classify(mystery)
    check("icon-only control with no accessible name is UNKNOWN",
          v.classification == UNKNOWN and not v.auto_clickable, v.classification)
    check("unlabelled flag set", safety.FLAG_UNLABELLED in v.flags, str(v.flags))

    v = classify(el(type="clickable", role="", tag="div", name="Widget area"))
    check("opaque clickable div is UNKNOWN", v.classification == UNKNOWN, v.classification)

    v = classify(el(name="Recalculate index"))
    check("recognised-but-unlisted verb is not treated as navigation",
          v.classification in (DANGEROUS, UNKNOWN) and not v.auto_clickable, v.classification)

    v = classify(el(name="Frobnicate"))
    check("a named button with an unrecognised effect is UNKNOWN",
          v.classification == UNKNOWN and not v.auto_clickable, v.classification)

    # Icon-only WITH a label is judged by that label.
    v = classify(el(name="Delete row", iconOnly=True, labelled=True,
                    attrs={"aria-label": "Delete row"}))
    check("icon-only + aria-label 'Delete row' is DANGEROUS", v.classification == DANGEROUS,
          v.classification)
    v = classify(el(name="Expand details", iconOnly=True, labelled=True, expandable=True,
                    expanded=False, attrs={"aria-label": "Expand details"}))
    check("icon-only + aria-label 'Expand details' is SAFE_NAVIGATION",
          v.classification == SAFE_NAVIGATION and v.auto_clickable, v.classification)


def test_safe_navigation() -> None:
    print("\nsafe navigation")
    for label, rec in [
        ("tab", el(type="tab", role="tab", name="Germplasms", selected=False)),
        ("expander", el(name="Show advanced settings", expandable=True, expanded=False)),
        ("summary", el(tag="summary", role="button", name="Advanced")),
        ("tree item", el(type="treeitem", role="treeitem", name="Agronomic", expandable=True)),
        ("pagination", el(type="pagination", role="navigation", name="Pagination")),
        ("aria-haspopup=menu", el(name="Actions", hasPopup="menu")),
        ("view button", el(name="View details")),
    ]:
        v = classify(rec)
        check(f"{label} is SAFE_NAVIGATION and auto-clickable",
              v.classification == SAFE_NAVIGATION and v.auto_clickable,
              f"{v.classification} auto={v.auto_clickable}")

    v = classify(el(name="Open dialog", hasPopup="dialog"))
    check("aria-haspopup=dialog is CONDITIONAL, not navigation",
          v.classification == CONDITIONAL and not v.auto_clickable, v.classification)


def test_conditional() -> None:
    print("\nconditional actions")
    for label, rec, expect in [
        ("Close dialog", el(name="Close dialog"), CONDITIONAL),
        ("Cancel", el(name="Cancel"), CONDITIONAL),
        ("text input", el(type="textbox", role="textbox", tag="input", name="Name"), CONDITIONAL),
        ("checkbox", el(type="checkbox", role="checkbox", name="Only mine"), CONDITIONAL),
        ("switch", el(type="switch", role="switch", name="Live updates"), CONDITIONAL),
        ("combobox", el(type="combobox", role="combobox", tag="select", name="Season"), CONDITIONAL),
        ("search", el(name="Search groups"), CONDITIONAL),
        ("sort", el(name="Sort by name"), CONDITIONAL),
        ("menu item", el(type="menuitem", role="menuitem", name="Columns"), CONDITIONAL),
        ("wizard Next", el(name="Next"), CONDITIONAL),
    ]:
        v = classify(rec)
        check(f"{label} -> CONDITIONAL, not auto-clickable",
              v.classification == expect and not v.auto_clickable,
              f"{v.classification} auto={v.auto_clickable}")

    v = classify(el(name="Next page", attrs={"aria-label": "Next page"}))
    check("'Next page' IS pagination navigation", v.classification == SAFE_NAVIGATION,
          v.classification)

    # Confirm-dialog affirmatives execute; they are not dismissals.
    for word in ("OK", "Yes", "Continue", "Proceed", "Apply", "Accept"):
        v = classify(el(name=word, context={"dialog": "Delete all observations?"}))
        check(f"'{word}' in a confirm dialog is DANGEROUS", v.classification == DANGEROUS,
              v.classification)

    for phrase in ("Close account", "Hide project", "Cancel subscription"):
        v = classify(el(name=phrase))
        check(f"'{phrase}' is not treated as a dismissal",
              v.classification == DANGEROUS and not v.auto_clickable, v.classification)


def test_state_and_context() -> None:
    print("\nstate and context gates")
    v = classify(el(type="tab", role="tab", name="Germplasms", visible=False))
    check("hidden element is never auto-clickable",
          not v.auto_clickable and safety.FLAG_HIDDEN in v.flags, f"{v.classification} {v.flags}")
    v = classify(el(type="tab", role="tab", name="Germplasms", enabled=False))
    check("disabled element is never auto-clickable",
          not v.auto_clickable and safety.FLAG_DISABLED in v.flags, f"{v.classification} {v.flags}")

    v = classify(el(type="tab", role="tab", name="Details",
                    context={"dialog": "Add Germplasm"}))
    check("navigation inside a write dialog is downgraded to CONDITIONAL",
          v.classification == CONDITIONAL and not v.auto_clickable, v.classification)

    v = classify(el(name="View details", inForm=True, form={"identity": "search-form",
                                                            "method": "get"},
                    buttonType="button", effectiveButtonType="button"))
    check("navigation inside a form is downgraded to CONDITIONAL",
          v.classification == CONDITIONAL, v.classification)


def test_invariants() -> None:
    print("\nglobal invariants")
    universe = [
        el(name=w) for w in REQUIRED_DANGEROUS + ["Frobnicate", "Details", "View", "Cancel", "OK"]
    ] + [
        el(type="tab", role="tab", name="Germplasms"),
        el(name="", iconOnly=True, labelled=False),
        el(type="checkbox", role="checkbox", name="Flag"),
        link("mailto:x@y.z", name="Mail"), link("javascript:x()", name="Js"),
        link("blob:http://x/1", name="Blob"), link("https://other.example/x", name="Ext"),
        link("/f.csv", name="Csv"), link("/ok", name="Fine"),
        el(name="Go", effectiveButtonType="submit", inForm=True,
           form={"identity": "f", "method": "post"}),
    ]
    pairs = classify_all(universe, origin="http://127.0.0.1:1")

    leaks = [f"{e.get('name') or '(unnamed)'}={v.classification}"
             for e, v in pairs if v.auto_clickable and v.classification != SAFE_NAVIGATION]
    check("auto_clickable implies SAFE_NAVIGATION", not leaks, "; ".join(leaks))

    leaks = [e.get("name") for e, v in pairs
             if v.classification in (DANGEROUS, UNKNOWN) and v.auto_clickable]
    check("no DANGEROUS or UNKNOWN action is ever auto-clickable", not leaks, "; ".join(map(str, leaks)))

    leaks = [f"{e.get('name')}:{v.flags}" for e, v in pairs
             if v.auto_clickable and (set(v.flags) & safety.BLOCKING_FLAGS)]
    check("no auto-clickable action carries a blocking flag", not leaks, "; ".join(leaks))

    check("every verdict has a reason", all(v.reasons for _e, v in pairs))
    check("every verdict is one of the four classes",
          all(v.classification in safety.CLASSES for _e, v in pairs))

    s = summarise(pairs)
    check("summarise counts all four classes", set(s["counts"]) == set(safety.CLASSES), str(s["counts"]))
    check("summary autoClickable matches the verdicts",
          s["autoClickable"] == sum(1 for _e, v in pairs if v.auto_clickable), str(s))


def test_no_networkidle() -> None:
    print("\nwaitStable implementation constraints")
    src = (ROOT / "src" / "p1uid" / "discovery" / "stability.py").read_text(encoding="utf-8")
    core = (ROOT / "src" / "p1uid" / "browser" / "injected.py").read_text(encoding="utf-8")
    check("stability code never waits for networkidle",
          "networkidle" not in src.replace("`networkidle`", "").replace("network idle", ""))
    check("no arbitrary sleep in the settle path",
          "asyncio.sleep" not in src and "wait_for_timeout" not in src)
    check("waitStable is implemented with a MutationObserver + signature",
          "MutationObserver" in core and "domSignature()" in core)


# ============================================================== integration
async def _classify_live(engine, page) -> list[tuple[dict, object]]:
    """Collect raw records from every frame and classify them."""
    from p1uid.discovery import scanner
    out: list[tuple[dict, object]] = []
    for frame in page.frames:
        data = await scanner.collect_frame(frame)
        if not data:
            continue
        for rec in data.get("elements", []):
            out.append((rec, classify(rec, origin=engine.origin)))
    return out


def find(pairs, testid=None, name=None):
    for rec, v in pairs:
        if testid and (rec.get("attrs") or {}).get("data-testid") == testid:
            return rec, v
        if name and rec.get("name") == name:
            return rec, v
    return None, None


def semantics_free_tree() -> None:
    """A navigation tree with no ARIA at all must still be navigable.

    Reproduced from the DOM probe of real PhenomeOne (2026-08-27): dhtmlxTree
    renders every research group as
    `<td class="dhxTextCell standartTreeRow"><span>Tomato</span></td>` - no role,
    no href, no tabindex, no test id. Discovery collected 5 elements on that
    whole screen, none of them navigation, so an autonomous crawl had nothing to
    click on any page of the application.

    The negative cases carry equal weight: corroboration is what makes this safe,
    so a lone pointer node and a pair of them must stay UNKNOWN, and a
    destructive label must stay DANGEROUS however list-shaped it is.
    """
    import queue
    from p1uid.browser.controller import Engine
    from p1uid.discovery import scanner
    from p1uid.logging_setup import setup
    from serve_mock import MockServer

    setup(debug="--debug" in sys.argv)
    print("\n" + "=" * 62 + "\nINTEGRATION: a tree with no semantics\n" + "=" * 62)
    with MockServer() as server:
        root = server.url.rsplit("/app/", 1)[0] + "/"
        engine = Engine(queue.Queue(), headless="--headed" not in sys.argv)
        engine.start()
        try:
            engine.call(lambda: engine.open_url(root + "tree.html"), timeout=120)
            res = engine.call(lambda: scanner.scan_page(
                engine.page, engine.store, origin=engine.origin,
                validate_limit=300, keep_rows=True), timeout=180)
            check("the page was scanned", res is not None and res.elements > 5,
                  str(res.elements if res else 0))
            rows = {}
            for _f, el, loc in res.rows:
                name = (el.get("name") or "").strip()
                if name:
                    rows[name] = (el, loc, classify(el, origin=engine.origin))

            tree = ["Tomato Demo", "Eggplant", "Pepper-ID1533", "Sorghum", "Watermelon"]
            found = [n for n in tree if n in rows]
            check("every tree row was discovered", found == tree, f"found {found}")
            check("they are recognised as clickable controls",
                  all(rows[n][0].get("type") == "clickable" for n in found),
                  str([(n, rows[n][0].get("type")) for n in found]))
            check("corroboration counted the shape",
                  all((rows[n][0].get("leafSiblings") or 0) >= 3 for n in found),
                  str([(n, rows[n][0].get("leafSiblings")) for n in found]))
            check("they are SAFE_NAVIGATION and auto-clickable",
                  all(rows[n][2].classification == SAFE_NAVIGATION and rows[n][2].auto_clickable
                      for n in found),
                  str([(n, rows[n][2].classification) for n in found]))
            check("each row has a UNIQUE locator (the wrapper was not harvested too)",
                  all(rows[n][1].matches == 1 for n in found),
                  str([(n, rows[n][1].matches) for n in found]))
            check("the locator targets the row by its text",
                  all("Sorghum" in rows["Sorghum"][1].js for _ in [0]), rows["Sorghum"][1].js)

            # --- corroboration is load-bearing -----------------------------
            check("a LONE pointer node stays UNKNOWN",
                  "Mystery control" in rows
                  and rows["Mystery control"][2].classification == UNKNOWN
                  and not rows["Mystery control"][2].auto_clickable,
                  str(rows.get("Mystery control", ("missing",))[-1:]))
            pair = [n for n in ("First thing", "Second thing") if n in rows]
            check("exactly TWO of a shape is not a list either",
                  len(pair) == 2 and all(rows[n][2].classification == UNKNOWN for n in pair),
                  str([(n, rows[n][2].classification) for n in pair]))

            # --- the vetoes still win --------------------------------------
            check("a destructive label stays DANGEROUS however list-shaped",
                  "Delete Sorghum" in rows
                  and rows["Delete Sorghum"][2].classification == DANGEROUS
                  and not rows["Delete Sorghum"][2].auto_clickable,
                  str(rows.get("Delete Sorghum", ("missing",))[-1:]))
            check("no auto-clickable row carries a blocking flag",
                  not [n for n, (_e, _l, v) in rows.items()
                       if v.auto_clickable and set(v.flags) & safety.BLOCKING_FLAGS],
                  str([n for n, (_e, _l, v) in rows.items() if v.auto_clickable]))

            # --- a data grid has the same shape and must NOT be collected ---
            #
            # The first real crawl (2026-08-28) put record names, counts and
            # dates into the map with locators built from the data. These cells
            # are pointer leaves exactly like the tree rows above: what separates
            # them is a value for a label, or three labelled cells in one row.
            names = {(el.get("name") or "").strip() for _f, el, _l in res.rows}
            leaked = sorted(n for n in names if n and (
                "parchita" in n.lower() or "itay-test" in n.lower()
                or n in ("1,241", "5,547", "93", "8,120", "9,004", "7,441")
                or n in ("2025-09-21", "2023-10-22")))
            check("no grid value reached the map (no business data)", not leaked, str(leaked))
            check("a word-labelled cell in a row of values is refused too",
                  "Approved" not in names and "Draft" not in names,
                  str(sorted(n for n in names if n in ("Approved", "Draft"))))
            check("the tree survived the same rules",
                  all(n in rows for n in tree), f"found {[n for n in tree if n in rows]}")

            # A flat list of navigation rows - siblings of each other, with no
            # table wrapper - is what a "too many labelled siblings" rule would
            # have vetoed, taking the navigation with it. Names, not values.
            flat = ["Germplasms", "Trials", "Inventory", "Observations"]
            check("a flat sibling list of names stays navigable",
                  all(n in rows and rows[n][2].classification == SAFE_NAVIGATION
                      and rows[n][2].auto_clickable for n in flat),
                  str([(n, rows[n][2].classification if n in rows else "MISSING")
                       for n in flat]))

            # --- the same label twice: still uniquely targetable -------------
            #
            # 308 refusals in the 2026-08-28 crawl were `locator-not-unique`, and
            # they were navigation: a tab and a summary card share a label, so
            # `getByText` matched two elements and the crawler refused both.
            dupes = [(el, loc) for _f, el, loc in res.rows
                     if (el.get("name") or "").strip() == "Germplasms"]
            # Three of them on this page: a nav item (section 9), a tab and a
            # summary card. `getByText('Germplasms')` matches all three.
            check("all three 'Germplasms' controls are discovered", len(dupes) == 3,
                  f"{len(dupes)} found")
            check("each one resolves to exactly ONE element",
                  all(loc.matches == 1 for _e, loc in dupes),
                  str([(loc.matches, loc.js[:44]) for _e, loc in dupes]))
            check("neither fell back to plain ambiguous text",
                  not [l for _e, l in dupes if l.js.startswith("getByText(")],
                  str([l.js[:44] for _e, l in dupes]))
            scopes = sorted(l.args.get("css", "").split(":text-is")[0] for _e, l in dupes)
            check("each is scoped by its own design-system class",
                  scopes == ["div.cardLabel", "div.navCell", "div.tabCell"], str(scopes))
            check("a state modifier never reaches the locator",
                  not [l for _e, l in dupes if "actv" in l.js],
                  str([l.js[:52] for _e, l in dupes]))
            tab = [l for e, l in dupes if "tabCell" in l.js]
            check("the tab is auto-clickable now that it is unambiguous",
                  bool(tab) and safety.classify(
                      [e for e, l in dupes if "tabCell" in l.js][0],
                      origin=engine.origin).auto_clickable,
                  str([l.js[:52] for l in tab]))

            # --- anonymous header-free tables are layout, not structure ------
            tables = [el for _f, el, _l in res.rows if el.get("type") == "table"]
            headed = [t for t in tables if "Trial" in ((t.get("grid") or {}).get("columns") or [])]
            check("the header-free layout tables were skipped", len(tables) == len(headed),
                  f"{len(tables)} table(s) recorded, {len(headed)} with headers")
            check("the real grid with headers survived", len(headed) == 1,
                  str([(t.get("grid") or {}).get("columns") for t in tables]))
        finally:
            engine.shutdown_blocking()


def late_data() -> None:
    """A quiet DOM is not a settled one while the data is still on its way.

    Real PhenomeOne changes route, fetches, and renders when the response lands.
    The DOM is perfectly quiet for the whole round trip, which is far longer than
    the 250 ms quiet window - so a mutation-only detector reports "settled" and
    the scan records a screen that has not been drawn.

    The mock's `/slow-data` endpoint sleeps server-side, so this is a real
    in-flight request rather than a timer a test could fake. Both directions are
    asserted: with request-awareness the rows are there, and with it switched off
    they are not - which is what makes the machinery worth its place.
    """
    import queue
    from p1uid.browser.controller import Engine
    from p1uid.discovery import scanner, stability
    from p1uid.logging_setup import setup
    from serve_mock import MockServer

    setup(debug="--debug" in sys.argv)
    print("\n" + "=" * 62 + "\nINTEGRATION: content that arrives after the DOM goes quiet\n" + "=" * 62)
    ROWS = "() => document.querySelectorAll('#content .row').length"
    with MockServer() as server:
        root = server.url.rsplit("/app/", 1)[0] + "/"
        engine = Engine(queue.Queue(), headless="--headed" not in sys.argv)
        engine.start()
        try:
            async def run(wait_requests: bool):
                await engine.open_url(root + "slowdata.html")
                page = engine.page
                await scanner.ensure_core(page.main_frame)
                await page.get_by_text("Load report", exact=True).click()
                res = await page.evaluate(
                    "(o) => window.__p1uidCore.waitStable(o)",
                    {"quietMs": 250, "timeoutMs": 5000, "waitRequests": wait_requests})
                return res, await page.evaluate(ROWS)

            off, rows_off = engine.call(lambda: run(False), timeout=120)
            print(f"    requests ignored: reason={off['reason']} {off['ms']}ms "
                  f"pending={off['pending']} rows={rows_off}")
            check("without request-awareness the page looks settled while empty",
                  off["reason"] == "quiet" and rows_off == 0,
                  f"reason={off['reason']} rows={rows_off}")

            on, rows_on = engine.call(lambda: run(True), timeout=120)
            print(f"    requests awaited: reason={on['reason']} {on['ms']}ms "
                  f"waited={on.get('waited')} rows={rows_on}")
            check("with it, the wait outlasts the request", on["reason"] == "quiet"
                  and bool(on.get("waited")), f"reason={on['reason']} waited={on.get('waited')}")
            check("and the rendered rows are there to be scanned", rows_on == 6, str(rows_on))
            check("it waited for the response, not a fixed sleep",
                  850 < on["ms"] < 4000, f"{on['ms']} ms")
            check("nothing is left in flight afterwards", on["pending"] == 0, str(on["pending"]))

            # A page with no requests must not pay for the machinery.
            async def plain():
                await engine.open_url(root + "tree.html")
                return await stability.wait_stable(engine.page, timeout_ms=5000)
            st = engine.call(lambda: plain(), timeout=60)
            check("a page that fetches nothing still settles fast",
                  st.stable and st.ms < 2000 and not st.waited_for_requests,
                  f"stable={st.stable} {st.ms}ms waited={st.waited_for_requests}")
        finally:
            engine.shutdown_blocking()


def value_labels() -> None:
    """A value is not a control name - the unit half of the same rule.

    `isValueLabel` in the injected core refuses to harvest these nodes at all;
    this is the classifier's own copy, which also covers a record read back from
    a stored map, and it is where the rule can be tested without a browser.
    """
    from p1uid.crawler.safety import _looks_like_a_value

    print("\n" + "=" * 62 + "\nUNIT: value labels are not control names\n" + "=" * 62)
    for label in ("1,241", "5,547", "93", "8", "2025-09-21", "21/09/2025", "5.6.1",
                  "12:30", "  ", "1.241,00"):
        check(f"value: {label!r}", _looks_like_a_value(label))
    for label in ("Tomato", "Eggplant", "Pepper-ID1533", "Delete Sorghum", "Overview",
                  "Trial A", "Approved", "g_1001.3 pepper"):
        check(f"control name: {label!r}", not _looks_like_a_value(label))

    # And the classifier refuses to promote one however list-shaped it is.
    row = {"type": "clickable", "name": "1,241", "leafSiblings": 12, "visible": True,
           "enabled": True}
    v = classify(row)
    check("a list-shaped value is UNKNOWN, not navigation",
          v.classification == UNKNOWN and not v.auto_clickable and v.matched == "value-label",
          f"{v.classification} matched={v.matched}")
    named = {"type": "clickable", "name": "Tomato", "leafSiblings": 12, "visible": True,
             "enabled": True}
    v2 = classify(named)
    check("a list-shaped NAME is still navigation",
          v2.classification == SAFE_NAVIGATION and v2.auto_clickable and v2.matched == "list-shape",
          f"{v2.classification} matched={v2.matched}")


def integration() -> None:
    from p1uid.browser.controller import Engine
    from p1uid.discovery import stability
    from p1uid.logging_setup import setup
    from serve_mock import MockServer

    setup(debug="--debug" in sys.argv)
    print("\n" + "=" * 62 + "\nINTEGRATION: hardened mock app\n" + "=" * 62)

    with MockServer() as server:
        events: "queue.Queue[dict]" = queue.Queue()
        engine = Engine(events, headless="--headed" not in sys.argv)
        engine.start()
        try:
            engine.call(lambda: engine.op_login(server.url, "t@e.st", "SafetyPass!1"), timeout=180)
            check("logged into the mock app", engine.authenticated)

            async def to_admin():
                page = engine.page
                await page.get_by_role("link", name="Research Groups").click()
                await asyncio.sleep(0.4)
                await page.get_by_role("link", name="Research Group ABC").click()
                await asyncio.sleep(0.4)
                await page.get_by_role("tab", name="Admin").click()
                await asyncio.sleep(0.6)
                return await stability.wait_stable(page, timeout_ms=4000)

            st = engine.call(lambda: to_admin(), timeout=120)
            print(f"\n  waitStable on the settled Admin tab: stable={st.stable} "
                  f"reason={st.reason} ms={st.ms} changes={st.changes}")
            check("waitStable reports the settled page as stable", st.stable, st.reason)
            check("waitStable settles quickly", st.ms < 3000, f"{st.ms} ms")

            pairs = engine.call(lambda: _classify_live(engine, engine.page), timeout=120)
            s = summarise(pairs)
            print(f"\n  classified {len(pairs)} live elements: {s['counts']}")
            print(f"  auto-clickable: {s['autoClickable']}")
            print(f"  flags: {s['flags']}\n")

            # --- dangerous toolbar
            bad = []
            for tid in ("admin-save", "admin-delete", "admin-remove", "admin-import",
                        "admin-archive", "admin-publish", "admin-approve", "admin-reject",
                        "admin-execute", "admin-send", "admin-reset", "admin-logout"):
                rec, v = find(pairs, testid=tid)
                if rec is None:
                    bad.append(f"{tid}=NOT FOUND")
                elif v.classification != DANGEROUS or v.auto_clickable:
                    bad.append(f"{tid}={v.classification}/auto={v.auto_clickable}")
            check("every destructive Admin control is DANGEROUS in the live DOM", not bad,
                  "; ".join(bad))

            # --- the structural trap: an innocuous label that POSTs
            rec, v = find(pairs, testid="admin-implicit-submit")
            check("'Go' (implicit submit in a POST form) is DANGEROUS live",
                  v is not None and v.classification == DANGEROUS and not v.auto_clickable,
                  f"{v.classification if v else 'missing'} {v.flags if v else ''}")
            check("POST detected from the live form", v is not None and safety.FLAG_POST in v.flags,
                  str(v.flags) if v else "")
            rec, v = find(pairs, testid="admin-input-submit")
            check("input[type=submit] is DANGEROUS live",
                  v is not None and v.classification == DANGEROUS, str(v.classification if v else None))

            # --- icon-only controls
            rec, v = find(pairs, testid="admin-icon-mystery")
            check("unlabelled icon button is UNKNOWN live",
                  v is not None and v.classification == UNKNOWN and not v.auto_clickable,
                  f"{v.classification if v else 'missing'}")
            rec, v = find(pairs, testid="admin-icon-delete")
            check("icon button labelled 'Delete row' is DANGEROUS live",
                  v is not None and v.classification == DANGEROUS, str(v.classification if v else None))
            rec, v = find(pairs, testid="admin-icon-expand")
            check("icon button labelled 'Expand details' is SAFE_NAVIGATION live",
                  v is not None and v.classification == SAFE_NAVIGATION and v.auto_clickable,
                  str(v.classification if v else None))

            # --- blocked destinations
            for tid, flag in (("admin-mailto", safety.FLAG_MAILTO),
                              ("admin-js", safety.FLAG_JAVASCRIPT),
                              ("admin-blob", safety.FLAG_BLOB),
                              ("admin-external", safety.FLAG_CROSS_ORIGIN),
                              ("admin-download", safety.FLAG_DOWNLOAD),
                              ("admin-file", safety.FLAG_DOWNLOAD)):
                rec, v = find(pairs, testid=tid)
                check(f"{tid} blocked with {flag} live",
                      v is not None and flag in v.flags and not v.auto_clickable,
                      f"{v.classification if v else 'missing'} {v.flags if v else ''}")
            rec, v = find(pairs, testid="admin-newtab")
            check("target=_blank link flagged live",
                  v is not None and safety.FLAG_NEW_TAB in v.flags and not v.auto_clickable,
                  str(v.flags) if v else "")

            # --- safe navigation still gets through
            rec, v = find(pairs, testid="admin-safe-link")
            check("same-origin link is auto-clickable live",
                  v is not None and v.auto_clickable, str(v.classification if v else None))
            tabs = [(r, v) for r, v in pairs if r.get("type") == "tab"]
            check("all tabs are auto-clickable live",
                  bool(tabs) and all(v.auto_clickable for _r, v in tabs),
                  f"{sum(1 for _r, v in tabs if v.auto_clickable)}/{len(tabs)}")
            details = [(r, v) for r, v in pairs if r.get("name") == "Details"]
            check("duplicate 'Details' buttons all classified navigation",
                  len(details) >= 3 and all(v.classification == SAFE_NAVIGATION for _r, v in details),
                  f"{len(details)} found")

            # --- iframe controls
            frame_recs = [(r, v) for r, v in pairs if r.get("frame")]
            check("controls inside the iframe were discovered", len(frame_recs) >= 3,
                  f"{len(frame_recs)} records from sub-frames")
            rec, v = find(pairs, testid="frame-delete")
            check("iframe 'Delete report' is DANGEROUS",
                  v is not None and v.classification == DANGEROUS, str(v.classification if v else None))
            rec, v = find(pairs, name="Run query")
            check("iframe POST submit is DANGEROUS",
                  v is not None and v.classification == DANGEROUS and safety.FLAG_POST in v.flags,
                  f"{v.classification if v else 'missing'} {v.flags if v else ''}")
            rec, v = find(pairs, testid="frame-view")
            check("iframe 'View report' is SAFE_NAVIGATION",
                  v is not None and v.classification == SAFE_NAVIGATION, str(v.classification if v else None))

            # --- hidden dialog contents
            hidden = [(r, v) for r, v in pairs if r.get("visible") is False]
            check("hidden dialog elements were discovered but never auto-clickable",
                  bool(hidden) and not any(v.auto_clickable for _r, v in hidden),
                  f"{len(hidden)} hidden records")
            rec, v = find(pairs, testid="germplasm-save")
            check("closed dialog's Save button is DANGEROUS and flagged not-visible",
                  v is not None and v.classification == DANGEROUS
                  and safety.FLAG_HIDDEN in v.flags, f"{v.classification if v else 'missing'}")

            # --- the confirm() trap must be unreachable
            rec, v = find(pairs, testid="admin-confirm-delete")
            check("the control that raises a native confirm() is DANGEROUS",
                  v is not None and v.classification == DANGEROUS and not v.auto_clickable,
                  str(v.classification if v else None))

            # --- dynamic id must not become a locator or change the verdict
            rec, v = find(pairs, testid="admin-dynamic-id")
            check("control with a random id is still classified (not navigation)",
                  v is not None and not v.auto_clickable, str(v.classification if v else None))

            # --- the whole-surface invariant
            leak = [f"{r.get('name') or r.get('attrs', {}).get('data-testid')}:{v.flags}"
                    for r, v in pairs if v.auto_clickable
                    and (set(v.flags) & safety.BLOCKING_FLAGS)]
            check("no live auto-clickable element carries a blocking flag", not leak, "; ".join(leak))
            danger_words = re.compile("|".join(REQUIRED_DANGEROUS), re.I)
            leak = [r.get("name") for r, v in pairs
                    if v.auto_clickable and danger_words.search(r.get("name") or "")]
            check("no live auto-clickable element has a dangerous verb in its name", not leak,
                  "; ".join(map(str, leak)))
            check("the classifier is not trivially blocking everything",
                  s["autoClickable"] >= 5, f"{s['autoClickable']} auto-clickable")

            # --- waitStable on a page that never settles
            async def churn():
                page = engine.page
                await page.goto(server.url + "?churn=1", wait_until="domcontentloaded")
                return await stability.wait_stable(page, quiet_ms=250, timeout_ms=1500)

            st2 = engine.call(lambda: churn(), timeout=120)
            print(f"\n  waitStable on a churning page: stable={st2.stable} reason={st2.reason} "
                  f"changes={st2.changes} ms={st2.ms}")
            check("waitStable refuses to call a churning page stable", not st2.stable, st2.reason)
            check("waitStable respects its timeout budget", st2.ms < 3000, f"{st2.ms} ms")
            check("waitStable counted the churn", st2.changes > 0, str(st2.changes))
        finally:
            engine.shutdown_blocking()


def main() -> int:
    for fn in (test_required_dangerous_verbs, test_structure_beats_labels, test_urls,
               test_unknown_actions, test_safe_navigation, test_conditional,
               test_state_and_context, test_invariants, test_no_networkidle,
               value_labels):
        fn()
    if "--unit" not in sys.argv:
        semantics_free_tree()
        late_data()
        integration()
    print(f"\n{'=' * 62}\n{count - len(failures)}/{count} safety checks passed")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
    else:
        print("ALL SAFETY CHECKS PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    rc = main()
    shutil.rmtree(HOME, ignore_errors=True)
    sys.exit(rc)
