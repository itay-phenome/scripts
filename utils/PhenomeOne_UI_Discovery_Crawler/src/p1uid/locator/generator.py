"""Locator generation (spec 10) and quality scoring (spec 12).

Strategy order, best first:
  1. explicit test id            -> getByTestId / [data-cy=...]
  2. unique ARIA role + name     -> getByRole
  3. label                       -> getByLabel
  4. stable semantic attribute   -> getByPlaceholder / getByTitle / [name=...] / #id
  5. unique meaningful text      -> getByText
  6. the control's own shape + text -> tag.designSystemClass:text-is("...")
     or simple stable CSS          -> tag[attr=...]
  7. structural (role + nth)     -> LAST RESORT, always LOW

Deliberately never produced: XPath, nth-child chains, absolute DOM paths, or
selectors built from framework-generated class names / volatile ids. A class is
used at tier 6 only when the injected core judged it part of the framework's own
vocabulary - not generated, not a state modifier - and only when shape+text
resolves to exactly one element.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any

# Playwright's getByTestId default attribute. Other test-id attributes are
# still used, but through an attribute CSS selector.
DEFAULT_TESTID_ATTR = "data-testid"
TESTID_ATTRS = ["data-testid", "data-test-id", "data-test", "data-cy", "data-qa",
                "data-automation-id", "data-e2e"]

HIGH, MEDIUM, LOW = "HIGH", "MEDIUM", "LOW"

# Tier -> best achievable confidence when the locator resolves to exactly one node.
_TIER_CEILING = {1: HIGH, 2: HIGH, 3: HIGH, 4: MEDIUM, 5: MEDIUM, 6: MEDIUM, 7: LOW}

def _q_js(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _q_py(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _css_value(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class Locator:
    """One locator candidate, expressed for every consumer we care about."""

    strategy: str                       # testid|role|label|placeholder|title|text|css|structural
    tier: int
    js: str                             # Playwright JS/TS chain, e.g. getByRole('tab', {...})
    python: str                         # Playwright Python chain
    args: dict[str, Any] = field(default_factory=dict)
    est_matches: int = 1                # uniqueness estimated in-browser
    matches: int | None = None          # authoritative count from validation
    unique: bool | None = None
    visible: bool | None = None
    enabled: bool | None = None
    confidence: str = MEDIUM
    validation: str = ""      # live | deferred-hidden | ""
    notes: list[str] = field(default_factory=list)

    def to_json(self, compact: bool = False) -> dict[str, Any]:
        """`compact` keeps only what a consumer needs to pick an alternative."""
        if compact:
            d = {"strategy": self.strategy, "js": self.js, "confidence": self.confidence,
                 "matches": self.matches, "estMatches": self.est_matches}
            return {k: v for k, v in d.items() if v is not None}
        d = asdict(self)
        if not self.notes:
            d.pop("notes")
        return {k: v for k, v in d.items() if v is not None and v != ""}


def _tier_confidence(tier: int, est: int) -> str:
    if est != 1:
        return LOW
    return _TIER_CEILING.get(tier, LOW)


def candidates(el: dict[str, Any], counts: dict[str, dict[str, int]],
               index: int = 0) -> list[Locator]:
    """Build the ordered candidate list for one element record."""
    out: list[Locator] = []
    attrs: dict[str, str] = el.get("attrs") or {}
    role = el.get("role") or ""
    name = el.get("name") or ""
    tag = el.get("tag") or "*"
    text = el.get("directText") or ""

    c_testid = counts.get("testid", {})
    c_rolename = counts.get("roleName", {})
    c_label = counts.get("label", {})
    c_ph = counts.get("placeholder", {})
    c_title = counts.get("title", {})
    c_id = counts.get("id", {})
    c_nameattr = counts.get("nameAttr", {})
    c_text = counts.get("text", {})
    c_role = counts.get("role", {})
    c_classtext = counts.get("classText", {})

    # --- 1. test ids -------------------------------------------------------
    for attr in TESTID_ATTRS:
        val = attrs.get(attr)
        if not val:
            continue
        est = c_testid.get(f"{attr} {val}", 1)
        if attr == DEFAULT_TESTID_ATTR:
            out.append(Locator("testid", 1,
                               f"getByTestId({_q_js(val)})",
                               f"get_by_test_id({_q_py(val)})",
                               {"attribute": attr, "value": val}, est,
                               confidence=_tier_confidence(1, est)))
        else:
            sel = f"[{attr}={_css_value(val)}]"
            out.append(Locator("testid", 1,
                               f"locator({_q_js(sel)})",
                               f"locator({_q_py(sel)})",
                               {"attribute": attr, "value": val, "css": sel}, est,
                               confidence=_tier_confidence(1, est),
                               notes=[f"non-default test-id attribute ({attr}); "
                                      f"configure testIdAttribute to use getByTestId"]))

    # --- 2. role + accessible name ----------------------------------------
    if role and name:
        est = c_rolename.get(f"{role} {name.lower()}", 1)
        out.append(Locator("role", 2,
                           f"getByRole({_q_js(role)}, {{ name: {_q_js(name)}, exact: true }})",
                           f"get_by_role({_q_py(role)}, name={_q_py(name)}, exact=True)",
                           {"role": role, "name": name, "exact": True}, est,
                           confidence=_tier_confidence(2, est)))

    # --- 3. label (form controls) -----------------------------------------
    if name and el.get("nameSource") == "label":
        est = c_label.get(name.lower(), 1)
        out.append(Locator("label", 3,
                           f"getByLabel({_q_js(name)}, {{ exact: true }})",
                           f"get_by_label({_q_py(name)}, exact=True)",
                           {"label": name, "exact": True}, est,
                           confidence=_tier_confidence(3, est)))

    # --- 4. stable semantic attributes ------------------------------------
    ph = attrs.get("placeholder")
    if ph:
        est = c_ph.get(ph, 1)
        out.append(Locator("placeholder", 4,
                           f"getByPlaceholder({_q_js(ph)}, {{ exact: true }})",
                           f"get_by_placeholder({_q_py(ph)}, exact=True)",
                           {"placeholder": ph, "exact": True}, est,
                           confidence=_tier_confidence(4, est)))
    ttl = attrs.get("title")
    if ttl:
        est = c_title.get(ttl, 1)
        out.append(Locator("title", 4,
                           f"getByTitle({_q_js(ttl)}, {{ exact: true }})",
                           f"get_by_title({_q_py(ttl)}, exact=True)",
                           {"title": ttl, "exact": True}, est,
                           confidence=_tier_confidence(4, est)))
    el_id = attrs.get("id")
    if el_id and not attrs.get("idVolatile"):
        est = c_id.get(el_id, 1)
        sel = f"#{el_id}" if re.fullmatch(r"[A-Za-z][\w-]*", el_id) else f"[id={_css_value(el_id)}]"
        out.append(Locator("css", 4,
                           f"locator({_q_js(sel)})", f"locator({_q_py(sel)})",
                           {"css": sel, "via": "id"}, est,
                           confidence=_tier_confidence(4, est)))
    nm_attr = attrs.get("name")
    if nm_attr:
        est = c_nameattr.get(nm_attr, 1)
        sel = f"{tag}[name={_css_value(nm_attr)}]"
        out.append(Locator("css", 4,
                           f"locator({_q_js(sel)})", f"locator({_q_py(sel)})",
                           {"css": sel, "via": "name-attribute"}, est,
                           confidence=_tier_confidence(4, est)))

    # --- 5. unique meaningful text ----------------------------------------
    if text and 1 <= len(text) <= 60 and el.get("type") in {
            "button", "link", "tab", "menuitem", "treeitem", "option", "clickable"}:
        est = c_text.get(text.lower(), 1)
        out.append(Locator("text", 5,
                           f"getByText({_q_js(text)}, {{ exact: true }})",
                           f"get_by_text({_q_py(text)}, exact=True)",
                           {"text": text, "exact": True}, est,
                           confidence=_tier_confidence(5, est)))

    # --- 6. the control's own shape, plus its text ------------------------
    #
    # For a design system that sets no role, no href and no test id, text is the
    # only handle - and a label is not always unique. Measured on real PhenomeOne
    # (2026-08-28): 308 of one crawl's refusals were `locator-not-unique`, and
    # they were navigable controls: the `Germplasms` tab and the `Germplasms 10`
    # summary card share a label, so `getByText` matched two elements and the
    # crawler refused both, leaving the tabs unreachable.
    #
    # `div.dhxtabbar_tab_text:text-is("Germplasms")` separates them. The class
    # comes from `classSelector` in the injected core, which keeps only the
    # framework's own vocabulary - never a generated name, never a state
    # modifier like `...actv`, which would stop matching the moment the user
    # selects another tab. Emitted only when shape+text is unique on the page, so
    # it can never make ambiguity worse.
    class_sel = el.get("classSel") or ""
    if class_sel and text and 1 <= len(text) <= 60:
        est = c_classtext.get(f"{class_sel} {text.lower()}", 1)
        if est == 1:
            sel = f'{class_sel}:text-is({_css_value(text)})'
            out.append(Locator("css", 6,
                               f"locator({_q_js(sel)})", f"locator({_q_py(sel)})",
                               {"css": sel, "via": "class+text", "text": text}, est,
                               confidence=_tier_confidence(6, est),
                               notes=["scoped by the design-system class because the "
                                      "text alone is not unique on this page"]))

    # --- 6b. simple stable CSS (role attribute) ---------------------------
    if attrs.get("role") and not name:
        sel = f"[role={_css_value(attrs['role'])}]"
        est = c_role.get(role, 1)
        out.append(Locator("css", 6,
                           f"locator({_q_js(sel)})", f"locator({_q_py(sel)})",
                           {"css": sel, "via": "role-attribute"}, est,
                           confidence=_tier_confidence(6, est)))

    # --- 7. structural last resort ----------------------------------------
    if not out:
        if role:
            out.append(Locator("structural", 7,
                               f"getByRole({_q_js(role)}).nth({index})",
                               f"get_by_role({_q_py(role)}).nth({index})",
                               {"role": role, "nth": index}, c_role.get(role, 1),
                               confidence=LOW,
                               notes=["positional locator - will break when the page changes"]))
        else:
            out.append(Locator("structural", 7,
                               f"locator({_q_js(tag)}).nth({index})",
                               f"locator({_q_py(tag)}).nth({index})",
                               {"css": tag, "nth": index}, 0, confidence=LOW,
                               notes=["no usable attribute, role or name on this element"]))

    out.sort(key=lambda l: (0 if l.est_matches == 1 else 1, l.tier))
    return out


def suggest_test_id(el: dict[str, Any], state_slug: str = "") -> str:
    """Suggested data-testid for a weakly-locatable element (spec 12)."""
    base = el.get("name") or el.get("directText") or el.get("attrs", {}).get("placeholder") or el.get("type") or "element"
    slug = re.sub(r"[^a-z0-9]+", "-", str(base).lower()).strip("-")[:40] or "element"
    kind = (el.get("type") or "element").lower()
    prefix = re.sub(r"[^a-z0-9]+", "-", state_slug.lower()).strip("-")
    parts = [p for p in (prefix, slug, kind if kind not in slug else "") if p]
    return "-".join(parts)[:64]


def apply_validation(loc: Locator, matches: int | None, visible: bool | None,
                     enabled: bool | None) -> Locator:
    """Fold authoritative validation results into a candidate (spec 11-12)."""
    loc.visible = visible
    loc.enabled = enabled
    if matches is None:
        loc.validation = loc.validation or "failed"
        loc.notes.append("not validated")
        if loc.confidence == HIGH:
            loc.confidence = MEDIUM
        return loc
    loc.matches = matches
    loc.unique = matches == 1
    loc.validation = "live"
    if matches == 1:
        ceiling = _TIER_CEILING.get(loc.tier, LOW)
        loc.confidence = ceiling
        if loc.est_matches != 1:
            loc.notes.append("in-page estimate disagreed with validation")
    elif matches == 0:
        loc.confidence = LOW
        loc.notes.append("locator matched nothing during validation")
    else:
        loc.confidence = LOW
        loc.notes.append(f"locator is ambiguous ({matches} matches)")
    return loc
