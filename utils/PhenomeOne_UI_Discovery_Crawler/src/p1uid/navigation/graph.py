"""Navigation graph construction (spec 15)."""
from __future__ import annotations

from typing import Any

from ..logging_setup import get

log = get("navigation")


def build(store: Any) -> dict[str, Any]:
    states: dict[str, Any] = store.data.get("states", {})
    nav: dict[str, Any] = store.data.get("navigation", {})

    nodes = [{
        "id": sid,
        "label": st.get("label") or sid,
        "route": st.get("route"),
        "fingerprint": st.get("fingerprint"),
        "elements": len(st.get("elements", {})),
        "timesSeen": st.get("timesSeen", 0),
        "hasDialog": bool((st.get("signals") or {}).get("dialogs")),
        "activeTab": (st.get("signals") or {}).get("activeTab") or "",
    } for sid, st in sorted(states.items())]

    edges = [{
        "from": e["from"],
        "action": e["action"],
        "to": e["to"],
        "timesSeen": e.get("timesSeen", 1),
        "firstSeen": e.get("firstSeen"),
        "lastSeen": e.get("lastSeen"),
    } for e in nav.values()]

    return {
        "nodes": nodes,
        "edges": edges,
        "roots": _roots(nodes, edges),
        "tree": tree_lines(nodes, edges),
    }


def _roots(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    incoming = {e["to"] for e in edges}
    roots = [n["id"] for n in nodes if n["id"] not in incoming]
    if not roots and nodes:
        # Fully cyclic graph: start from the shallowest, shortest route.
        roots = [min(nodes, key=lambda n: (str(n["route"]).count("/"),
                                           len(str(n["route"])), n["id"]))["id"]]
    return roots


def tree_lines(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    """Readable spanning tree of the learned navigation (spec 15)."""
    by_id = {n["id"]: n for n in nodes}
    children: dict[str, list[tuple[str, str]]] = {}
    for e in edges:
        act = e["action"]
        label = (act.get("name") or act.get("type") or "action")
        children.setdefault(e["from"], []).append((e["to"], label))
    for v in children.values():
        v.sort(key=lambda t: t[1].lower())

    lines: list[str] = []
    shown: set[str] = set()

    def label_of(sid: str) -> str:
        n = by_id.get(sid)
        return f"{sid}  ({n['elements']} elements)" if n else sid

    def walk(sid: str, prefix: str, depth: int) -> None:
        for i, (child, action) in enumerate(children.get(sid, [])):
            last = i == len(children[sid]) - 1
            lines.append(f"{prefix}{'└── ' if last else '├── '}[{action}] -> {label_of(child)}")
            if child in shown or depth >= 12:
                if child in shown:
                    lines[-1] += "   (shown above)"
                continue
            shown.add(child)
            walk(child, prefix + ("    " if last else "│   "), depth + 1)

    for root in _roots(nodes, edges):
        shown.add(root)
        lines.append(label_of(root))
        walk(root, "", 0)
    for n in nodes:                       # anything unreachable from a root
        if n["id"] not in shown:
            shown.add(n["id"])
            lines.append(label_of(n["id"]))
            walk(n["id"], "", 0)
    return lines
