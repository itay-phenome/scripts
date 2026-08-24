"""UI-state fingerprinting (spec 14).

A SaaS SPA route like ``/research-group/123`` covers many distinct UI states,
so the URL alone cannot identify one. The fingerprint therefore combines:

    normalised route + active tab + open dialogs + tab set + landmark roles

and deliberately *excludes* volatile material: record ids, customer/business
names, timestamps, and result counts. Landmark **roles** are hashed but their
**names** are not, because a name like "Research Group ABC" is data, not
structure.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

# Path segments that are record identifiers rather than structure.
_ID_PATTERNS = [
    (re.compile(r"^[0-9]+$"), ":id"),
    (re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I), ":uuid"),
    (re.compile(r"^[0-9a-f]{24,}$", re.I), ":hash"),
    (re.compile(r"^[A-Za-z]*[0-9]{4,}[A-Za-z0-9_-]*$"), ":id"),
    (re.compile(r"^[A-Za-z0-9_-]{28,}$"), ":token"),
]

_SLUG_STOP = {"", "app", "index", "home", "main", "ui", "web", "en", "#"}


def normalise_route(path: str, hash_frag: str = "") -> str:
    """`/research-group/123/germplasms` -> `/research-group/:id/germplasms`."""
    combined = path or "/"
    frag = (hash_frag or "").lstrip("#")
    if frag and frag.startswith("/"):
        combined = combined.rstrip("/") + "/#" + frag
    elif frag:
        combined = combined.rstrip("/") + "/#" + frag
    parts = []
    for seg in combined.split("/"):
        if not seg:
            parts.append(seg)
            continue
        repl = seg
        for pat, token in _ID_PATTERNS:
            if pat.match(seg):
                repl = token
                break
        parts.append(repl)
    route = "/".join(parts) or "/"
    route = re.sub(r"/{2,}", "/", route)
    return route if route.startswith("/") else "/" + route


def slugify(text: str, max_len: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:max_len].strip("-")


@dataclass
class Fingerprint:
    digest: str                     # 12 hex chars, stable across sessions
    slug: str                       # human-readable base for the state id
    label: str                      # display label for reports/graph
    route: str
    signals: dict[str, Any] = field(default_factory=dict)


def fingerprint(structure: dict[str, Any]) -> Fingerprint:
    route = normalise_route(structure.get("path", "/"), structure.get("hash", ""))
    active_tab = structure.get("activeTab") or ""
    dialogs = sorted(structure.get("dialogs") or [])
    tabs = sorted(structure.get("tabs") or [])
    landmark_roles = sorted({lm.split(":", 1)[0] for lm in (structure.get("landmarks") or [])})

    signals = {
        "route": route,
        "activeTab": active_tab,
        "dialogs": dialogs,
        "tabs": tabs,
        "landmarkRoles": landmark_roles,
    }
    material = "\n".join([
        route,
        "tab=" + active_tab,
        "dialogs=" + "|".join(dialogs),
        "tabs=" + "|".join(tabs),
        "landmarks=" + "|".join(landmark_roles),
    ])
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]

    # Human-readable identity. Route + tab + dialog, all structural.
    route_slug = "-".join(
        p for p in (slugify(seg.replace(":", "")) for seg in route.split("/"))
        if p and p not in _SLUG_STOP and p not in {"id", "uuid", "hash", "token"}
    )
    bits = [b for b in (route_slug, slugify(active_tab, 24)) if b]
    if dialogs:
        bits.append("dialog-" + slugify(dialogs[0], 24))
    slug = "-".join(bits)
    if not slug:
        # A bare route such as /app/ carries no structure in the path: name the
        # state after its heading instead. Identity still comes from `digest`.
        heading = structure.get("h1") or (structure.get("headings") or [""])[0] or structure.get("title") or ""
        slug = slugify(heading, 40)
    slug = re.sub(r"-{2,}", "-", slug)[:72].strip("-") or "root"

    label_bits = []
    heading = structure.get("h1") or (structure.get("headings") or [""])[0]
    if heading:
        label_bits.append(heading)
    if active_tab:
        label_bits.append(f"> {active_tab}")
    if dialogs:
        label_bits.append(f"[dialog: {dialogs[0]}]")
    label = " ".join(label_bits) or structure.get("title") or route

    return Fingerprint(digest=digest, slug=slug, label=label[:120], route=route, signals=signals)
