"""Page scanning: DOM+ARIA harvest -> locators -> validation -> merge.

One scan is: 1 evaluate per frame (spec 28 - no per-element round trips for
discovery), then one Playwright resolve per element for locator validation
(spec 11), then an in-memory merge into the UI map.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..logging_setup import get
from ..locator import validator
from ..locator.generator import HIGH, LOW, MEDIUM, Locator, candidates
from ..state.fingerprint import fingerprint
from ..browser.injected import CORE_JS

log = get("discovery")

INSTALL_JS = "() => {\n" + CORE_JS + "\n}"
COLLECT_JS = "(o) => window.__p1uidCore.collect(o)"
HAS_CORE_JS = "() => !!(window.__p1uidCore && window.__p1uidCore.version === 1)"

MAX_FRAMES = 6


@dataclass
class ScanResult:
    state_id: str = ""
    is_new_state: bool = False
    label: str = ""
    route: str = ""
    fingerprint: str = ""
    elements: int = 0
    added: int = 0
    frames: int = 1
    truncated: bool = False
    not_validated: int = 0
    confidence: dict[str, int] = field(default_factory=lambda: {HIGH: 0, MEDIUM: 0, LOW: 0})
    timings_ms: dict[str, int] = field(default_factory=dict)
    structure: dict[str, Any] = field(default_factory=dict)
    stability: dict[str, Any] | None = None
    # (frame, element_record, preferred_locator) - only when keep_rows=True.
    rows: list[tuple[Any, dict[str, Any], Any]] = field(default_factory=list)


def _reuse_validation(store, sid: str, row: dict[str, Any]) -> bool:
    """Copy a still-valid validation result instead of re-resolving it."""
    from ..store.uimap import element_key
    state = store.data.get("states", {}).get(sid) or {}
    entry = (state.get("elements") or {}).get(element_key(row["el"]))
    prev = (entry or {}).get("locator") or {}
    pref = row["pref"]
    if not prev or prev.get("js") != pref.js or prev.get("validation") not in ("live", "deferred-hidden"):
        return False
    pref.matches = prev.get("matches")
    pref.unique = prev.get("unique")
    pref.visible = row["el"].get("visible")
    pref.enabled = row["el"].get("enabled")
    pref.confidence = prev.get("confidence", pref.confidence)
    pref.validation = prev.get("validation", "")
    return True


async def ensure_core(frame: Any) -> bool:
    """Make sure window.__p1uidCore exists in this frame."""
    try:
        if await frame.evaluate(HAS_CORE_JS):
            return True
        await frame.evaluate(INSTALL_JS)
        return bool(await frame.evaluate(HAS_CORE_JS))
    except Exception as exc:
        log.debug("Could not install core in frame %s: %s", getattr(frame, "url", "?"), exc)
        return False


def _scannable_frames(page: Any) -> list[Any]:
    frames = [page.main_frame]
    for f in page.frames:
        if f is page.main_frame or len(frames) >= MAX_FRAMES:
            continue
        url = (f.url or "")
        if url.startswith("http") and not f.is_detached():
            frames.append(f)
    return frames


async def collect_frame(frame: Any, max_elements: int = 1500) -> dict[str, Any] | None:
    if not await ensure_core(frame):
        return None
    try:
        return await frame.evaluate(COLLECT_JS, {"maxElements": max_elements,
                                                 "frame": "" if frame.parent_frame is None else frame.url})
    except Exception as exc:
        log.debug("collect failed on %s: %s", frame.url, exc)
        return None


async def scan_page(page: Any, store, origin: str = "", validate: bool = True,
                    validate_limit: int = 500, max_elements: int = 1500,
                    validate_new_only: bool = False,
                    stabilise: bool = False,
                    keep_rows: bool = False) -> ScanResult | None:
    """Full scan of the page's current UI state, merged into `store`.

    `validate_new_only` reuses the previously validated result for an element
    whose locator has not changed since the last scan of this state. Training
    uses it so revisiting a known screen costs a collect + merge instead of a
    Playwright round trip per element; explicit "Scan Current Page" does not,
    so a manual scan is always authoritative.
    """
    t_start = time.perf_counter()
    url = (page.url or "")
    if not url or url.startswith("about:") or url.startswith("chrome-error:"):
        # A blank or error page is not a UI state; recording it would pollute
        # the map with a state that no test could ever navigate to.
        log.info("Nothing to scan: the page is at %s", url or "(no url)")
        return None
    if stabilise:
        # Local import: stability imports this module for ensure_core().
        from . import stability
        st = await stability.wait_stable(page)
        res_stability = {"stable": st.stable, "reason": st.reason, "ms": st.ms, "changes": st.changes}
        if not st.stable:
            log.warning("Page had not settled before scanning (%s after %d ms, %d changes)",
                        st.reason, st.ms, st.changes)
    else:
        res_stability = None
    # The settle wait is reported separately: folding it into `collect` would
    # make the scan look 250 ms slower than it is.
    t0 = time.perf_counter()
    frames = _scannable_frames(page)
    collected: list[tuple[Any, dict[str, Any]]] = []
    for f in frames:
        data = await collect_frame(f, max_elements)
        if data:
            collected.append((f, data))
    if not collected:
        log.warning("Scan found no analysable frame on %s", page.url)
        return None
    t_collect = time.perf_counter()

    main_data = collected[0][1]
    structure = main_data["structure"]
    fp = fingerprint(structure)
    sid, is_new = store.merge_state(fp, structure, origin)
    if origin:
        store.note_environment(origin)

    res = ScanResult(state_id=sid, is_new_state=is_new, label=fp.label, route=fp.route,
                     fingerprint=fp.digest, frames=len(collected), structure=structure)
    if res_stability is not None:
        res.stability = res_stability

    # --- locator generation ------------------------------------------------
    per_frame: list[tuple[Any, list[dict[str, Any]]]] = []
    total_elements = 0
    for frame, data in collected:
        counts = data.get("counts") or {}
        res.truncated = res.truncated or bool(data.get("stats", {}).get("truncated"))
        rows: list[dict[str, Any]] = []
        role_index: dict[str, int] = {}
        kind_index: dict[str, int] = {}
        for el in data.get("elements", []):
            role = el.get("role") or el.get("tag") or "*"
            idx = role_index.get(role, 0)
            role_index[role] = idx + 1
            # Ordinal within (type, role): disambiguates unnamed elements such as
            # two <main> landmarks, which would otherwise share an element key.
            kind = f"{el.get('type')}:{role}"
            el["ordinal"] = kind_index.get(kind, 0)
            kind_index[kind] = el["ordinal"] + 1
            cands = candidates(el, counts, index=idx)
            rows.append({"el": el, "cands": cands, "pref": cands[0]})
        total_elements += len(rows)
        per_frame.append((frame, rows))
    t_generate = time.perf_counter()

    # --- validation --------------------------------------------------------
    if validate:
        budget = validate_limit
        for frame, rows in per_frame:
            for row in rows:
                reused = _reuse_validation(store, sid, row) if validate_new_only else False
                if reused:
                    continue
                if budget <= 0:
                    res.not_validated += 1
                    continue
                row["pref"] = await validator.validate_element(frame, row["el"], row["cands"])
                budget -= 1
        if res.not_validated:
            log.warning("Validation cap of %d reached: %d element(s) left unvalidated in this scan",
                        validate_limit, res.not_validated)
    t_validate = time.perf_counter()

    # --- merge -------------------------------------------------------------
    added = 0
    for _frame, rows in per_frame:
        merge_rows = [(r["el"], r["pref"], [c for c in r["cands"] if c is not r["pref"]])
                      for r in rows]
        stats = store.merge_elements(sid, merge_rows, state_slug=fp.slug)
        added += stats["added"]
        for r in rows:
            res.confidence[r["pref"].confidence] = res.confidence.get(r["pref"].confidence, 0) + 1
    t_merge = time.perf_counter()

    if keep_rows:
        res.rows = [(frame, r["el"], r["pref"]) for frame, rows in per_frame for r in rows]
    res.elements = total_elements
    res.added = added
    res.timings_ms = {
        "stabilise": int((t0 - t_start) * 1000),
        "collect": int((t_collect - t0) * 1000),
        "generate": int((t_generate - t_collect) * 1000),
        "validate": int((t_validate - t_generate) * 1000),
        "merge": int((t_merge - t_validate) * 1000),
        "total": int((t_merge - t0) * 1000),
        "totalWithWait": int((t_merge - t_start) * 1000),
    }
    log.info("Scan: state=%s%s elements=%d (new %d) frames=%d  [collect %dms, locators %dms, "
             "validate %dms, merge %dms]", sid, " NEW" if is_new else "", total_elements, added,
             len(collected), res.timings_ms["collect"], res.timings_ms["generate"],
             res.timings_ms["validate"], res.timings_ms["merge"])
    return res
