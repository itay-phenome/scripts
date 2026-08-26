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

def shortest_path(store: Any, to_state: str, from_state: str | None = None) -> list[dict[str, Any]] | None:
    """Learned click path that reaches `to_state`, or None if unreachable.

    Breadth-first over the navigation the tool actually observed, so every step
    carries the locator that was validated when the edge was discovered. Used by
    the functional runner: tests navigate by state id and the graph supplies the
    clicks, which is why a test never hard-codes a route.
    """
    edges = list((store.data.get("navigation") or {}).values())
    if to_state == from_state:
        return []
    adj: dict[str, list[dict[str, Any]]] = {}
    for e in edges:
        adj.setdefault(e["from"], []).append(e)

    starts = [from_state] if from_state else _roots(
        [{"id": sid, "route": st.get("route")} for sid, st in
         (store.data.get("states") or {}).items()],
        [{"from": e["from"], "to": e["to"], "action": e.get("action")} for e in edges])
    seen = set(starts)
    queue: list[tuple[str, list[dict[str, Any]]]] = [(s, []) for s in starts]
    while queue:
        node, path = queue.pop(0)
        if node == to_state:
            return path
        for e in sorted(adj.get(node, []), key=lambda x: str((x.get("action") or {}).get("name"))):
            dest = e["to"]
            if dest in seen:
                continue
            seen.add(dest)
            act = e.get("action") or {}
            queue.append((dest, path + [{
                "from": node, "to": dest,
                "action": act.get("name") or act.get("type") or "?",
                "type": act.get("type"),
                "locator": act.get("locator"),
                "locatorSpec": act.get("locatorSpec"),
            }]))
    return None
