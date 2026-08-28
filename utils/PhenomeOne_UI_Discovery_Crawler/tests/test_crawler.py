"""Safe Crawl tests against the hardened mock app.

The crawl must map the app on its own AND leave it untouched. The mock records
every side effect it would have suffered (`window.__sideEffects`), so the test
can assert the crawler triggered none of them.

Run: python tests/test_crawler.py [--headed] [--debug]
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

HOME = Path(tempfile.mkdtemp(prefix="p1uid-crawl-"))
os.environ["P1UID_HOME"] = str(HOME)

from serve_mock import MockServer                          # noqa: E402
from p1uid import paths                                    # noqa: E402
from p1uid.browser.controller import Engine                # noqa: E402
from p1uid.crawler.bfs import CrawlLimits                  # noqa: E402
from p1uid.logging_setup import setup                      # noqa: E402

PASSWORD = "CrawlPass!-secret"
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
        events: "queue.Queue[dict]" = queue.Queue()
        engine = Engine(events, headless="--headed" not in sys.argv)
        engine.start()
        try:
            print(f"\nSafe Crawl test  home={HOME}\n")
            engine.call(lambda: engine.op_login(server.url, "t@e.st", PASSWORD), timeout=180)
            check("logged into the mock app", engine.authenticated)

            limits = CrawlLimits(max_states=25, max_actions=120, max_depth=5,
                                 time_budget_s=180, per_state_actions=25)
            engine.call(lambda: engine.op_crawl(limits), timeout=600)

            summary = json.loads(paths.CRAWL_SUMMARY_FILE.read_text(encoding="utf-8"))
            counts = engine.store.counts()
            states = engine.store.data["states"]
            nav = engine.store.data["navigation"]

            print(f"\n  crawl: {summary['statesVisited']} states visited, "
                  f"{len(summary['newStates'])} new, {summary['actionsClicked']} clicks, "
                  f"{summary['newNavigationPaths']} new paths, {summary['replays']} replays, "
                  f"{summary['durationSeconds']}s")
            print(f"  classifications seen: {summary['classificationTotals']}")
            print(f"  not clicked: {summary['skippedByReason']}")
            print(f"  incidents: {summary['incidents'] or 'none'}")
            print(f"  limit hit: {summary['limitHit'] or 'none'} | aborted: "
                  f"{summary['abortedBecause'] or 'no'}\n")

            # ---------------- it actually explored
            check("crawl visited several states", summary["statesVisited"] >= 5,
                  str(summary["statesVisited"]))
            check("crawl clicked actions autonomously", summary["actionsClicked"] >= 8,
                  str(summary["actionsClicked"]))
            check("crawl learned navigation edges", summary["newNavigationPaths"] >= 5,
                  str(summary["newNavigationPaths"]))
            check("crawl was not aborted", not summary["abortedBecause"],
                  summary["abortedBecause"])
            check("map now holds the crawled states", counts["states"] >= 5, str(counts["states"]))

            ids = " ".join(states)
            check("crawl reached the tabbed research-group states",
                  "research-group-germplasms" in ids and "research-group-variables" in ids, ids)
            check("crawl reached the Admin tab", "admin" in ids.lower(), ids)

            # ---------------- it stayed safe
            edges = list(nav.values())
            crawl_edges = [e for e in edges if e["action"].get("trigger") == "safe-crawl"]
            check("crawl-authored edges are labelled as such", bool(crawl_edges),
                  f"{len(crawl_edges)} of {len(edges)}")
            unsafe = [e["action"]["name"] for e in crawl_edges
                      if e["action"].get("safety") != "SAFE_NAVIGATION"]
            check("every crawl edge came from a SAFE_NAVIGATION action", not unsafe,
                  "; ".join(unsafe))

            import re
            danger = re.compile(r"delete|remove|save|submit|import|execute|archive|publish|"
                                r"approve|reject|reset|send|log ?out|sign ?out", re.I)
            clicked = [t["action"] for t in summary["timeline"]]
            hits = [a for a in clicked if danger.search(a or "")]
            check("no dangerous label was ever clicked", not hits, "; ".join(hits))

            check("dangerous/unknown actions were counted as skipped",
                  summary["skippedByReason"].get("dangerous", 0) > 0
                  and summary["skippedByReason"].get("unknown", 0) > 0,
                  str(summary["skippedByReason"]))
            check("no native dialog was ever accepted",
                  not [i for i in summary["incidents"] if i["kind"] == "native-dialog"],
                  str(summary["incidents"]))
            check("still authenticated after the crawl", not summary["abortedBecause"])

            # ---------------- the mock recorded no side effects
            async def side_effects():
                return await engine.page.evaluate(
                    "() => (window.__sideEffects || []).slice(0, 50)")
            fx = engine.call(lambda: side_effects(), timeout=60)
            check("the application recorded ZERO side effects", not fx, str(fx))

            # ---------------- outputs
            check("crawl-summary.json written", paths.CRAWL_SUMMARY_FILE.is_file())
            check("navigation graph regenerated", paths.NAV_GRAPH_FILE.is_file())
            navjson = json.loads(paths.NAV_GRAPH_FILE.read_text(encoding="utf-8"))
            print("  --- navigation tree learned WITHOUT a human ---")
            for line in navjson.get("tree", [])[:22]:
                print("   " + line)
            print()
            check("tree has real depth", any(l.startswith("    ") or "│" in l
                                            for l in navjson.get("tree", [])))

            # ---------------- budget enforcement
            limits2 = CrawlLimits(max_states=2, max_actions=3, max_depth=1, time_budget_s=60)
            engine.call(lambda: engine.op_crawl(limits2), timeout=300)
            s2 = json.loads(paths.CRAWL_SUMMARY_FILE.read_text(encoding="utf-8"))
            check("budget limits are enforced", s2["actionsClicked"] <= 3 and bool(s2["limitHit"]),
                  f"clicks={s2['actionsClicked']} limit={s2['limitHit']}")

            # ---------------- idempotence: a second full crawl adds no duplicates
            before = (counts["states"], counts["navigationPaths"])
            engine.call(lambda: engine.op_crawl(limits), timeout=600)
            after = engine.store.counts()
            check("re-crawling does not duplicate states",
                  after["states"] == before[0], f"{before[0]} -> {after['states']}")
            check("re-crawling does not duplicate navigation paths",
                  after["navigationPaths"] == before[1],
                  f"{before[1]} -> {after['navigationPaths']}")

            # ---------------- global chrome must not eat the whole budget
            #
            # Measured on real PhenomeOne (2026-08-28): the research-group tree
            # is present in every state and sorts first, and once a research
            # group had one identity every row led to the same place. All 60
            # clicks of a 400-action crawl were tree rows and no tab was ever
            # reached. `chrome.html` is that shape: 10 rows that all navigate to
            # `#panel=open`, and three tabs that each open a state of their own
            # and sort AFTER every row ("Temp" < "Tomato" < "Trials"). On an
            # 8-action budget the tabs are reachable only by learning that the
            # rows are one edge.
            root = server.url.rsplit("/app/", 1)[0] + "/"
            engine.call(lambda: engine.open_url(root + "chrome.html"), timeout=120)
            limits3 = CrawlLimits(max_states=10, max_actions=8, max_depth=3,
                                  time_budget_s=180, per_state_actions=30)
            engine.call(lambda: engine.op_crawl(limits3), timeout=600)
            s3 = json.loads(paths.CRAWL_SUMMARY_FILE.read_text(encoding="utf-8"))
            clicked3 = [t["action"] for t in s3["timeline"]]
            ROWS = {"Canola", "Eggplant", "Kiwi", "Oilseed", "Peas", "Pepper",
                    "Sorghum", "Temp", "Tomato", "Tomato Demo"}
            TABS = {"Trials", "Variables", "Zones"}
            row_clicks = [c for c in clicked3 if c in ROWS]
            tab_clicks = [c for c in clicked3 if c in TABS]
            print(f"\n  global chrome: clicked {clicked3}")
            print(f"  skipped: {s3['skippedByReason']}\n")

            check("the tree is still tried first (it sorts before every tab)",
                  clicked3 and clicked3[0] in ROWS, str(clicked3[:2]))
            check("the same edge is proven a few times, not once per sibling",
                  len(row_clicks) <= 6, f"{len(row_clicks)} row clicks: {row_clicks}")
            check("and the siblings are reported as skipped, never silently",
                  s3["skippedByReason"].get("same-shape-known-edge", 0) >= 5,
                  str(s3["skippedByReason"]))
            check("so the budget reached all three tabs",
                  set(tab_clicks) == TABS, f"{tab_clicks}")
            ids3 = " ".join(engine.store.data["states"])
            check("each tab opened a state of its own",
                  all(f"panel-{t.lower()}" in ids3 for t in TABS), ids3)
            check("the crawl was not aborted", not s3["abortedBecause"], s3["abortedBecause"])
        finally:
            engine.shutdown_blocking()

    leaked = [str(p.relative_to(HOME)) for p in HOME.rglob("*")
              if p.is_file() and PASSWORD.encode() in p.read_bytes()]
    check("no secret written during the crawl", not leaked, "; ".join(leaked))

    print(f"\n{count - len(failures)}/{count} crawler checks passed")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    rc = main()
    shutil.rmtree(HOME, ignore_errors=True)
    sys.exit(rc)
