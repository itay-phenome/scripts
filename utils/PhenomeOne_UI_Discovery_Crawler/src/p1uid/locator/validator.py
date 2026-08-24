"""Locator validation against the live page (spec 11).

A generated locator is worthless until it has been resolved by Playwright
itself, so every element's preferred locator is executed here:

    matches / unique / visible / enabled

If an ``exact: true`` role-name locator resolves to nothing (our accessible-name
computation is a close but not perfect match for Playwright's), we retry with
``exact: false`` and, when that is unique, adopt it and say so in the notes.
"""
from __future__ import annotations

from typing import Any

from ..logging_setup import get
from .generator import LOW, MEDIUM, Locator, apply_validation

log = get("locator.validate")

# Validation must be fast and never block on a stale element.
STATE_TIMEOUT_MS = 1000


def build(frame: Any, loc: Locator, exact_override: bool | None = None) -> Any:
    """Turn a Locator spec into a real Playwright Locator on `frame`."""
    a = loc.args
    exact = a.get("exact", True) if exact_override is None else exact_override
    s = loc.strategy
    if s == "testid" and "css" not in a:
        return frame.get_by_test_id(a["value"])
    if s == "role":
        if a.get("name"):
            return frame.get_by_role(a["role"], name=a["name"], exact=exact)
        return frame.get_by_role(a["role"])
    if s == "label":
        return frame.get_by_label(a["label"], exact=exact)
    if s == "placeholder":
        return frame.get_by_placeholder(a["placeholder"], exact=exact)
    if s == "title":
        return frame.get_by_title(a["title"], exact=exact)
    if s == "text":
        return frame.get_by_text(a["text"], exact=exact)
    if s == "structural":
        if a.get("role"):
            return frame.get_by_role(a["role"]).nth(a.get("nth", 0))
        return frame.locator(a["css"]).nth(a.get("nth", 0))
    return frame.locator(a.get("css") or a.get("value") or "html")


async def validate(frame: Any, loc: Locator) -> Locator:
    """Resolve `loc` on `frame` and fold the result into the Locator."""
    matches: int | None = None
    visible: bool | None = None
    enabled: bool | None = None
    try:
        handle = build(frame, loc)
        matches = await handle.count()

        # Accessible-name near-miss recovery for role locators.
        if matches == 0 and loc.strategy == "role" and loc.args.get("exact") is True:
            loose = build(frame, loc, exact_override=False)
            loose_n = await loose.count()
            if loose_n == 1:
                loc.args["exact"] = False
                loc.js = loc.js.replace("exact: true", "exact: false")
                loc.python = loc.python.replace("exact=True", "exact=False")
                loc.notes.append("exact name match failed; substring match is unique")
                handle, matches = loose, loose_n

        if matches and matches >= 1:
            first = handle.first
            # Explicit short timeouts: an element that vanished between the
            # collect and the validation must not stall the scan for 30 s.
            try:
                visible = await first.is_visible(timeout=STATE_TIMEOUT_MS)
            except Exception:
                visible = None
            try:
                enabled = await first.is_enabled(timeout=STATE_TIMEOUT_MS)
            except Exception:
                enabled = None
    except Exception as exc:
        loc.notes.append(f"validation error: {type(exc).__name__}")
        log.debug("Locator validation failed for %s: %s", loc.js, exc)
    return apply_validation(loc, matches, visible, enabled)


DEFERRED_NOTE = ("not validated: the element is hidden at scan time, and Playwright role "
                 "locators deliberately do not match hidden elements")


async def validate_element(frame: Any, el: dict[str, Any], cands: list[Locator]) -> Locator:
    """Validate an element's preferred locator, promoting an alternative if the
    preferred one turns out to be ambiguous.

    Verified against Playwright 1.61: of all strategies we generate, only
    ``getByRole`` skips CSS-hidden elements. So for a hidden element a role
    locator cannot be confirmed *now* - which does not make it a bad locator,
    it is exactly the right one once the dialog/menu is open. Such locators are
    marked ``deferred-hidden`` and capped at MEDIUM instead of being called LOW.
    """
    pref = cands[0]
    visible = bool(el.get("visible"))

    if pref.strategy == "role" and not visible:
        pref.visible = False
        pref.enabled = el.get("enabled")
        pref.confidence = MEDIUM if pref.est_matches == 1 else LOW
        pref.validation = "deferred-hidden"
        pref.notes.append(DEFERRED_NOTE)
        return pref

    await validate(frame, pref)
    if pref.matches == 1:
        return pref

    for alt in cands[1:3]:
        if alt.strategy == "role" and not visible:
            continue
        await validate(frame, alt)
        if alt.matches == 1:
            alt.notes.append(f"promoted: the {pref.strategy} locator matched {pref.matches}")
            return alt
    return pref
