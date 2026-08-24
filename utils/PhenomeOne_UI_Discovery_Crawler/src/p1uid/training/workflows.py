"""Workflow recording (spec 29).

A workflow is a *named* sequence of UI steps the user performed, e.g.

    Create Germplasm:
      Research Groups -> Select Group -> Germplasms -> Add -> Fill form -> Save

Recording is a thin layer over training: the trainer already knows which control
was used and which state it led to, so a workflow is that stream, bracketed by a
name and merged into `output/workflows.json`.

Field values are never captured - a "fill" step records that a control was
filled, not with what.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from .. import paths
from ..logging_setup import get

log = get("training.workflow")

SCHEMA_VERSION = 1


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


@dataclass
class Workflow:
    name: str
    started_at: str = field(default_factory=_now)
    steps: list[dict[str, Any]] = field(default_factory=list)
    start_state: str = ""

    def add_step(self, kind: str, label: str, from_state: str, to_state: str,
                 locator: str = "", element_type: str = "") -> None:
        self.steps.append({
            "n": len(self.steps) + 1,
            "kind": kind,                  # navigate | activate | fill | toggle
            "label": label,
            "type": element_type,
            "locator": locator,
            "from": from_state,
            "to": to_state,
        })

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "startState": self.start_state,
            "endState": self.steps[-1]["to"] if self.steps else self.start_state,
            "stepCount": len(self.steps),
            "steps": self.steps,
        }


class WorkflowStore:
    """Named workflows, merged across sessions."""

    def __init__(self, path=None) -> None:
        self.path = path or paths.WORKFLOWS_FILE
        self.data: dict[str, Any] = {"schemaVersion": SCHEMA_VERSION, "workflows": {}}

    def load(self) -> "WorkflowStore":
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("schemaVersion") == SCHEMA_VERSION:
                    self.data = data
            except (OSError, json.JSONDecodeError) as exc:
                log.warning("Could not read workflows (%s); starting fresh", exc)
        return self

    def merge(self, wf: Workflow) -> dict[str, Any]:
        entry = self.data["workflows"].get(wf.name)
        body = wf.to_json()
        if entry is None:
            entry = {**body, "firstRecorded": _now(), "timesRecorded": 0}
            self.data["workflows"][wf.name] = entry
        else:
            # A re-recording replaces the steps (the newest run is the truth)
            # but keeps the history counters.
            previous = entry.get("stepCount", 0)
            entry.update(body)
            if previous != body["stepCount"]:
                entry["stepCountChanged"] = f"{previous} -> {body['stepCount']}"
        entry["lastRecorded"] = _now()
        entry["timesRecorded"] = entry.get("timesRecorded", 0) + 1
        return entry

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)
        log.info("Workflows saved -> %s (%d recorded)", paths.rel(self.path),
                 len(self.data["workflows"]))

    def names(self) -> list[str]:
        return sorted(self.data["workflows"])
