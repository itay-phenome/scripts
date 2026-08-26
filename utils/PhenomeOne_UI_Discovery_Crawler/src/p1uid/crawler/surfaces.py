"""Surfaces: the places an application can put its UI.

A click does not always change the page you clicked on. It can open a modal, a
menu, an iframe, a new tab, or a separate window - and a crawler that assumes
one page can only ever explore one of those. The previous design encoded three
fixed rules ("a popup is closed", "a new tab is refused", "target=_blank is
blocked before clicking"), which meant a legitimate part of the application
opening in a tab was unreachable by construction.

This module replaces those rules with observation. A `Surface` is any page-level
context the application may occupy; `scope_of()` decides whether a newly opened
one belongs to the application, and the crawler decides what to do from the
*observed* outcome rather than from the attributes of the control it clicked.

Deciding scope
--------------
Measured on PhenomeOne, the two cases that matter pull in opposite directions:

  * a germplasm detail page opens in a **new tab on the same origin** and is
    entirely part of the application - it must be crawled;
  * `knowledge-base.phenome-networks.com` shares the registrable domain but is a
    documentation site - it must be ignored, without disturbing the parent crawl.

Scope is therefore decided by **origin**, plus an explicit allow-list for a
multi-host deployment. "Same domain and it looks like an application" was tried
and rejected: the Knowledge Base renders twelve visible controls, so every
app-shell heuristic calls it an application. A page cannot be asked whether it
is the software under test, so the second origin has to be declared rather than
guessed - and guessing wrong means crawling someone else's site.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from ..logging_setup import get

log = get("crawler.surfaces")

# Scope verdicts.
IN_SCOPE = "in-scope"           # part of the application: crawl it
EXTERNAL = "external"           # a different site: never crawl, never keep
IRRELEVANT = "irrelevant"       # our domain, but not the application (a docs site)
UNKNOWN = "unknown"             # could not be determined (about:blank, error page)

# Surface kinds.
MAIN = "main"                   # the page the crawl started on
TAB = "tab"                     # opened by a link with a target
POPUP = "popup"                 # opened by window.open()

_BLANKISH = ("about:", "chrome:", "edge:", "data:", "blob:", "javascript:")


def registrable_domain(host: str) -> str:
    """`knowledge-base.phenome-networks.com` -> `phenome-networks.com`.

    A deliberately simple last-two-labels rule. It over-groups a handful of
    multi-part public suffixes (`foo.co.uk` -> `co.uk`), which is why a same
    domain match is never sufficient on its own - it only permits the extra
    application-marker check below.
    """
    host = (host or "").lower().strip(".")
    if not host or host.replace(".", "").isdigit():
        return host
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def same_origin(a: str, b: str) -> bool:
    pa, pb = urlsplit(a or ""), urlsplit(b or "")
    return bool(pa.scheme) and (pa.scheme, pa.netloc) == (pb.scheme, pb.netloc)


def same_domain(a: str, b: str) -> bool:
    da = registrable_domain(urlsplit(a or "").hostname or "")
    db = registrable_domain(urlsplit(b or "").hostname or "")
    return bool(da) and da == db


@dataclass
class Surface:
    """One page-level context, and how we got to it."""

    id: str
    page: Any
    kind: str = MAIN
    url: str = ""
    scope: str = UNKNOWN
    # Provenance: which state, and which action, opened this surface. Keeping it
    # on the surface is what lets the navigation relationship survive being
    # explored out of order.
    opened_by_state: str = ""
    opened_by_action: str = ""
    # States already scanned while on this surface.
    visited: set[str] = field(default_factory=set)
    closed: bool = False

    @property
    def is_crawlable(self) -> bool:
        return self.scope == IN_SCOPE and not self.closed

    def describe(self) -> str:
        return f"{self.kind}:{self.id} {self.scope} {self.url[:70]}"

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "url": self.url[:200],
                "scope": self.scope, "openedByState": self.opened_by_state,
                "openedByAction": self.opened_by_action,
                "statesVisited": len(self.visited), "closed": self.closed}


async def scope_of(page: Any, app_url: str, extra_origins: tuple[str, ...] = ()) -> str:
    """Does this page belong to the application under test?

    Never raises: a page that cannot be inspected is UNKNOWN, and the caller
    treats UNKNOWN as "not ours" - failing closed, as everywhere else.
    """
    url = ""
    try:
        url = page.url or ""
    except Exception:
        return UNKNOWN
    if not url or url.startswith(_BLANKISH):
        return UNKNOWN
    if same_origin(url, app_url):
        return IN_SCOPE
    for allowed in extra_origins:
        if same_origin(url, allowed):
            return IN_SCOPE
    # Anything on another origin is not ours unless it was named explicitly.
    #
    # "Same registrable domain plus it looks like an application" was tried and
    # rejected: `knowledge-base.phenome-networks.com` renders 12 visible
    # controls, so every app-shell heuristic says "application" about a
    # documentation site. There is no reliable way to tell a sibling service
    # from the application by inspecting the page, and guessing wrong means
    # crawling somebody else's site - so a second origin has to be declared.
    #
    # This costs nothing in practice: the application's own surfaces are
    # same-origin (a germplasm detail tab included), and a genuinely multi-host
    # deployment names its extra origins once.
    verdict = IRRELEVANT if same_domain(url, app_url) else EXTERNAL
    log.debug("Off-origin surface %s -> %s", url[:80], verdict)
    return verdict


class SurfaceRegistry:
    """The surfaces seen during one crawl, and which one we are working on."""

    def __init__(self, app_url: str, extra_origins: tuple[str, ...] = ()) -> None:
        self.app_url = app_url
        self.extra_origins = extra_origins
        self.surfaces: dict[str, Surface] = {}
        self._by_page: dict[int, str] = {}
        self._n = 0

    def _next_id(self, kind: str) -> str:
        self._n += 1
        return f"{kind}-{self._n}"

    def register(self, page: Any, kind: str = MAIN, scope: str = UNKNOWN,
                 opened_by_state: str = "", opened_by_action: str = "") -> Surface:
        existing = self.find(page)
        if existing is not None:
            return existing
        sid = self._next_id(kind)
        url = ""
        try:
            url = page.url or ""
        except Exception:
            pass
        surface = Surface(id=sid, page=page, kind=kind, url=url, scope=scope,
                          opened_by_state=opened_by_state, opened_by_action=opened_by_action)
        self.surfaces[sid] = surface
        self._by_page[id(page)] = sid
        return surface

    def find(self, page: Any) -> Surface | None:
        sid = self._by_page.get(id(page))
        return self.surfaces.get(sid) if sid else None

    def forget(self, surface: Surface) -> None:
        surface.closed = True
        self._by_page.pop(id(surface.page), None)

    def crawlable(self) -> list[Surface]:
        return [s for s in self.surfaces.values() if s.is_crawlable]

    def to_json(self) -> list[dict[str, Any]]:
        return [s.to_json() for s in self.surfaces.values()]
