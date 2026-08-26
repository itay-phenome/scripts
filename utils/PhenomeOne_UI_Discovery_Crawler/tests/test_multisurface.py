"""Autonomous crawling across surfaces, driven by observation.

The crawler used to encode three fixed rules - a popup is closed, a new tab is
refused during a crawl, `target=_blank` is blocked before the click - so any part
of an application living in another browsing context was unreachable by
construction. Real PhenomeOne opens a germplasm detail page exactly that way.

This suite drives `mock_app/surfaces.html`, which contains one construct per
outcome the crawler must react to, and asserts the crawler decided from what the
browser DID rather than from the control's attributes.

`localhost` and `127.0.0.1` serve the same files but are distinct origins, so the
same child page stands in for both "the application in another tab" and
"somebody else's site" depending only on how it was opened.

Run: python tests/test_multisurface.py [--headed] [--debug]
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

HOME = Path(tempfile.mkdtemp(prefix="p1uid-surface-"))
os.environ["P1UID_HOME"] = str(HOME)

from serve_mock import MockServer                      # noqa: E402
from p1uid.browser.controller import Engine            # noqa: E402
from p1uid.crawler import outcomes as O                # noqa: E402
from p1uid.crawler import surfaces as S                # noqa: E402
from p1uid.crawler.bfs import CrawlLimits, SafeCrawler  # noqa: E402
from p1uid.discovery import scanner, stability         # noqa: E402
from p1uid.logging_setup import setup                  # noqa: E402

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
        root = server.url.rsplit("/app/", 1)[0] + "/"
        start = root + "surfaces.html"
        engine = Engine(queue.Queue(), headless="--headed" not in sys.argv)
        engine.start()
        try:
            print(f"\nSurfaces  start={start}\n")
            engine.call(lambda: engine.open_url(start), timeout=120)

            print("[1] the menu construct really is invisible to the fingerprint")
            before = engine.call(lambda: scanner.scan_page(
                engine.page, engine.store, origin=engine.origin, validate_limit=200), timeout=180)

            async def open_menu():
                await engine.page.get_by_test_id("sf-menu").click()
                await engine.page.wait_for_timeout(250)
                return await scanner.scan_page(engine.page, engine.store,
                                               origin=engine.origin, validate_limit=200)

            sig_before = engine.call(lambda: stability.visible_signature(engine.page), timeout=60)
            after = engine.call(lambda: open_menu(), timeout=180)
            sig_after = engine.call(lambda: stability.visible_signature(engine.page), timeout=60)
            check("opening the menu does NOT change the state id",
                  before is not None and after is not None
                  and before.state_id == after.state_id,
                  f"{before.state_id if before else '?'} vs {after.state_id if after else '?'}")
            # The element COUNT does not move either: hidden elements are already
            # recorded, so opening the menu only changes their visibility. That is
            # exactly why a visibility-aware signature is needed.
            check("the element count does not move either",
                  after.elements == before.elements, f"{before.elements} -> {after.elements}")
            check("but the VISIBLE signature does change",
                  sig_before != sig_after and sig_before and sig_after,
                  f"{sig_before!r} -> {sig_after!r}")
            print("    -> a fingerprint-only crawler counts this action as inert")

            # Put the page back before crawling.
            engine.call(lambda: engine.open_url(start), timeout=120)

            print("\n[2] autonomous crawl across surfaces")
            crawler = SafeCrawler(engine, engine.store,
                                  CrawlLimits(max_states=25, max_actions=60,
                                              max_depth=4, time_budget_s=180.0))
            engine.crawl_active = True
            try:
                result = engine.call(lambda: crawler.run(start), timeout=600)
            finally:
                engine.crawl_active = False
            check("the crawl completed", result is not None and not result.aborted,
                  result.aborted if result else "no result")
            if result is None:
                raise SystemExit(1)

            print(f"\n    outcomes: {json.dumps(result.outcome_totals, sort_keys=True)}")
            print(f"    surfaces opened: {result.surfaces_opened}"
                  f"   surface changes: {result.surface_changes}")
            for inc in result.incidents:
                print(f"    incident: {inc}")

            totals = result.outcome_totals

            print("\n[3] a menu is productive, not inert")
            check("at least one surface change was observed",
                  result.surface_changes >= 1 and totals.get(O.SURFACE_CHANGED, 0) >= 1,
                  json.dumps(totals))
            check("the menu button was NOT pruned as inert",
                  "sf-menu" not in json.dumps(result.to_json().get("inertElements", "")),
                  "menu button pruned")

            print("\n[4] application content in another tab joins the graph")
            check("at least one in-scope surface was opened",
                  totals.get(O.NEW_SURFACE_IN_SCOPE, 0) >= 1, json.dumps(totals))
            check("in-scope surfaces were counted", result.surfaces_opened >= 1,
                  str(result.surfaces_opened))
            kinds = {s["kind"] for s in result.surfaces}
            check("both a tab and a scripted window were seen",
                  {S.TAB, S.POPUP} <= kinds, str(sorted(kinds)))

            # The parent -> action -> child relationship must survive.
            # `navigation` is keyed by "from|action|to"; the edges are the values.
            nav = (engine.store.data.get("navigation") or {}).values()
            child_edges = [e for e in nav if (e.get("action") or {}).get("opensSurface")]
            print(f"    surface edges: {[(e['from'], (e.get('action') or {}).get('name'), e['to']) for e in child_edges]}")
            check("the parent -> action -> child edge was recorded", len(child_edges) >= 1,
                  f"{len(child_edges)} edges")
            check("the edge names the surface kind",
                  all((e["action"]["opensSurface"] or {}).get("kind") in (S.TAB, S.POPUP)
                      for e in child_edges), str(child_edges[:2]))
            check("the child state is a real state with elements",
                  any(len((engine.store.data["states"].get(e["to"]) or {}).get("elements") or {}) > 2
                      for e in child_edges), "child state has no elements")
            check("a control that exists ONLY on the child surface was discovered",
                  "child-only" in json.dumps(engine.store.data["states"]),
                  "child-only control missing from the map")

            print("\n[4b] a child surface is CRAWLED, not just glanced at")
            # Scanning the landing state and closing the tab would map the door
            # and none of the rooms. The anchor matters: the first candidate on
            # the child is a "Back" link, and without returning to the landing
            # state every later candidate vanishes.
            inner = [e for e in nav if (e.get("action") or {}).get("onSurface")]
            print(f"    in-surface edges: "
                  f"{[(e['from'], (e.get('action') or {}).get('name'), e['to']) for e in inner]}")
            check("a state was discovered INSIDE a child surface", len(inner) >= 1,
                  f"{len(inner)} in-surface edges")
            check("the edge records which surface it happened on",
                  all((e["action"]["onSurface"] or {}).get("kind") in (S.TAB, S.POPUP)
                      for e in inner), str(inner[:1]))
            check("the deeper child state is in the map",
                  any("pedigree" in e["to"] for e in inner),
                  str([e["to"] for e in inner]))

            print("\n[4c] a child surface that asks for credentials is left alone")
            gate = [i for i in result.incidents
                    if i.get("kind") == "surface-unauthenticated"]
            check("the sign-in gate was recognised and refused", bool(gate), str(result.incidents))
            states_blob = json.dumps(engine.store.data["states"])
            check("no control from the gate entered the map",
                  "gate-continue" not in states_blob and "gate-pw" not in states_blob,
                  "a sign-in control was recorded from a child surface")
            check("and the crawl carried on afterwards", not result.aborted, result.aborted)

            print("\n[4d] a child surface the application closes is survivable")
            # It closes itself ~0.9 s after opening. Whether the crawler finishes
            # first or is caught mid-exploration is a race by design; what must
            # hold either way is that the parent crawl does not die.
            check("the crawl survived a self-closing surface",
                  not result.aborted and result.states_visited >= 2,
                  f"aborted={result.aborted!r}")
            check("a closed surface is never left marked open",
                  all(s.get("closed") for s in result.surfaces
                      if s.get("kind") in (S.TAB, S.POPUP)),
                  str([s for s in result.surfaces if not s.get("closed")]))

            print("\n[5] content that is not the application is refused")
            check("an out-of-scope surface was observed and disposed of",
                  totals.get(O.NEW_SURFACE_EXTERNAL, 0) >= 1
                  or totals.get(O.NEW_SURFACE_IRRELEVANT, 0) >= 1, json.dumps(totals))
            closed = [i for i in result.incidents
                      if str(i.get("kind", "")).startswith("surface-")]
            check("closing it was recorded as an incident", len(closed) >= 1, str(closed[:2]))
            check("no off-origin page became a state",
                  not [sid for sid, st in engine.store.data["states"].items()
                       if any("localhost" in o for o in (st.get("environmentsSeen") or []))],
                  "an off-origin surface entered the map")
            check("and the parent crawl survived it",
                  not result.aborted and result.states_visited >= 2,
                  f"aborted={result.aborted!r} states={result.states_visited}")

            print("\n[6] the crawl stayed safe and bounded")
            check("no leftover browsing contexts", len(engine.context.pages) <= 2,
                  f"{len(engine.context.pages)} pages still open")
            check("budgets were respected",
                  result.actions_clicked <= 60 and result.states_visited <= 25,
                  f"{result.actions_clicked} actions, {result.states_visited} states")
            check("nothing DANGEROUS was clicked",
                  not [t for t in result.timeline
                       if str(t.get("action", "")).lower() in ("delete", "remove", "save")],
                  str(result.timeline[:3]))
            check("every surface is accounted for in the report",
                  all({"id", "kind", "scope", "openedByAction"} <= set(s)
                      for s in result.surfaces), str(result.surfaces[:1]))

            print("\n[7] the intended workflow: a human signs in, then it runs itself")
            # This is what the tool is FOR (user, 2026-08-26): "i will login to the
            # application and after the login the application will work
            # autonomous". Automatic login is not required for that - and on the
            # real app it is refused, because PhenomeOne uses a two-step form.
            # What must hold is that nothing gates the autonomous crawl behind the
            # tool's own `authenticated` flag.
            app = server.url                       # the mock application root
            engine.authenticated = False           # never set by us, as after a
            engine.store.data["navigation"].clear()  # hand sign-in in the browser

            async def human_signs_in() -> None:
                await engine.page.goto(app, wait_until="domcontentloaded")
                await engine.page.wait_for_selector("#pw", timeout=20000)
                await engine.page.fill("#user", "tester@example.com")
                await engine.page.fill("#pw", "SurfacePass!-secret")
                await engine.page.get_by_test_id("login-submit").click()
                await engine.page.wait_for_selector("[data-testid=nav-research-groups]",
                                                    timeout=20000)

            engine.call(lambda: human_signs_in(), timeout=120)
            check("the human is signed in but the tool's auth flag is still False",
                  not engine.authenticated, f"authenticated={engine.authenticated}")

            crawler2 = SafeCrawler(engine, engine.store,
                                   CrawlLimits(max_states=6, max_actions=8, max_depth=2,
                                               time_budget_s=90.0))
            engine.crawl_active = True
            try:
                r2 = engine.call(lambda: crawler2.run(engine.page.url), timeout=300)
            finally:
                engine.crawl_active = False
            check("Safe Crawl ran without the tool ever authenticating itself",
                  r2 is not None and not r2.aborted, r2.aborted if r2 else "no result")
            check("and it explored autonomously", r2.states_visited >= 2 and r2.actions_clicked >= 2,
                  f"{r2.states_visited} states, {r2.actions_clicked} clicks")
            check("recording real application states",
                  len(r2.new_states) >= 1 or r2.edges_new >= 1,
                  f"new={r2.new_states} edges={r2.edges_new}")
            check("with no destructive action taken",
                  not [t for t in r2.timeline
                       if str(t.get("action", "")).lower() in ("delete", "save", "submit")],
                  str(r2.timeline[:3]))

            leaked = [str(p.relative_to(HOME)) for p in HOME.rglob("*")
                      if p.is_file() and b"localhost" in p.read_bytes()
                      and p.suffix == ".json" and "ui-map" in p.name]
            check("no off-origin url leaked into the ui map", not leaked, "; ".join(leaked))
        finally:
            engine.shutdown_blocking()

    print(f"\n{count - len(failures)}/{count} multi-surface checks passed")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    rc = main()
    shutil.rmtree(HOME, ignore_errors=True)
    sys.exit(rc)
