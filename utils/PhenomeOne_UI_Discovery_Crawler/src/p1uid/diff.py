"""UI diff between two UI maps (spec 29).

Answers "what changed in the UI between revision A and revision B":

    + new state / element
    - removed state / element
    ~ locator changed, confidence changed, columns changed

Comparison is by *identity*, not by position: states match on fingerprint,
elements on their element key. So a reordered page produces no diff, while a
renamed button produces a removal plus an addition - which is the truth.
"""
from __future__ import annotations

import html
import json
import time
from pathlib import Path
from typing import Any

from .logging_setup import get

log = get("diff")

ADDED, REMOVED, CHANGED = "added", "removed", "changed"


def load_map(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "states" not in data:
        raise ValueError(f"{path} does not look like a ui-map.json")
    return data


def _by_fingerprint(data: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    for sid, st in (data.get("states") or {}).items():
        out[st.get("fingerprint") or sid] = (sid, st)
    return out


def diff_maps(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    o_states, n_states = _by_fingerprint(old), _by_fingerprint(new)

    states_added = [n_states[f][0] for f in sorted(n_states.keys() - o_states.keys())]
    states_removed = [o_states[f][0] for f in sorted(o_states.keys() - n_states.keys())]

    element_changes: list[dict[str, Any]] = []
    state_changes: list[dict[str, Any]] = []

    for fp in sorted(o_states.keys() & n_states.keys()):
        o_sid, o_st = o_states[fp]
        n_sid, n_st = n_states[fp]
        o_els = o_st.get("elements") or {}
        n_els = n_st.get("elements") or {}

        added = sorted(n_els.keys() - o_els.keys())
        removed = sorted(o_els.keys() - n_els.keys())
        for key in added:
            el = n_els[key]
            element_changes.append({"kind": ADDED, "state": n_sid, "element": el.get("logicalName"),
                                    "type": el.get("type"),
                                    "locator": (el.get("locator") or {}).get("js"),
                                    "confidence": el.get("confidence")})
        for key in removed:
            el = o_els[key]
            element_changes.append({"kind": REMOVED, "state": n_sid, "element": el.get("logicalName"),
                                    "type": el.get("type"),
                                    "locator": (el.get("locator") or {}).get("js")})
        for key in sorted(o_els.keys() & n_els.keys()):
            o_el, n_el = o_els[key], n_els[key]
            o_loc = (o_el.get("locator") or {}).get("js")
            n_loc = (n_el.get("locator") or {}).get("js")
            deltas: list[str] = []
            if o_loc != n_loc:
                deltas.append("locator")
            if o_el.get("confidence") != n_el.get("confidence"):
                deltas.append("confidence")
            o_cols = ((o_el.get("grid") or {}).get("columns") or [])
            n_cols = ((n_el.get("grid") or {}).get("columns") or [])
            if o_cols != n_cols:
                deltas.append("columns")
            if o_el.get("enabled") != n_el.get("enabled"):
                deltas.append("enabled")
            if deltas:
                element_changes.append({
                    "kind": CHANGED, "state": n_sid, "element": n_el.get("logicalName"),
                    "type": n_el.get("type"), "what": deltas,
                    "before": {"locator": o_loc, "confidence": o_el.get("confidence"),
                               "columns": o_cols or None, "enabled": o_el.get("enabled")},
                    "after": {"locator": n_loc, "confidence": n_el.get("confidence"),
                              "columns": n_cols or None, "enabled": n_el.get("enabled")},
                })

        if o_sid != n_sid:
            state_changes.append({"kind": CHANGED, "state": n_sid, "what": ["id"],
                                  "before": o_sid, "after": n_sid})
        o_tabs = ((o_st.get("signals") or {}).get("tabs") or [])
        n_tabs = ((n_st.get("signals") or {}).get("tabs") or [])
        if o_tabs != n_tabs:
            state_changes.append({"kind": CHANGED, "state": n_sid, "what": ["tabs"],
                                  "before": o_tabs, "after": n_tabs})

    o_nav = {(e["from"], (e["action"] or {}).get("name"), e["to"])
             for e in (old.get("navigation") or {}).values()}
    n_nav = {(e["from"], (e["action"] or {}).get("name"), e["to"])
             for e in (new.get("navigation") or {}).values()}
    paths_added = sorted(n_nav - o_nav)
    paths_removed = sorted(o_nav - n_nav)

    result = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "baseline": {"createdAt": old.get("createdAt"), "updatedAt": old.get("updatedAt"),
                     "states": len(old.get("states") or {})},
        "current": {"createdAt": new.get("createdAt"), "updatedAt": new.get("updatedAt"),
                    "states": len(new.get("states") or {})},
        "states": {"added": states_added, "removed": states_removed, "changed": state_changes},
        "elements": element_changes,
        "navigation": {"added": [list(p) for p in paths_added],
                       "removed": [list(p) for p in paths_removed]},
    }
    result["summary"] = {
        "statesAdded": len(states_added),
        "statesRemoved": len(states_removed),
        "statesChanged": len(state_changes),
        "elementsAdded": sum(1 for c in element_changes if c["kind"] == ADDED),
        "elementsRemoved": sum(1 for c in element_changes if c["kind"] == REMOVED),
        "elementsChanged": sum(1 for c in element_changes if c["kind"] == CHANGED),
        "locatorsChanged": sum(1 for c in element_changes
                               if c["kind"] == CHANGED and "locator" in (c.get("what") or [])),
        "pathsAdded": len(paths_added),
        "pathsRemoved": len(paths_removed),
    }
    result["hasChanges"] = any(result["summary"].values())
    return result


def render_lines(d: dict[str, Any]) -> list[str]:
    """Plain-text diff, the `+ - ~` shape from the spec."""
    out: list[str] = []
    for sid in d["states"]["added"]:
        out.append(f"+ state   {sid}")
    for sid in d["states"]["removed"]:
        out.append(f"- state   {sid}")
    for c in d["states"]["changed"]:
        out.append(f"~ state   {c['state']}: {', '.join(c['what'])} "
                   f"{c.get('before')} -> {c.get('after')}")
    for c in d["elements"]:
        sign = {"added": "+", "removed": "-", "changed": "~"}[c["kind"]]
        if c["kind"] == CHANGED:
            bits = []
            for w in c["what"]:
                bits.append(f"{w}: {c['before'].get(w)} -> {c['after'].get(w)}")
            out.append(f"{sign} {c['type'] or 'element':7} {c['state']} / {c['element']}: "
                       + "; ".join(bits))
        else:
            out.append(f"{sign} {c['type'] or 'element':7} {c['state']} / {c['element']}")
    for p in d["navigation"]["added"]:
        out.append(f"+ path    {p[0]} --[{p[1]}]--> {p[2]}")
    for p in d["navigation"]["removed"]:
        out.append(f"- path    {p[0]} --[{p[1]}]--> {p[2]}")
    return out


_CSS = """
body{margin:0;background:#12161c;color:#e6eaf0;font:14px/1.55 -apple-system,Segoe UI,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:32px 20px 64px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;margin:32px 0 10px;text-transform:uppercase;
letter-spacing:.05em;color:#96a0ae;border-bottom:1px solid #2a323d;padding-bottom:6px}
.sub{color:#96a0ae;margin:0 0 22px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}
.card{background:#1a1f27;border:1px solid #2a323d;border-radius:8px;padding:12px 14px}
.card .n{font-size:22px;font-weight:600}.card .l{color:#96a0ae;font-size:11px;text-transform:uppercase}
.add .n{color:#3fb950}.rem .n{color:#f85149}.chg .n{color:#d29922}
pre{background:#0e1217;border:1px solid #2a323d;border-radius:8px;padding:14px;overflow-x:auto;
font:12px/1.6 ui-monospace,Consolas,monospace}
.p{color:#3fb950}.m{color:#f85149}.t{color:#d29922}
code{font:12px ui-monospace,Consolas,monospace;background:#0e1217;border:1px solid #2a323d;
border-radius:4px;padding:1px 5px;color:#a5d6ff}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:6px 9px;border-bottom:1px solid #2a323d;vertical-align:top}
th{color:#96a0ae;font-size:11px;text-transform:uppercase}
.none{color:#96a0ae}
"""


def render_html(d: dict[str, Any]) -> str:
    e = lambda v: html.escape("" if v is None else str(v))          # noqa: E731
    s = d["summary"]
    p = ["<!doctype html><meta charset='utf-8'><title>PhenomeOne UI Diff</title>",
         f"<style>{_CSS}</style><div class=wrap>", "<h1>PhenomeOne UI Diff</h1>",
         f"<p class=sub>Generated {e(d['generatedAt'])}<br>"
         f"baseline: {e(d['baseline']['states'])} states (updated {e(d['baseline']['updatedAt'])})<br>"
         f"current: {e(d['current']['states'])} states (updated {e(d['current']['updatedAt'])})</p>",
         "<div class=cards>"]
    for label, key, cls in (("States +", "statesAdded", "add"), ("States -", "statesRemoved", "rem"),
                            ("States ~", "statesChanged", "chg"),
                            ("Elements +", "elementsAdded", "add"),
                            ("Elements -", "elementsRemoved", "rem"),
                            ("Elements ~", "elementsChanged", "chg"),
                            ("Locators ~", "locatorsChanged", "chg"),
                            ("Paths +", "pathsAdded", "add"), ("Paths -", "pathsRemoved", "rem")):
        p.append(f'<div class="card {cls}"><div class=n>{s[key]}</div><div class=l>{label}</div></div>')
    p.append("</div>")

    if not d["hasChanges"]:
        p.append("<h2>Result</h2><p class=none>No differences: the two maps describe the same UI.</p>")
    else:
        p.append("<h2>Diff</h2><pre>")
        for line in render_lines(d):
            cls = {"+": "p", "-": "m", "~": "t"}.get(line[:1], "")
            p.append(f'<span class="{cls}">{e(line)}</span>')
        p.append("</pre>")

        changed = [c for c in d["elements"] if c["kind"] == CHANGED
                   and "locator" in (c.get("what") or [])]
        if changed:
            p.append("<h2>Locator changes (test-breaking)</h2>"
                     "<table><thead><tr><th>State</th><th>Element</th><th>Before</th>"
                     "<th>After</th></tr></thead><tbody>")
            for c in changed:
                p.append(f"<tr><td>{e(c['state'])}</td><td>{e(c['element'])}</td>"
                         f"<td><code>{e(c['before']['locator'])}</code></td>"
                         f"<td><code>{e(c['after']['locator'])}</code></td></tr>")
            p.append("</tbody></table>")
    p.append("</div>")
    return "\n".join(p)


def write_reports(d: dict[str, Any], json_path: Path, html_path: Path) -> None:
    for path, text in ((json_path, json.dumps(d, indent=1, ensure_ascii=False)),
                       (html_path, render_html(d))):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    log.info("UI diff written -> %s and %s", json_path.name, html_path.name)
