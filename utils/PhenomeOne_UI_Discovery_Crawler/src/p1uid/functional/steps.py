"""Declarative functional-test model.

A functional test is data, not code: a list of steps, each naming an action, a
target and (for assertions) an expectation. The same model is what the runner
executes and what a generator can emit, so there is one description of a test.

    navigate  go to a discovered UI state, using the learned navigation graph
    click     activate a control
    fill      type into a field
    select    choose an option in a <select> / listbox
    assert    check an expectation and record expected-vs-actual

Targets are resolved against the **existing UI map** wherever possible, so a
test refers to controls the discovery engine already validated instead of
re-inventing selectors. Nothing here builds a selector by hand: every target
ends up as a `locator.generator.Locator`, which `locator.validator.build()`
turns into a real Playwright locator.

Destructive steps (create/update/delete) must say so explicitly with
`"destructive": true`. The runner refuses to perform them unless the expected
state matches and the target resolves to exactly one element - fail closed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NAVIGATE, CLICK, FILL, SELECT, ASSERT = "navigate", "click", "fill", "select", "assert"
ACTIONS = (NAVIGATE, CLICK, FILL, SELECT, ASSERT)

# Declared for reporting and future selection; no selection logic yet.
LEVELS = ("smoke", "critical", "full")


@dataclass
class Target:
    """How to find a control.

    Resolution order (first usable wins):
      1. `locator`  - a raw locator spec, as stored in the UI map
      2. `state`+`key` - an element the discovery engine already validated
      3. `testid`   - data-testid
      4. `role`+`name` - ARIA role and accessible name
      5. `text`     - visible text
    `within` scopes the search inside another target, which is how a specific
    grid row is addressed: within={role: row, name: <record>}.
    """

    state: str | None = None
    key: str | None = None
    testid: str | None = None
    role: str | None = None
    name: str | None = None
    text: str | None = None
    exact: bool = True
    nth: int | None = None
    within: "Target | None" = None
    locator: dict[str, Any] | None = None

    @classmethod
    def from_json(cls, data: Any) -> "Target | None":
        if data is None:
            return None
        if isinstance(data, str):
            # Shorthand: "state#element-key" or just a test id.
            if "#" in data:
                state, key = data.split("#", 1)
                return cls(state=state or None, key=key)
            return cls(testid=data)
        inner = data.get("within")
        return cls(
            state=data.get("state"), key=data.get("key"), testid=data.get("testid"),
            role=data.get("role"), name=data.get("name"), text=data.get("text"),
            exact=bool(data.get("exact", True)), nth=data.get("nth"),
            within=cls.from_json(inner), locator=data.get("locator"),
        )

    def describe(self) -> str:
        bits = []
        if self.locator:
            bits.append(f"locator={self.locator.get('js') or self.locator}")
        if self.state or self.key:
            bits.append(f"map={self.state or '*'}#{self.key}")
        if self.testid:
            bits.append(f"testid={self.testid}")
        if self.role or self.name:
            bits.append(f"role={self.role or '*'} name={self.name!r}")
        if self.text:
            bits.append(f"text={self.text!r}")
        if self.nth is not None:
            bits.append(f"nth={self.nth}")
        desc = " ".join(bits) or "(no target)"
        if self.within:
            desc += f"  within[{self.within.describe()}]"
        return desc

    def substituted(self, expand) -> "Target":
        """Copy with {RUN_ID}/{record} expanded in the human-facing fields."""
        return Target(
            state=self.state, key=expand(self.key), testid=expand(self.testid),
            role=self.role, name=expand(self.name), text=expand(self.text),
            exact=self.exact, nth=self.nth,
            within=self.within.substituted(expand) if self.within else None,
            locator=self.locator,
        )

    def to_json(self) -> dict[str, Any]:
        d = {k: v for k, v in {
            "state": self.state, "key": self.key, "testid": self.testid,
            "role": self.role, "name": self.name, "text": self.text,
            "nth": self.nth, "locator": self.locator,
        }.items() if v is not None}
        if not self.exact:
            d["exact"] = False
        if self.within:
            d["within"] = self.within.to_json()
        return d


@dataclass
class Expect:
    """What an `assert` step checks. Exactly one primary check per step."""

    visible: bool | None = None
    hidden: bool | None = None
    count: int | None = None
    text_contains: str | None = None
    state: str | None = None
    enabled: bool | None = None

    @classmethod
    def from_json(cls, data: Any) -> "Expect | None":
        if data is None:
            return None
        if isinstance(data, str):
            # Shorthand: "visible" / "hidden"
            return cls(visible=True) if data == "visible" else cls(hidden=True)
        return cls(visible=data.get("visible"), hidden=data.get("hidden"),
                   count=data.get("count"), text_contains=data.get("textContains"),
                   state=data.get("state"), enabled=data.get("enabled"))

    def describe(self) -> str:
        for label, value in (("visible", self.visible), ("hidden", self.hidden),
                             ("count", self.count), ("textContains", self.text_contains),
                             ("state", self.state), ("enabled", self.enabled)):
            if value is not None:
                return f"{label}={value!r}"
        return "(no expectation)"

    def to_json(self) -> dict[str, Any]:
        return {k: v for k, v in {
            "visible": self.visible, "hidden": self.hidden, "count": self.count,
            "textContains": self.text_contains, "state": self.state,
            "enabled": self.enabled,
        }.items() if v is not None}


@dataclass
class Step:
    action: str
    target: Target | None = None
    value: str | None = None
    expect: Expect | None = None
    state: str | None = None          # guard: the state we must be in first
    to_state: str | None = None       # for navigate
    destructive: bool = False
    optional: bool = False            # a missing target skips instead of failing
    description: str = ""
    timeout_ms: int = 10000
    # Records created/removed by this step, for the cleanup ledger.
    creates: str | None = None
    removes: str | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Step":
        action = str(data.get("action", "")).lower()
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action!r}; expected one of {', '.join(ACTIONS)}")
        return cls(
            action=action,
            target=Target.from_json(data.get("target")),
            value=data.get("value"),
            expect=Expect.from_json(data.get("expect")),
            state=data.get("state"),
            to_state=data.get("toState") or data.get("to_state"),
            destructive=bool(data.get("destructive", False)),
            optional=bool(data.get("optional", False)),
            description=data.get("description", ""),
            timeout_ms=int(data.get("timeoutMs", 10000)),
            creates=data.get("creates"),
            removes=data.get("removes"),
        )

    def describe(self) -> str:
        if self.description:
            return self.description
        if self.action == NAVIGATE:
            return f"navigate to {self.to_state}"
        if self.action == ASSERT:
            return f"assert {self.expect.describe() if self.expect else '?'}"
        bits = f"{self.action} {self.target.describe() if self.target else ''}".strip()
        if self.value is not None and self.action in (FILL, SELECT):
            bits += f" = {self.value!r}"
        return bits


@dataclass
class FunctionalTest:
    name: str
    steps: list[Step] = field(default_factory=list)
    cleanup: list[Step] = field(default_factory=list)
    level: str = "smoke"
    tags: list[str] = field(default_factory=list)
    description: str = ""

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "FunctionalTest":
        level = str(data.get("level", "smoke")).lower()
        if level not in LEVELS:
            raise ValueError(f"unknown level {level!r}; expected one of {', '.join(LEVELS)}")
        return cls(
            name=data["name"],
            steps=[Step.from_json(s) for s in data.get("steps", [])],
            cleanup=[Step.from_json(s) for s in data.get("cleanup", [])],
            level=level,
            tags=list(data.get("tags", [])),
            description=data.get("description", ""),
        )

    @property
    def destructive_steps(self) -> list[Step]:
        return [s for s in self.steps + self.cleanup if s.destructive]


@dataclass
class Suite:
    name: str
    tests: list[FunctionalTest] = field(default_factory=list)
    base_state: str | None = None       # where every test starts
    source: str = ""

    @classmethod
    def from_json(cls, data: dict[str, Any], source: str = "") -> "Suite":
        return cls(name=data.get("name", "functional"),
                   tests=[FunctionalTest.from_json(t) for t in data.get("tests", [])],
                   base_state=data.get("baseState"), source=source)

    def select(self, level: str | None = None, names: list[str] | None = None) -> "Suite":
        """Filter by level or explicit names. Levels are ordered smoke < critical < full."""
        tests = self.tests
        if level:
            allowed = LEVELS[: LEVELS.index(level) + 1]
            tests = [t for t in tests if t.level in allowed]
        if names:
            wanted = {n.lower() for n in names}
            tests = [t for t in tests if t.name.lower() in wanted]
        return Suite(name=self.name, tests=tests, base_state=self.base_state, source=self.source)


def load_suite(path: str | Path) -> Suite:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    suite = Suite.from_json(data, source=str(p))
    if not suite.tests:
        raise ValueError(f"{p} defines no tests")
    return suite
