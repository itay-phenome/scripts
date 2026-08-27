"""Action safety classification for autonomous discovery (Safe Crawl foundation).

Nothing here clicks anything. It answers one question about an element record
produced by the injected core:

    if a machine clicked this, could it change or destroy data?

Four verdicts:

    SAFE_NAVIGATION  moves around the UI: tabs, same-origin links, expanders.
                     The ONLY class a crawler may click without being told to.
    CONDITIONAL      recognised, plausibly harmless, but not provably read-only
                     (opens a dialog, toggles a control, closes a modal).
                     Requires an explicit opt-in per category.
    DANGEROUS        writes, deletes, sends, leaves the app, or leaves the origin.
    UNKNOWN          not understood. Never clicked. An unlabelled icon button is
                     the canonical case: it might be Save, it might be Delete.

Design rules
------------
* **Fail closed.** Anything that is not positively recognised as navigation ends
  up CONDITIONAL or UNKNOWN, never SAFE_NAVIGATION.
* **Structure beats words.** A button called "Search" that submits a POST form
  is DANGEROUS regardless of its label.
* ``auto_clickable`` is the single gate a crawler consults. It is True only for
  SAFE_NAVIGATION with no blocking flag, and is asserted False for every
  DANGEROUS and UNKNOWN verdict.
* Deterministic and offline: pure string/attribute rules, no model, no network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

SAFE_NAVIGATION = "SAFE_NAVIGATION"
CONDITIONAL = "CONDITIONAL"
DANGEROUS = "DANGEROUS"
UNKNOWN = "UNKNOWN"

CLASSES = (SAFE_NAVIGATION, CONDITIONAL, DANGEROUS, UNKNOWN)

# --------------------------------------------------------------------- flags
FLAG_DOWNLOAD = "download"
FLAG_MAILTO = "mailto"
FLAG_JAVASCRIPT = "javascript-url"
FLAG_BLOB = "blob-url"
FLAG_DATA_URL = "data-url"
FLAG_EXTERNAL_SCHEME = "external-scheme"
FLAG_CROSS_ORIGIN = "cross-origin"
FLAG_NEW_TAB = "new-tab"
FLAG_FORM_SUBMIT = "form-submit"
FLAG_FORM_RESET = "form-reset"
FLAG_POST = "post-request"
FLAG_DANGEROUS_VERB = "dangerous-verb"
FLAG_DANGEROUS_QUERY = "dangerous-query"
FLAG_HIDDEN = "not-visible"
FLAG_DISABLED = "disabled"
FLAG_UNLABELLED = "unlabelled"
FLAG_AUTH = "leaves-session"

# Flags that veto automatic clicking no matter how the action is classified.
BLOCKING_FLAGS = frozenset({
    FLAG_DOWNLOAD, FLAG_MAILTO, FLAG_JAVASCRIPT, FLAG_BLOB, FLAG_DATA_URL,
    FLAG_EXTERNAL_SCHEME, FLAG_FORM_SUBMIT,
    FLAG_FORM_RESET, FLAG_POST, FLAG_DANGEROUS_VERB, FLAG_DANGEROUS_QUERY,
    FLAG_HIDDEN, FLAG_DISABLED,
    FLAG_AUTH,
})

# Recorded, but NOT blocking. `new-tab` describes where a control *might* lead,
# and refusing it before the click made whole regions of an application
# unreachable by construction: PhenomeOne opens a germplasm detail page in a new
# tab on its own origin, and `new-tab` meant that link was never clicked at all.
#
# What the click did is decided from the observed result instead (see
# `crawler/outcomes.py`): the new context is classified by its URL and explored
# only if it is the application, otherwise it is closed and the action poisoned.
#
# `cross-origin` is deliberately NOT here. It stays DANGEROUS via the URL-level
# rule below, because a link that advertises it leaves the application offers
# nothing to a crawler mapping that application - while an external surface the
# application produces by itself (a scripted `window.open`, a redirect) is still
# observed and handled, since those carry no such attribute to judge in advance.
OBSERVE_NOT_BLOCK = frozenset({FLAG_NEW_TAB})

ALLOWED_URL_SCHEMES = frozenset({"http", "https"})

# --------------------------------------------------------------------- words
# Verbs that write, destroy, dispatch, or end the session. Word-boundary
# matched against every label an element carries.
_DANGEROUS_WORDS = [
    # required minimum
    "delete", "remove", "save", "submit", "import", "execute", "archive",
    "publish", "approve", "reject", "reset", "send", "logout", "log out",
    "sign out", "signout", "log off", "logoff",
    # equally destructive in practice
    "discard", "erase", "purge", "destroy", "drop", "truncate", "wipe",
    "revoke", "deactivate", "disable", "suspend", "terminate", "cancel",
    "unpublish", "retract", "withdraw", "restore", "rollback", "revert",
    "overwrite", "replace", "merge", "split", "duplicate", "clone", "copy",
    "move", "rename", "upload", "export", "download", "print", "email",
    "invite", "share", "assign", "unassign", "confirm", "accept", "decline",
    "apply", "commit", "push", "sync", "synchronise", "synchronize",
    "deploy", "migrate", "run", "start", "stop", "restart", "kill", "abort",
    "pay", "buy", "order", "checkout", "subscribe", "unsubscribe", "renew",
    "generate", "recalculate", "recompute", "process", "finalize", "finalise",
    # Observed on real PhenomeOne 2026-08-26: these mutate and were UNKNOWN,
    # i.e. safe only by accident. "Calculate variables" writes computed values,
    # "Define germplasm columns" changes the schema, "Distribute lots" moves
    # inventory between plots.
    "calculate", "define", "distribute",
    "lock", "unlock", "enable", "activate", "create", "add", "new", "update",
    "edit", "modify", "change", "set", "clear", "empty", "flush", "reindex",
    "validate", "verify", "notify", "alert", "escalate", "close ticket",
]
_DANGEROUS_RE = re.compile(r"(?<![a-z])(" + "|".join(
    re.escape(w).replace(r"\ ", r"\s*") for w in _DANGEROUS_WORDS) + r")(?![a-z])", re.I)

# Session-ending specifically: worth its own flag, since losing the session
# ends the whole crawl rather than just corrupting one record.
_AUTH_RE = re.compile(r"(?<![a-z])(log\s*out|logout|sign\s*out|signout|log\s*off|logoff)(?![a-z])", re.I)

# Positively read-only navigation vocabulary.
_NAV_WORDS = [
    "view", "details", "detail", "show", "preview", "open", "expand", "collapse",
    "more", "less", "next", "previous", "prev", "first", "last", "back",
    "page", "go to", "browse", "overview", "summary", "list", "read",
]
# Application vocabulary: entity names that title a *view* rather than an action.
#
# The generic verbs above cannot cover domain nouns, so an application whose
# navigation is named after its own entities reads as UNKNOWN throughout and the
# crawler cannot move. Measured against the real PhenomeOne label set on
# 2026-08-26: only 3 of 54 documented labels were auto-clickable, and every tab
# and sidebar view was UNKNOWN.
#
# Provenance: the documented PhenomeOne navigation vocabulary - global tabs,
# Trial sidebar children, hamburger modules, record-detail tabs - cross-checked
# against the states the real run actually produced.
#
# A destructive verb always wins, because dangerous matching runs first: "Delete
# columns", "Upload lots - List" and "Add studies" stay DANGEROUS even though
# they contain a navigation noun. These words only decide the case where nothing
# destructive is present.
_APP_NAV_WORDS = [
    # global tabs: Research Group / Program / Study
    "germplasms", "variables", "observations", "cultivars", "images",
    "inventory", "entities", "plots", "plants", "selections", "crosses",
    # Trial sidebar children (List and Overview are already generic nav words)
    "map",
    # hamburger menu modules
    "organization", "varieties", "locales", "forms", "insights", "phenogene",
    "image gallery", "home", "activities",
    # record-detail tabs
    "pedigree tree", "attributes",
    # the Actions menu opener: revealing a menu commits nothing, and every
    # item inside it is classified separately (Delete stays DANGEROUS).
    "actions",
]
_NAV_RE = re.compile(r"(?<![a-z])(" + "|".join(
    re.escape(w).replace(r"\ ", r"\s*") for w in _NAV_WORDS + _APP_NAV_WORDS) + r")(?![a-z])", re.I)

# Words that merely dismiss a transient surface. Harmless in isolation, but only
# ever CONDITIONAL - "Close account" must not slip through as "Close".
_DISMISS_RE = re.compile(r"^\s*(close|cancel|dismiss|back|x|×|✕|hide|no|not now|later)\s*"
                         r"(dialog|modal|window|panel|menu|popup|drawer)?\s*$", re.I)

# A dismissal verb aimed at something that is NOT a transient UI surface
# ("Close account") is destructive, not a dismissal.
_DISMISS_START_RE = re.compile('^\\s*(close|cancel|dismiss|hide)\\b', re.I)

# The affirmative half of a confirm dialog. These EXECUTE whatever was asked,
# so they must never be mistaken for a harmless "close this popup".
_CONFIRM_RE = re.compile(r"^\s*(ok|okay|yes|done|apply|accept|continue|proceed|"
                         r"got it|understood|i agree|agree)\s*!?\s*$", re.I)

# Distinguishes "Next page" (pagination = navigation) from a bare "Next",
# which may be a wizard step that commits data.
_PAGINATION_RE = re.compile('\\bpages?\\b|\\bpagin', re.I)

# Recognised-but-not-navigation vocabulary: opening editors, searching, sorting.
_CONDITIONAL_RE = re.compile(
    r"(?<![a-z])(search|filter|sort|refresh|reload|group|column|settings|"
    r"preferences|options|help|about|toggle|select|choose|pick|upload file)(?![a-z])", re.I)

# --------------------------------------------------------- element categories
_NAV_ROLES = frozenset({"tab", "treeitem", "link"})
_TOGGLE_TYPES = frozenset({"checkbox", "radio", "switch", "slider", "spinbutton"})
_INPUT_TYPES = frozenset({"textbox", "searchbox", "textarea", "combobox", "listbox",
                          "option", "password"})
_OPAQUE_TYPES = frozenset({"clickable", "focusable", "testid-element", ""})

# How many same-shaped controls make a list. Three is the smallest number
# that cannot be a coincidence of layout, and a two-item menu is better left
# UNKNOWN than guessed at.
_LIST_SHAPE_MIN = 3

# input[type=...] values that submit or reset a form when clicked.
_SUBMIT_INPUTS = frozenset({"submit", "image"})
_RESET_INPUTS = frozenset({"reset"})


@dataclass
class Verdict:
    classification: str
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    matched: str = ""
    auto_clickable: bool = False

    def to_json(self) -> dict[str, Any]:
        d = {"classification": self.classification, "autoClickable": self.auto_clickable}
        if self.matched:
            d["matched"] = self.matched
        if self.flags:
            d["flags"] = sorted(set(self.flags))
        if self.reasons:
            d["reasons"] = self.reasons
        return d


def _labels(el: dict[str, Any]) -> list[str]:
    """Every human-visible or assistive label this element carries.

    Deliberately excludes surrounding context (e.g. the enclosing dialog's
    title): context shapes risk, but it is not this element's own label, and
    conflating the two makes every control inside an "Add ..." dialog look like
    an Add button. Context is applied separately, as a downgrade.
    """
    attrs = el.get("attrs") or {}
    out = [
        el.get("name"), el.get("directText"),
        attrs.get("aria-label"), attrs.get("title"), attrs.get("value"),
        attrs.get("data-testid"), attrs.get("data-test"), attrs.get("data-cy"),
        attrs.get("data-qa"), attrs.get("name"),
        (el.get("link") or {}).get("pathname"),
        (el.get("link") or {}).get("search"),
        el.get("formAction"),
    ]
    return [str(s) for s in out if s]


# Parameter names that carry a command rather than a filter.
_COMMAND_PARAM = re.compile(r"^(action|act|op|operation|do|cmd|command|method|task|mode|"
                            r"event|func|fn|verb|exec|run|type)$", re.I)


def _query_danger(search: str) -> tuple[str, str]:
    """(matched, why) when a query string carries a destructive command."""
    if not search:
        return "", ""
    for pair in search.lstrip("?").split("&"):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        key, value = key.strip(), value.strip()
        hit = _DANGEROUS_RE.search(value)
        if hit and (_COMMAND_PARAM.match(key) or not key):
            return hit.group(0), f"query parameter {key or '(bare)'}={value!r} is a command"
        if hit:
            return hit.group(0), f"query parameter {key}={value!r} contains {hit.group(0)!r}"
        khit = _DANGEROUS_RE.search(key)
        if khit:
            return khit.group(0), f"query parameter name {key!r} is destructive"
    return "", ""


def _url_flags(el: dict[str, Any], origin: str) -> tuple[list[str], list[str]]:
    """Blocking flags implied by an href, plus human reasons."""
    flags: list[str] = []
    reasons: list[str] = []
    link = el.get("link")
    if not link:
        return flags, reasons

    scheme = (link.get("scheme") or "").lower()
    if scheme == "mailto":
        flags.append(FLAG_MAILTO)
        reasons.append("mailto: link would open a mail client")
    elif scheme == "javascript":
        flags.append(FLAG_JAVASCRIPT)
        reasons.append("javascript: URL runs arbitrary code")
    elif scheme == "blob":
        flags.append(FLAG_BLOB)
        reasons.append("blob: URL is generated content, usually a download")
    elif scheme == "data":
        flags.append(FLAG_DATA_URL)
        reasons.append("data: URL is inline content, usually a download")
    elif scheme and scheme not in ALLOWED_URL_SCHEMES:
        flags.append(FLAG_EXTERNAL_SCHEME)
        reasons.append(f"{scheme}: is not a browsable http(s) scheme")

    if link.get("download") or el.get("download"):
        flags.append(FLAG_DOWNLOAD)
        reasons.append("carries a download attribute")
    elif link.get("fileLike"):
        flags.append(FLAG_DOWNLOAD)
        reasons.append("href points at a file that would download")

    if scheme in ALLOWED_URL_SCHEMES and not link.get("sameOrigin"):
        flags.append(FLAG_CROSS_ORIGIN)
        reasons.append(f"navigates off-origin to {link.get('origin') or 'another site'}")
    elif origin and link.get("origin") and link["origin"] != origin \
            and scheme in ALLOWED_URL_SCHEMES:
        flags.append(FLAG_CROSS_ORIGIN)
        reasons.append(f"origin {link['origin']} differs from {origin}")

    matched, why = _query_danger(link.get("search") or "")
    if matched:
        flags.append(FLAG_DANGEROUS_QUERY)
        reasons.append(why)

    target = (link.get("target") or "").lower()
    if target and target not in ("_self", "_top", "_parent"):
        flags.append(FLAG_NEW_TAB)
        reasons.append(f"target={target} opens a new browsing context")
    return flags, reasons


def _form_flags(el: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Blocking flags implied by form participation."""
    flags: list[str] = []
    reasons: list[str] = []
    form = el.get("form") or {}
    method = (el.get("formMethod") or form.get("method") or "").lower()

    input_type = (el.get("inputType") or "").lower()
    effective = (el.get("effectiveButtonType") or "").lower()

    if input_type in _SUBMIT_INPUTS or effective == "submit":
        flags.append(FLAG_FORM_SUBMIT)
        if effective == "submit" and not (el.get("buttonType") or ""):
            reasons.append("<button> with no type inside a form submits it")
        else:
            reasons.append("submits a form")
    if input_type in _RESET_INPUTS or effective == "reset":
        flags.append(FLAG_FORM_RESET)
        reasons.append("resets a form")

    if flags and method == "post":
        flags.append(FLAG_POST)
        reasons.append(f"form method=post to {form.get('action') or '(same URL)'}")
    if el.get("formAction") and method == "post":
        if FLAG_POST not in flags:
            flags.append(FLAG_POST)
            reasons.append("formmethod=post overrides the form to a POST")
    return flags, reasons


def classify(el: dict[str, Any], origin: str = "") -> Verdict:
    """Classify one element record. Never clicks, never touches the browser."""
    return _apply_context(el, _classify(el, origin))


def _classify(el: dict[str, Any], origin: str = "") -> Verdict:
    el_type = (el.get("type") or "").lower()
    role = (el.get("role") or "").lower()
    labels = _labels(el)
    joined = " | ".join(labels)

    flags: list[str] = []
    reasons: list[str] = []

    # ---- state gates: an action we cannot even perform is not "safe" -------
    if el.get("visible") is False:
        flags.append(FLAG_HIDDEN)
        reasons.append("element is not visible")
    if el.get("enabled") is False:
        flags.append(FLAG_DISABLED)
        reasons.append("element is disabled")

    u_flags, u_reasons = _url_flags(el, origin)
    flags += u_flags
    reasons += u_reasons
    f_flags, f_reasons = _form_flags(el)
    flags += f_flags
    reasons += f_reasons

    # ---- 1. session-ending -------------------------------------------------
    auth = _AUTH_RE.search(joined)
    if auth:
        flags.append(FLAG_AUTH)
        flags.append(FLAG_DANGEROUS_VERB)
        return _verdict(DANGEROUS, reasons + [f"ends the session ({auth.group(0)!r})"],
                        flags, auth.group(0))

    # ---- 2. structural writes beat any label ------------------------------
    for flag, why in ((FLAG_DANGEROUS_QUERY, "the URL carries a destructive command"),
                      (FLAG_POST, "issues a POST"),
                      (FLAG_FORM_SUBMIT, "submits a form"),
                      (FLAG_FORM_RESET, "resets a form")):
        if flag in flags:
            return _verdict(DANGEROUS, reasons + [why], flags, flag)

    # ---- 3. confirm-dialog affirmatives ----------------------------------
    own_label = (el.get("name") or el.get("directText") or "").strip()
    if own_label and _CONFIRM_RE.match(own_label):
        flags.append(FLAG_DANGEROUS_VERB)
        return _verdict(DANGEROUS, reasons + [f"{own_label!r} confirms and executes a pending action"],
                        flags, own_label.lower())

    # ---- 4. dangerous vocabulary -----------------------------------------
    danger = _DANGEROUS_RE.search(joined)
    dismiss = bool(own_label and _DISMISS_RE.match(own_label))
    if danger and not dismiss:
        flags.append(FLAG_DANGEROUS_VERB)
        return _verdict(DANGEROUS, reasons + [f"label contains {danger.group(0)!r}"],
                        flags, danger.group(0))

    # ---- 4. URL-level blocks ---------------------------------------------
    for flag in (FLAG_JAVASCRIPT, FLAG_BLOB, FLAG_DATA_URL, FLAG_MAILTO,
                 FLAG_EXTERNAL_SCHEME, FLAG_DOWNLOAD, FLAG_CROSS_ORIGIN):
        if flag in flags:
            return _verdict(DANGEROUS, reasons, flags, flag)

    # ---- 5. inputs are not clicks ----------------------------------------
    if el_type in _INPUT_TYPES:
        return _verdict(CONDITIONAL, reasons + ["data-entry control: filling it is a write"],
                        flags, el_type)
    if el_type in _TOGGLE_TYPES:
        return _verdict(CONDITIONAL, reasons + ["toggling may persist immediately"], flags, el_type)

    # ---- 6. unlabelled / opaque controls ---------------------------------
    named = bool(el.get("name") or el.get("directText"))
    if el.get("iconOnly") and not named:
        flags.append(FLAG_UNLABELLED)
        return _verdict(UNKNOWN, reasons + ["icon-only control with no accessible name: "
                                            "its effect cannot be determined"], flags, "icon-only")
    if not named and el_type not in ("tab", "tabpanel"):
        flags.append(FLAG_UNLABELLED)
        return _verdict(UNKNOWN, reasons + ["no accessible name to reason about"], flags, "unnamed")
    if el_type in _OPAQUE_TYPES:
        # A semantics-free control, but not necessarily unknowable. When the page
        # contains MANY controls of the same shape, they are a list or a tree -
        # and a row in a list navigates, it does not act.
        #
        # Measured on real PhenomeOne (2026-08-27): the research-group tree is
        # dhtmlxTree markup with no role, href, tabindex or test id, so every row
        # was UNKNOWN and an autonomous crawl had nothing to click on any screen.
        #
        # Every veto above still applies and has already run: a dangerous verb in
        # the label, form participation, a POST, cross-origin, hidden, disabled.
        # This only decides the leftover case of a labelled row among peers.
        siblings = int(el.get("leafSiblings") or 0)
        if el_type == "clickable" and siblings >= _LIST_SHAPE_MIN and own_label:
            return _verdict(SAFE_NAVIGATION,
                            reasons + [f"one of {siblings} controls of the same shape: a list or "
                                       f"tree row, which navigates rather than acts"],
                            flags, "list-shape")
        return _verdict(UNKNOWN, reasons + [f"opaque control ({el_type or 'no role'})"],
                        flags, el_type or "no-role")

    # ---- 7. dismissal controls ------------------------------------------
    if own_label and _DISMISS_START_RE.match(own_label) and not dismiss:
        flags.append(FLAG_DANGEROUS_VERB)
        return _verdict(DANGEROUS,
                        reasons + [f"{own_label!r} applies a dismissal verb to something that "
                                   f"is not a dialog or menu"],
                        flags, own_label.lower())
    if dismiss:
        return _verdict(CONDITIONAL, reasons + ["dismisses a dialog/menu"], flags, "dismiss")

    # ---- 8. positive navigation ------------------------------------------
    if el_type == "tab" or role == "tab":
        return _verdict(SAFE_NAVIGATION, reasons + ["tab selection changes the view only"],
                        flags, "tab")
    if el.get("expandable") or el_type == "treeitem" or (el.get("tag") == "summary"):
        return _verdict(SAFE_NAVIGATION, reasons + ["expand/collapse control"], flags, "expander")
    if el_type == "link" or role == "link":
        link = el.get("link") or {}
        if link.get("empty"):
            return _verdict(UNKNOWN, reasons + ["link with no destination: behaviour is scripted"],
                            flags, "empty-href")
        return _verdict(SAFE_NAVIGATION, reasons + ["same-origin link navigation"], flags, "link")
    if el_type == "pagination":
        return _verdict(SAFE_NAVIGATION, reasons + ["pagination control"], flags, "pagination")

    popup = (el.get("hasPopup") or "").lower()
    if popup in ("menu", "listbox", "tree", "grid", "true"):
        return _verdict(SAFE_NAVIGATION, reasons + [f"opens a {popup} without submitting"],
                        flags, "haspopup=" + popup)
    if popup == "dialog":
        return _verdict(CONDITIONAL, reasons + ["opens a dialog, which may contain a form"],
                        flags, "haspopup=dialog")

    nav = _NAV_RE.search(joined)
    if nav and el_type in ("button", "menuitem", "link", "clickable"):
        word = nav.group(0).lower().strip()
        if word in {"next", "previous", "prev", "first", "last", "back"}:
            ctx = el.get("context") or {}
            pagey = (_PAGINATION_RE.search(joined)
                     or "pagin" in str(ctx.get("landmark", "")).lower()
                     or el_type == "pagination")
            if not pagey:
                return _verdict(CONDITIONAL,
                                reasons + [f"{word!r} could be pagination or a wizard step that "
                                           f"commits data - indistinguishable from the label"],
                                flags, word)
        return _verdict(SAFE_NAVIGATION, reasons + [f"read-only vocabulary ({nav.group(0)!r})"],
                        flags, nav.group(0))

    cond = _CONDITIONAL_RE.search(joined)
    if cond:
        return _verdict(CONDITIONAL, reasons + [f"recognised non-navigation action ({cond.group(0)!r})"],
                        flags, cond.group(0))

    if el_type == "menuitem":
        return _verdict(CONDITIONAL, reasons + ["menu item may perform an action"], flags, "menuitem")

    # ---- 9. a named button we do not recognise ---------------------------
    return _verdict(UNKNOWN, reasons + ["named control whose effect is not recognised"],
                    flags, el_type or role or "unclassified")


def _apply_context(el: dict[str, Any], v: Verdict) -> Verdict:
    """A control sitting inside a write-flow surface is never plain navigation."""
    if v.classification != SAFE_NAVIGATION:
        return v
    dialog = ((el.get("context") or {}).get("dialog") or "")
    hit = _DANGEROUS_RE.search(dialog) if dialog else None
    if hit:
        return Verdict(CONDITIONAL,
                       v.reasons + [f"inside the {dialog!r} dialog, which is a write flow"],
                       sorted(set(v.flags + ["in-write-dialog"])), v.matched, False)
    if el.get("inForm") and v.matched not in ("tab", "expander"):
        return Verdict(CONDITIONAL,
                       v.reasons + [f"inside form {(el.get('form') or {}).get('identity', '?')!r}"],
                       sorted(set(v.flags + ["in-form"])), v.matched, False)
    return v


def _verdict(classification: str, reasons: list[str], flags: list[str], matched: str) -> Verdict:
    blocked = sorted(set(flags) & BLOCKING_FLAGS)
    auto = classification == SAFE_NAVIGATION and not blocked
    # Belt and braces: these two classes are never auto-clickable, whatever
    # the rules above concluded.
    if classification in (DANGEROUS, UNKNOWN):
        auto = False
    return Verdict(classification=classification, reasons=reasons,
                   flags=sorted(set(flags)), matched=matched, auto_clickable=auto)


def classify_all(elements: Iterable[dict[str, Any]], origin: str = "") -> list[tuple[dict, Verdict]]:
    return [(el, classify(el, origin)) for el in elements]


def summarise(pairs: Iterable[tuple[dict, Verdict]]) -> dict[str, Any]:
    counts = {c: 0 for c in CLASSES}
    flags: dict[str, int] = {}
    auto = 0
    for _el, v in pairs:
        counts[v.classification] = counts.get(v.classification, 0) + 1
        auto += 1 if v.auto_clickable else 0
        for f in v.flags:
            flags[f] = flags.get(f, 0) + 1
    return {"counts": counts, "autoClickable": auto,
            "flags": dict(sorted(flags.items(), key=lambda kv: -kv[1]))}
