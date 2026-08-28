"""UI-state fingerprinting (spec 14).

A SaaS SPA route like ``/research-group/123`` covers many distinct UI states,
so the URL alone cannot identify one. The fingerprint therefore combines:

    normalised route + active tab + open dialogs + tab set + landmark roles

and deliberately *excludes* volatile material: record ids, customer/business
names, timestamps, and result counts. Landmark **roles** are hashed but their
**names** are not, because a name like "Research Group ABC" is data, not
structure.

Dialog **titles** are hashed, because "Add Germplasm" and "Confirm delete" are
genuinely different states - but they are normalised first, since a title like
"Edit INV-0001" would otherwise produce one state per record. See
`normalise_dialog_title`.
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

# --------------------------------------------------------------- dialog titles
#
# A dialog title routinely embeds the record it acts on - "Edit INV-0001" - so
# hashing it verbatim fragments the state map into one state per record. The
# rule below is deliberately narrow: individual TOKENS that look like record
# identifiers, dates or times are replaced with the same `:id`-style
# placeholders already used for route segments, and everything else is kept
# exactly as written. Every purely alphabetic word survives, so "Add
# Germplasm", "Edit Germplasm" and "Confirm delete" remain three distinct
# states. A token must contain a digit to be considered volatile at all.
#
# This also keeps record names - business data - out of the UI map entirely,
# which the spec asks for independently of fingerprint stability.
_TITLE_TOKENS = [
    (re.compile(r"^#[0-9]+$"), ":id"),                                  # #4521
    (re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I), ":uuid"),
    (re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"), ":date"),             # 2025-02-11
    (re.compile(r"^[0-9]{1,2}[/.][0-9]{1,2}[/.][0-9]{2,4}$"), ":date"),  # 11/02/2025
    (re.compile(r"^[0-9]{1,2}:[0-9]{2}(:[0-9]{2})?$"), ":time"),        # 14:03
    (re.compile(r"^[0-9a-f]{24,}$", re.I), ":hash"),
    (re.compile(r"^[0-9]{4,}$"), ":id"),                                # 4521, not "3"
    (re.compile(r"^[A-Za-z]{1,6}[-_][0-9]{2,}([-_][A-Za-z0-9]+)*$"), ":id"),  # INV-0001
    (re.compile(r"^[A-Za-z]{1,6}[0-9]{4,}$"), ":id"),                   # INV0001
    (re.compile(r"^(?=[A-Za-z0-9_-]*[0-9])[A-Za-z0-9_-]{28,}$"), ":token"),
]

# Stripped only to test a token; a token that turns out to be stable keeps its
# punctuation, so `Confirm delete?` is untouched.
_TITLE_EDGE = "\"'“”‘’()[]{}<>,.;:?!…-–— "


def normalise_dialog_title(title: str) -> str:
    """`Edit INV-0001` -> `Edit :id`; `Add Germplasm` -> `Add Germplasm`.

    Whitespace is collapsed. Tokens are examined one at a time and only
    replaced when the token *itself* looks like a record identifier, so a
    meaningful title is never broadly stripped.
    """
    out: list[str] = []
    for token in (title or "").split():
        core = token.strip(_TITLE_EDGE)
        repl = ""
        if core:
            for pat, placeholder in _TITLE_TOKENS:
                if pat.match(core):
                    repl = placeholder
                    break
        out.append(repl or token)
    return " ".join(out)


_PLACEHOLDER_PAIR_RE = re.compile(r"=(:(?:id|uuid|hash|token|name|date|time))?$")


def _slug_segment(seg: str) -> str:
    """Readable slug text for one route segment.

    A normalised parameter carries no identity - `oid=:id` and `oname=:name` are
    the same in every state that has them - so they are dropped from the human
    id. Identity still comes from `digest`; this only decides readability.
    """
    if "=" in seg:
        keep = [pair for pair in re.split(r"[&;]", seg)
                if pair and not _PLACEHOLDER_PAIR_RE.search(pair)]
        seg = "&".join(keep)
    return slugify(seg.replace(":", ""))


def _dialog_slug(normalised: str, max_len: int = 24) -> str:
    """Slug from the stable words only - a placeholder is not a name."""
    kept = [t for t in normalised.split() if not t.startswith(":")]
    return slugify(" ".join(kept), max_len)


# Parameters whose VALUE names a record rather than describing structure. Their
# values are business data and must not enter the map at all.
_NAME_PARAM_RE = re.compile(r"(^|_)(o?name|label|title|caption)$", re.I)

# Values that are record identifiers. Deliberately the same threshold as
# `normalise_dialog_title`: a run of 4+ digits is an id, 1-3 digits is an enum.
# `otype=23` (Study) and `otype=4` (Program) are *structure* and must survive -
# they select genuinely different screens - while `oid=541306` must not.
_PARAM_ID_PATTERNS = [
    (re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I), ":uuid"),
    (re.compile(r"^[0-9a-f]{24,}$", re.I), ":hash"),
    (re.compile(r"^[0-9]{4,}$"), ":id"),                          # 541306
    (re.compile(r"^[0-9]+([.~:_-][0-9]+)+$"), ":id"),             # 8.393426.541306, 541306~24
    (re.compile(r"^[A-Za-z]{1,6}[-_][0-9]{2,}([-_][A-Za-z0-9]+)*$"), ":id"),   # INV-0001
    (re.compile(r"^[A-Za-z]{1,6}[0-9]{4,}$"), ":id"),             # INV0001
    (re.compile(r"^(?=[A-Za-z0-9_-]*[0-9])[A-Za-z0-9_-]{28,}$"), ":token"),
]


# Parameters whose value is an identifier whatever it looks like.
#
# The length rule above cannot decide these. Measured on real PhenomeOne
# (2026-08-28): the research group at `p=8.393426.541306&oid=541306~24`
# normalised to one state, but the group at `p=8&oid=8` kept its digits - 1 to 3
# digits reads as an enum - so the SAME screen had two identities, decided by how
# many digits the record id happened to have. The crawl then treated one research
# group as unexplored and the other 19 as already seen.
#
# `otype` really is an enum and must keep its value: `otype=4` (Program) and
# `otype=23` (Study) are different screens. So the rule is by parameter NAME,
# never by value length.
_ID_PARAM_RE = re.compile(r"^(p|o?id|pid|rid|gid|sid|uid|eid|recid|objid|parent)$", re.I)


def _normalise_param_value(key: str, value: str) -> str:
    """One `key=value` pair from a query string or hash fragment."""
    if not value:
        return value
    if _NAME_PARAM_RE.search(key):
        return ":name"                      # a record name: never structural
    if _ID_PARAM_RE.match(key.strip()) and any(ch.isdigit() for ch in value):
        # A digit is what makes it an identifier. A purely alphabetic value under
        # the same key is a named position and stays: PhenomeOne's landing state
        # is `oid=m` ("Mine"), which is structure, not a record.
        return ":id"
    for pat, token in _PARAM_ID_PATTERNS:
        if pat.match(value):
            return token
    return value


def _normalise_params(segment: str) -> str:
    """Normalise `a=1&b=x` inside a path segment or hash fragment.

    A single-page application routinely carries its whole location in one hash
    fragment - `#v=1&r=m&p=8.393426.541306&oid=541306~24&otype=24&oname=List` -
    so segment-level id matching never sees the ids: the entire fragment is one
    segment. Without this, every record opened becomes its own UI state and the
    record's *name* ends up inside the state id.
    """
    if "=" not in segment:
        return segment
    out = []
    for pair in re.split(r"([&;])", segment):
        if pair in ("&", ";") or not pair:
            out.append(pair)
            continue
        if "=" in pair:
            key, _, value = pair.partition("=")
            out.append(f"{key}={_normalise_param_value(key, value)}")
        else:
            out.append(pair)
    return "".join(out)


def normalise_route(path: str, hash_frag: str = "") -> str:
    """`/research-group/123/germplasms` -> `/research-group/:id/germplasms`.

    Query-style parameters inside a segment or hash are normalised too, so
    `#...&oid=541306&otype=4&oname=Test` becomes `#...&oid=:id&otype=4&oname=:name`
    - one state per screen, not one per record.
    """
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
        else:
            # Not an id as a whole; it may still carry key=value parameters.
            repl = _normalise_params(seg)
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
    # Volatile record tokens are normalised out before hashing, so the edit
    # dialog for every record is one state. Duplicates are kept: two stacked
    # dialogs are structurally different from one.
    dialogs = sorted(normalise_dialog_title(d) for d in (structure.get("dialogs") or []))
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
        p for p in (_slug_segment(seg) for seg in route.split("/"))
        if p and p not in _SLUG_STOP and p not in {"id", "uuid", "hash", "token"}
    )
    bits = [b for b in (route_slug, slugify(active_tab, 24)) if b]
    if dialogs:
        d = _dialog_slug(dialogs[0])
        bits.append("dialog-" + d if d else "dialog")
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
