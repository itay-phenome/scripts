"""What actually happened after an action.

The crawler used to decide what an action *would* do from the control's
attributes - a `target=_blank` link was refused before it was ever clicked, a
popup was closed on sight - so any part of the application that opened in a new
browsing context was unreachable by construction.

This module inverts that. An action is performed, the browser is observed, and
the resulting facts are classified here. Nothing in this module touches the
browser: it turns an `Observation` into a set of outcome names, which makes the
whole decision table testable without a page.

A single action can produce several facts at once - opening a detail tab *and*
changing the parent state - so `classify()` returns all of them. `primary` picks
the most decisive one for logging and for the incident record.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --- outcome names -----------------------------------------------------------
NO_CHANGE = "no-change"                        # nothing observable happened
NEW_STATE = "same-surface-new-state"           # this surface became a new UI state
SURFACE_CHANGED = "surface-changed-same-state"  # DOM moved, state identity did not
NEW_SURFACE_IN_SCOPE = "new-surface-in-scope"   # a tab/window of the application
NEW_SURFACE_IRRELEVANT = "new-surface-irrelevant"   # our domain, not the app
NEW_SURFACE_EXTERNAL = "new-surface-external"   # somebody else's site
NEW_SURFACE_UNKNOWN = "new-surface-unknown"     # about:blank, or unreadable
NATIVE_DIALOG = "native-dialog"                 # confirm()/alert() was raised
LEFT_ORIGIN = "left-origin"                     # this surface navigated off-origin
SESSION_LOST = "session-lost"                   # authentication is gone
UNSCANNABLE = "unscannable"                     # nothing analysable here

# Most decisive first. Order matters only for `primary`; the crawler acts on the
# full set.
_PRECEDENCE = (
    SESSION_LOST, NATIVE_DIALOG, LEFT_ORIGIN,
    NEW_SURFACE_IN_SCOPE, NEW_SURFACE_IRRELEVANT, NEW_SURFACE_EXTERNAL,
    NEW_SURFACE_UNKNOWN, UNSCANNABLE, NEW_STATE, SURFACE_CHANGED, NO_CHANGE,
)

# Outcomes that mean "this action must never be tried again from this state".
POISONING = frozenset({NATIVE_DIALOG, LEFT_ORIGIN,
                       NEW_SURFACE_EXTERNAL, NEW_SURFACE_IRRELEVANT})

# Outcomes proving the action did something worth keeping, so it must not be
# pruned as inert even when the state id did not change.
PRODUCTIVE = frozenset({NEW_STATE, SURFACE_CHANGED,
                        NEW_SURFACE_IN_SCOPE, NEW_SURFACE_IRRELEVANT,
                        NEW_SURFACE_EXTERNAL, NEW_SURFACE_UNKNOWN})

_SCOPE_TO_OUTCOME = {
    "in-scope": NEW_SURFACE_IN_SCOPE,
    "irrelevant": NEW_SURFACE_IRRELEVANT,
    "external": NEW_SURFACE_EXTERNAL,
    "unknown": NEW_SURFACE_UNKNOWN,
}


@dataclass
class Observation:
    """Everything seen after one action, before any decision is taken."""

    state_before: str = ""
    state_after: str = ""
    signature_before: str = ""
    signature_after: str = ""
    scannable: bool = True
    session_lost: bool = False
    dialogs_raised: int = 0
    origin_before: str = ""
    origin_after: str = ""
    # (page, scope) for every browsing context that appeared during the action.
    new_surfaces: list[tuple[Any, str]] = field(default_factory=list)


@dataclass
class Outcome:
    facts: list[str]

    @property
    def primary(self) -> str:
        for name in _PRECEDENCE:
            if name in self.facts:
                return name
        return NO_CHANGE

    def __contains__(self, name: str) -> bool:
        return name in self.facts

    @property
    def poisons(self) -> bool:
        return bool(set(self.facts) & POISONING)

    @property
    def productive(self) -> bool:
        return bool(set(self.facts) & PRODUCTIVE)

    def describe(self) -> str:
        return "+".join(self.facts) or NO_CHANGE


def classify(obs: Observation) -> Outcome:
    """Turn an observation into the set of things that happened."""
    facts: list[str] = []

    if obs.dialogs_raised > 0:
        facts.append(NATIVE_DIALOG)
    if obs.session_lost:
        facts.append(SESSION_LOST)

    for _page, scope in obs.new_surfaces:
        name = _SCOPE_TO_OUTCOME.get(scope, NEW_SURFACE_UNKNOWN)
        if name not in facts:
            facts.append(name)

    # Off-origin navigation of the surface we clicked on. A new *surface* landing
    # off-origin is not this - that is already covered above.
    if obs.origin_before and obs.origin_after and obs.origin_after != obs.origin_before:
        facts.append(LEFT_ORIGIN)

    if not obs.scannable:
        facts.append(UNSCANNABLE)
    elif obs.state_after and obs.state_after != obs.state_before:
        facts.append(NEW_STATE)
    elif obs.signature_before and obs.signature_after \
            and obs.signature_after != obs.signature_before:
        # The state id is unchanged but the DOM is not. An opened menu is the
        # case that matters: a dropdown is not a route, a tab, a dialog or a
        # landmark, so no fingerprint input moves - and the old crawler counted
        # the menu button as inert and pruned it after two states. PhenomeOne's
        # "Actions" menu is the primary affordance surface for Study and Trial
        # operations, so pruning it removes most of the application.
        facts.append(SURFACE_CHANGED)

    if not facts:
        facts.append(NO_CHANGE)
    return Outcome(facts=facts)
