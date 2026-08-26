"""Deterministic test data and the cleanup ledger.

Every run gets a unique RUN_ID. Records a test creates are named from it, so
* two runs never collide, even in parallel,
* anything left behind is identifiable as ours and traceable to a run, and
* a human can find and remove residue by searching for the RUN_ID.

Cleanup runs even when a test fails. If cleanup itself fails, the record stays
in the ledger and is reported as a leftover rather than silently forgotten.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..logging_setup import get

log = get("functional.data")

# QA-260826-134501-a1b2 : sortable, obviously synthetic, safe in a URL or a name.
_RUN_ID_RE = re.compile(r"^QA-\d{6}-\d{6}-[0-9a-f]{4}$")


def new_run_id() -> str:
    return f"QA-{time.strftime('%y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"


def looks_like_run_id(text: str) -> bool:
    return bool(_RUN_ID_RE.match(text or ""))


@dataclass
class TestData:
    """Names the records a test owns, and remembers what still exists."""

    run_id: str
    test_name: str
    prefix: str = ""
    _counter: int = 0
    created: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    def record(self, index: int | None = None) -> str:
        """A stable, unique, test-owned record name.

        The RUN_ID already identifies the run, so a bare prefix would only
        duplicate it: `QA-260826-101112-abcd-1`.
        """
        if index is None:
            self._counter += 1
            index = self._counter
        head = f"{self.prefix}-" if self.prefix else ""
        return f"{head}{self.run_id}-{index}"

    # -- ledger -------------------------------------------------------------
    def note_created(self, name: str) -> None:
        if name and name not in self.created:
            self.created.append(name)
            log.info("Test data created: %s", name)

    def note_removed(self, name: str) -> None:
        if name and name not in self.removed:
            self.removed.append(name)
            log.info("Test data removed: %s", name)

    @property
    def leftovers(self) -> list[str]:
        return [n for n in self.created if n not in self.removed]

    # -- templating ---------------------------------------------------------
    def substitute(self, value: str | None) -> str | None:
        """Expand {RUN_ID}, {record} and {record.N} in a step value."""
        if not value or "{" not in value:
            return value
        out = value.replace("{RUN_ID}", self.run_id)

        def repl(m: "re.Match[str]") -> str:
            idx = m.group(1)
            return self.record(int(idx) if idx else 1)

        out = re.sub(r"\{record(?:\.(\d+))?\}", repl, out)
        return out


class LeftoverReport:
    """Collects unremoved test data across a whole run."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.entries: list[dict[str, Any]] = []

    def add(self, run_id: str, test_name: str, names: list[str], why: str) -> None:
        if not names:
            return
        self.entries.append({"runId": run_id, "test": test_name,
                             "records": list(names), "reason": why,
                             "notedAt": time.strftime("%Y-%m-%dT%H:%M:%S")})
        log.error("LEFTOVER TEST DATA from %r: %s (%s). Remove these manually.",
                  test_name, ", ".join(names), why)

    @property
    def count(self) -> int:
        return sum(len(e["records"]) for e in self.entries)

    def write(self) -> None:
        if self.path is None:
            return
        if not self.entries:
            # No residue: remove a stale report from an earlier run so nobody
            # chases records that were already cleaned up.
            try:
                if self.path.is_file():
                    self.path.unlink()
            except OSError:
                pass
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"leftovers": self.entries, "count": self.count},
                                  indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)
        log.error("%d leftover record(s) written to %s", self.count, self.path.name)
