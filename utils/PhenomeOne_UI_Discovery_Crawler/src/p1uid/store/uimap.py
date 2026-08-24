"""Incremental UI-map persistence (spec 17).

Every scan MERGES into the map on disk; nothing starts from zero. Per element we
track firstSeen / lastSeen / timesSeen / environmentsSeen / confidence /
locatorHistory, and a locator that keeps changing is flagged UNSTABLE LOCATOR.

Only structural metadata is stored (spec 18) - no grid rows, no record values.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Iterable

from .. import paths
from ..logging_setup import get
from ..locator.generator import HIGH, LOW, MEDIUM, Locator, suggest_test_id

log = get("store")

SCHEMA_VERSION = 1
UNSTABLE_FLAG = "UNSTABLE LOCATOR"
_MAX_LOCATOR_HISTORY = 4
_UNSTABLE_AFTER_DISTINCT = 3


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def element_key(el: dict[str, Any]) -> str:
    """Identity of a control within a UI state, stable across sessions."""
    attrs = el.get("attrs") or {}
    for a in ("data-testid", "data-test-id", "data-test", "data-cy", "data-qa"):
        if attrs.get(a):
            return f"{el.get('type','?')}#{a}={attrs[a]}"
    ident = (el.get("name") or el.get("directText") or attrs.get("placeholder")
             or attrs.get("name") or attrs.get("href") or attrs.get("id") or "")
    if not ident:
        # Unnamed and attribute-less: fall back to its position among elements
        # of the same kind so two bare <main> landmarks stay distinct.
        ident = f"#{el.get('ordinal', 0)}"
    return f"{el.get('type','?')}:{el.get('role','')}:{ident.strip().lower()[:80]}"


def logical_name(el: dict[str, Any]) -> str:
    name = (el.get("name") or el.get("directText") or "").strip()
    kind = (el.get("type") or "element").replace("-", " ").title()
    return f"{name} {kind}".strip() if name else kind


class UIMapStore:
    def __init__(self, path=None) -> None:
        self.path = path or paths.UI_MAP_FILE
        self.data: dict[str, Any] = self._empty()
        self._slug_to_fp: dict[str, str] = {}

    # ------------------------------------------------------------ lifecycle
    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "application": {"name": "PhenomeOne", "environments": []},
            "createdAt": _now(),
            "updatedAt": _now(),
            "states": {},
            "navigation": {},
        }

    def load(self) -> "UIMapStore":
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("schemaVersion") == SCHEMA_VERSION:
                    self.data = data
                    log.info("Loaded existing UI map: %d states, %d navigation paths",
                             len(self.data.get("states", {})), len(self.data.get("navigation", {})))
                else:
                    log.warning("UI map schema %s is not %s; starting a fresh map (old file kept as .bak)",
                                data.get("schemaVersion"), SCHEMA_VERSION)
                    self.path.replace(self.path.with_suffix(".json.bak"))
            except (OSError, json.JSONDecodeError) as exc:
                log.warning("Could not read UI map (%s); starting a fresh map", exc)
        self._slug_to_fp = {sid: st.get("fingerprint", "")
                            for sid, st in self.data.get("states", {}).items()}
        return self

    def save(self) -> None:
        self.data["updatedAt"] = _now()
        _atomic_write_json(self.path, self.data)
        log.info("UI map saved -> %s (%d states)", paths.rel(self.path), len(self.data["states"]))

    # ------------------------------------------------------------- merging
    def note_environment(self, origin: str) -> None:
        envs = self.data["application"].setdefault("environments", [])
        for e in envs:
            if e.get("origin") == origin:
                e["lastSeen"] = _now()
                e["timesSeen"] = e.get("timesSeen", 1) + 1
                return
        envs.append({"origin": origin, "firstSeen": _now(), "lastSeen": _now(), "timesSeen": 1})

    def state_id_for(self, fp) -> str:
        """Stable, human-readable state id for a fingerprint."""
        for sid, digest in self._slug_to_fp.items():
            if digest == fp.digest:
                return sid
        sid = fp.slug
        n = 2
        while sid in self._slug_to_fp:
            sid = f"{fp.slug}-{n}"
            n += 1
        self._slug_to_fp[sid] = fp.digest
        return sid

    def merge_state(self, fp, structure: dict[str, Any], origin: str) -> tuple[str, bool]:
        sid = self.state_id_for(fp)
        states = self.data["states"]
        is_new = sid not in states
        st = states.setdefault(sid, {
            "id": sid,
            "fingerprint": fp.digest,
            "firstSeen": _now(),
            "timesSeen": 0,
            "elements": {},
            "environmentsSeen": [],
        })
        st["label"] = fp.label
        st["route"] = fp.route
        st["signals"] = fp.signals
        st["lastSeen"] = _now()
        st["timesSeen"] = st.get("timesSeen", 0) + 1
        if origin and origin not in st["environmentsSeen"]:
            st["environmentsSeen"].append(origin)
        return sid, is_new

    def merge_elements(self, sid: str, records: Iterable[tuple[dict[str, Any], Locator, list[Locator]]],
                       state_slug: str = "") -> dict[str, int]:
        """Merge scanned elements into a state. `records` yields
        (element_record, preferred_locator, alternative_locators)."""
        st = self.data["states"][sid]
        bucket = st.setdefault("elements", {})
        added = updated = 0
        for el, pref, alts in records:
            key = element_key(el)
            entry = bucket.get(key)
            if entry is None:
                entry = {
                    "key": key,
                    "logicalName": logical_name(el),
                    "firstSeen": _now(),
                    "timesSeen": 0,
                    "locatorHistory": [],
                }
                bucket[key] = entry
                added += 1
            else:
                updated += 1
            entry["type"] = el.get("type")
            entry["role"] = el.get("role")
            entry["name"] = el.get("name")
            if el.get("nameSource"):
                entry["nameSource"] = el["nameSource"]
            entry["tag"] = el.get("tag")
            entry["visible"] = el.get("visible")
            entry["enabled"] = el.get("enabled")
            if el.get("inDialog"):
                entry["inDialog"] = True
            for opt in ("expandable", "expanded", "checked", "selected", "required"):
                if opt in el:
                    entry[opt] = el[opt]
            test_ids = {k: v for k, v in (el.get("attrs") or {}).items() if k.startswith("data-")}
            if test_ids:
                entry["testIds"] = test_ids
            if el.get("grid"):
                entry["grid"] = el["grid"]           # column names + row count only
            if el.get("options"):
                entry["options"] = el["options"]
            entry["lastSeen"] = _now()
            entry["timesSeen"] = entry.get("timesSeen", 0) + 1
            entry["locator"] = pref.to_json()
            entry["confidence"] = pref.confidence
            entry["alternatives"] = [a.to_json(compact=True) for a in alts[:2]]
            self._record_locator_history(entry, pref)
            if pref.confidence == LOW:
                entry["recommendation"] = (
                    f"Add {suggest_test_id(el, state_slug)!r} as a data-testid on this "
                    f"{el.get('type') or 'element'} to make it deterministically locatable")
            else:
                entry.pop("recommendation", None)
        return {"added": added, "updated": updated}

    @staticmethod
    def _record_locator_history(entry: dict[str, Any], pref: Locator) -> None:
        hist = entry.setdefault("locatorHistory", [])
        for h in hist:
            if h["js"] == pref.js:
                h["lastSeen"] = _now()
                h["timesSeen"] = h.get("timesSeen", 1) + 1
                break
        else:
            hist.append({"js": pref.js, "strategy": pref.strategy,
                         "firstSeen": _now(), "lastSeen": _now(), "timesSeen": 1})
        del hist[:-_MAX_LOCATOR_HISTORY]
        flags = set(entry.get("flags") or [])
        if len(hist) >= _UNSTABLE_AFTER_DISTINCT:
            flags.add(UNSTABLE_FLAG)
        else:
            flags.discard(UNSTABLE_FLAG)
        if flags:
            entry["flags"] = sorted(flags)
        else:
            entry.pop("flags", None)

    # ---------------------------------------------------------- navigation
    def merge_edge(self, from_sid: str, action: dict[str, Any], to_sid: str) -> bool:
        key = f"{from_sid}|{action.get('type','?')}:{(action.get('name') or '')[:60]}|{to_sid}"
        nav = self.data.setdefault("navigation", {})
        edge = nav.get(key)
        is_new = edge is None
        if is_new:
            edge = {"from": from_sid, "action": action, "to": to_sid,
                    "firstSeen": _now(), "timesSeen": 0}
            nav[key] = edge
        edge["action"] = action
        edge["lastSeen"] = _now()
        edge["timesSeen"] = edge.get("timesSeen", 0) + 1
        return is_new

    # ------------------------------------------------------------- queries
    def counts(self) -> dict[str, Any]:
        conf = {HIGH: 0, MEDIUM: 0, LOW: 0}
        types: dict[str, int] = {}
        weak: list[dict[str, Any]] = []
        total = 0
        for sid, st in self.data["states"].items():
            for key, el in st.get("elements", {}).items():
                total += 1
                conf[el.get("confidence", LOW)] = conf.get(el.get("confidence", LOW), 0) + 1
                t = el.get("type") or "unknown"
                types[t] = types.get(t, 0) + 1
                if el.get("confidence") == LOW or UNSTABLE_FLAG in (el.get("flags") or []):
                    weak.append({"state": sid, **el})
        return {
            "states": len(self.data["states"]),
            "elements": total,
            "navigationPaths": len(self.data.get("navigation", {})),
            "confidence": conf,
            "types": dict(sorted(types.items(), key=lambda kv: -kv[1])),
            "weak": weak,
        }


def _atomic_write_json(path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # indent=1: the UI map is a machine artefact first; indent=2 roughly doubles
    # its size for no consumer benefit (spec 28).
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
