"""Functional test results.

Deliberately separate from the discovery-health results: a weak locator is a
code-quality signal, a failed functional test is a broken application. They must
never be mixed in one report or one exit code.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..logging_setup import get

log = get("functional.results")

PASSED, FAILED, SKIPPED, ERROR = "PASSED", "FAILED", "SKIPPED", "ERROR"


@dataclass
class StepResult:
    index: int
    action: str
    description: str
    status: str = PASSED
    ms: int = 0
    target: str = ""
    locator: str = ""
    expected: Any = None
    actual: Any = None
    error: str = ""
    destructive: bool = False
    state_before: str = ""
    state_after: str = ""

    def to_json(self) -> dict[str, Any]:
        d = {"n": self.index, "action": self.action, "step": self.description,
             "status": self.status, "ms": self.ms}
        for key, value in (("target", self.target), ("locator", self.locator),
                           ("error", self.error), ("stateBefore", self.state_before),
                           ("stateAfter", self.state_after)):
            if value:
                d[key] = value
        if self.expected is not None:
            d["expected"] = self.expected
        if self.actual is not None:
            d["actual"] = self.actual
        if self.destructive:
            d["destructive"] = True
        return d


@dataclass
class TestResult:
    name: str
    level: str = "smoke"
    status: str = PASSED
    ms: int = 0
    steps: list[StepResult] = field(default_factory=list)
    cleanup_steps: list[StepResult] = field(default_factory=list)
    failure: str = ""
    failed_step: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    created: list[str] = field(default_factory=list)
    leftovers: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == PASSED

    def to_json(self) -> dict[str, Any]:
        d = {"name": self.name, "level": self.level, "status": self.status, "ms": self.ms,
             "steps": [s.to_json() for s in self.steps]}
        if self.cleanup_steps:
            d["cleanup"] = [s.to_json() for s in self.cleanup_steps]
        if self.failure:
            d["failure"] = self.failure
        if self.failed_step is not None:
            d["failedStep"] = self.failed_step
        if self.evidence:
            d["evidence"] = self.evidence
        if self.created:
            d["createdRecords"] = self.created
        if self.leftovers:
            d["leftoverRecords"] = self.leftovers
        return d


@dataclass
class SuiteResult:
    suite: str
    run_id: str
    started_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    ms: int = 0
    tests: list[TestResult] = field(default_factory=list)
    environment: str = ""
    aborted: str = ""

    @property
    def passed(self) -> int:
        return sum(1 for t in self.tests if t.status == PASSED)

    @property
    def failed(self) -> int:
        return sum(1 for t in self.tests if t.status in (FAILED, ERROR))

    @property
    def skipped(self) -> int:
        return sum(1 for t in self.tests if t.status == SKIPPED)

    @property
    def ok(self) -> bool:
        return self.failed == 0 and not self.aborted

    @property
    def leftovers(self) -> list[str]:
        return [r for t in self.tests for r in t.leftovers]

    def to_json(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "runId": self.run_id,
            "startedAt": self.started_at,
            "durationMs": self.ms,
            "environment": self.environment,
            "totals": {"tests": len(self.tests), "passed": self.passed,
                       "failed": self.failed, "skipped": self.skipped},
            "leftoverRecords": self.leftovers,
            "abortedBecause": self.aborted,
            "tests": [t.to_json() for t in self.tests],
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_json(), indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        log.info("Functional results -> %s (%d passed, %d failed)", path.name,
                 self.passed, self.failed)

    def summary_line(self) -> str:
        return (f"{self.passed} passed, {self.failed} failed, {self.skipped} skipped "
                f"in {self.ms / 1000:.1f}s"
                + (f" | LEFTOVERS: {len(self.leftovers)}" if self.leftovers else ""))
