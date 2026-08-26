"""Surface scope + outcome classification. No browser required.

These two modules are the decision table for autonomous multi-surface crawling,
so they are tested in isolation: every branch here used to be a hard-coded rule
inside the crawler ("a popup is closed", "target=_blank is blocked before the
click"), which made them impossible to test without driving a browser.

Run: python tests/test_surfaces.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ["P1UID_HOME"] = tempfile.mkdtemp(prefix="p1uid-surf-")

from p1uid.crawler import outcomes as O                     # noqa: E402
from p1uid.crawler import surfaces as S                     # noqa: E402

failures: list[str] = []
count = 0

APP = "https://eksdemo-helm.phenome-networks.com/"


def check(label: str, ok: bool, detail: str = "") -> None:
    global count
    count += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


class FakePage:
    def __init__(self, url: str) -> None:
        self.url = url


def test_domain_rules() -> None:
    print("origin and domain rules")
    check("registrable domain of a subdomain",
          S.registrable_domain("knowledge-base.phenome-networks.com") == "phenome-networks.com")
    check("an IP host is left alone", S.registrable_domain("127.0.0.1") == "127.0.0.1")
    check("a single label is left alone", S.registrable_domain("localhost") == "localhost")
    check("same origin ignores path and hash",
          S.same_origin(APP + "#v=1&oid=12", APP))
    check("a different host is a different origin",
          not S.same_origin("https://knowledge-base.phenome-networks.com/", APP))
    check("a different port is a different origin",
          not S.same_origin("http://127.0.0.1:5000/", "http://127.0.0.1:5001/"))
    check("the knowledge base shares the domain",
          S.same_domain("https://knowledge-base.phenome-networks.com/", APP))
    check("an unrelated site does not", not S.same_domain("https://google.com/", APP))


def test_scope() -> None:
    """The two real cases pull in opposite directions."""
    print("\nsurface scope")

    async def scope(url, extra=()):
        return await S.scope_of(FakePage(url), APP, extra_origins=extra)

    def run(url, extra=()):
        return asyncio.run(scope(url, extra))

    check("a germplasm detail tab on the same origin is IN SCOPE",
          run(APP + "#v=1&r=m&oid=541306&otype=12") == S.IN_SCOPE)
    # The case that killed the "same domain + looks like an app" rule: the
    # Knowledge Base renders 12 visible controls, so every app-shell heuristic
    # calls it an application.
    check("the Knowledge Base is IRRELEVANT, not in scope",
          run("https://knowledge-base.phenome-networks.com/") == S.IRRELEVANT)
    check("an unrelated site is EXTERNAL", run("https://google.com/") == S.EXTERNAL)
    check("about:blank is UNKNOWN", run("about:blank") == S.UNKNOWN)
    check("an empty url is UNKNOWN", run("") == S.UNKNOWN)
    check("a declared extra origin is IN SCOPE",
          run("https://reports.phenome-networks.com/x",
              ("https://reports.phenome-networks.com",)) == S.IN_SCOPE)
    check("only crawlable scopes are crawlable",
          S.Surface("a", None, scope=S.IN_SCOPE).is_crawlable
          and not S.Surface("b", None, scope=S.IRRELEVANT).is_crawlable
          and not S.Surface("c", None, scope=S.EXTERNAL).is_crawlable
          and not S.Surface("d", None, scope=S.UNKNOWN).is_crawlable)
    closed = S.Surface("e", None, scope=S.IN_SCOPE)
    closed.closed = True
    check("a closed surface is not crawlable", not closed.is_crawlable)


def test_registry() -> None:
    print("\nsurface registry")
    reg = S.SurfaceRegistry(APP)
    main_page = FakePage(APP)
    main = reg.register(main_page, kind=S.MAIN, scope=S.IN_SCOPE)
    check("the main surface is registered", main.id == "main-1" and main.kind == S.MAIN)
    check("registering the same page twice returns the same surface",
          reg.register(main_page) is main and len(reg.surfaces) == 1)
    child = reg.register(FakePage(APP + "#oid=12"), kind=S.TAB, scope=S.IN_SCOPE,
                        opened_by_state="study", opened_by_action="Germplasm detail")
    check("a child surface records its provenance",
          child.opened_by_state == "study" and child.opened_by_action == "Germplasm detail")
    check("both surfaces are crawlable", len(reg.crawlable()) == 2)
    check("a page can be found again", reg.find(main_page) is main)
    reg.forget(child)
    check("a forgotten surface is not crawlable", len(reg.crawlable()) == 1)
    check("but it stays in the report", len(reg.to_json()) == 2)
    check("json carries scope and provenance",
          reg.to_json()[1]["openedByAction"] == "Germplasm detail")


def test_outcomes() -> None:
    print("\noutcome classification")

    def o(**kw):
        return O.classify(O.Observation(**kw))

    same = dict(state_before="a", state_after="a", signature_before="s1", signature_after="s1")
    check("nothing observable is no-change", o(**same).primary == O.NO_CHANGE)
    check("no-change is not productive", not o(**same).productive)

    # The menu case: no fingerprint input moves, but the DOM did.
    menu = o(state_before="a", state_after="a", signature_before="s1", signature_after="s2")
    check("a DOM change with no state change is surface-changed",
          menu.primary == O.SURFACE_CHANGED)
    check("and it IS productive, so the control is never pruned as inert",
          menu.productive, "an opened menu would be pruned again")
    check("and it does not poison the action", not menu.poisons)

    check("a state change is a new state",
          o(state_before="a", state_after="b").primary == O.NEW_STATE)

    # New surfaces, by scope.
    for scope, expected, poisons in ((S.IN_SCOPE, O.NEW_SURFACE_IN_SCOPE, False),
                                     (S.IRRELEVANT, O.NEW_SURFACE_IRRELEVANT, True),
                                     (S.EXTERNAL, O.NEW_SURFACE_EXTERNAL, True),
                                     (S.UNKNOWN, O.NEW_SURFACE_UNKNOWN, False)):
        r = o(state_before="a", state_after="a", new_surfaces=[(None, scope)])
        check(f"a {scope} surface classifies as {expected}", r.primary == expected, r.describe())
        check(f"a {scope} surface poisons={poisons}", r.poisons is poisons, r.describe())

    # One action, several facts.
    both = o(state_before="a", state_after="b", new_surfaces=[(None, S.IN_SCOPE)])
    check("a tab AND a state change are both recorded",
          O.NEW_SURFACE_IN_SCOPE in both and O.NEW_STATE in both, both.describe())
    check("the surface wins as primary", both.primary == O.NEW_SURFACE_IN_SCOPE)

    check("a native dialog is decisive and poisons",
          o(state_before="a", dialogs_raised=1).primary == O.NATIVE_DIALOG
          and o(state_before="a", dialogs_raised=1).poisons)
    check("session loss outranks everything",
          o(state_before="a", state_after="b", session_lost=True,
            new_surfaces=[(None, S.IN_SCOPE)]).primary == O.SESSION_LOST)
    check("navigating this surface off-origin is left-origin and poisons",
          o(state_before="a", state_after="b", origin_before="https://x",
            origin_after="https://y").primary == O.LEFT_ORIGIN)
    check("an unchanged origin is not left-origin",
          O.LEFT_ORIGIN not in o(state_before="a", state_after="b",
                                 origin_before="https://x", origin_after="https://x"))
    check("an unscannable destination is reported",
          o(state_before="a", scannable=False).primary == O.UNSCANNABLE)


if __name__ == "__main__":
    for fn in (test_domain_rules, test_scope, test_registry, test_outcomes):
        fn()
    print(f"\n{count - len(failures)}/{count} surface checks passed")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
    sys.exit(1 if failures else 0)
