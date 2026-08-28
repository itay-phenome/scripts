# Architecture

## Stack

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.14 | Playwright + tkinter + PyInstaller all first-class on Windows; no extra runtime |
| Browser control | Playwright 1.61, **async** API | see *Threading* below |
| Browser | Chromium only, bundled | no dependency on installed Chrome/Edge |
| GUI | tkinter/ttk (stdlib) | zero extra dependency, packages cleanly, reliability over looks |
| Packaging | PyInstaller 6.21, **onedir** | one folder, fast startup, Chromium sits beside the exe instead of being unpacked on every run |
| Secrets | Windows DPAPI via `ctypes` | no third-party crypto dependency |

Runtime dependency count: **one** (`playwright`). Everything else is stdlib.

## Module map

```
src/p1uid/
  app.py                  entry point: GUI or --cli
  paths.py                portable path resolution (APP_DIR, P1UID_HOME override)
  logging_setup.py        logging + mandatory secret redaction
  gui/main_window.py      tkinter window; owns no Playwright state
  browser/
    controller.py         Engine: asyncio loop in a thread, browser lifecycle, ops, outputs
    injected.py           CORE_JS: all in-page analysis + observation (the heart of it)
  auth/login.py           confidence-gated login form analysis + submission
  discovery/scanner.py    collect -> generate -> validate -> merge, with timings
  locator/generator.py    7-tier locator strategy + confidence scoring
  locator/validator.py    resolves locators through Playwright itself
  state/fingerprint.py    UI-state identity (route + tab + dialogs + landmarks)
  store/uimap.py          incremental merge, locator history, UNSTABLE detection
  navigation/graph.py     nodes/edges + readable spanning tree
  training/trainer.py     correlates observed actions with observed state changes
  training/workflows.py   named workflow recording
  discovery/stability.py  waitStable(): settle detection for autonomous discovery
  crawler/safety.py       SAFE_NAVIGATION / CONDITIONAL / DANGEROUS / UNKNOWN
  crawler/bfs.py          Safe Crawl: budgeted, read-only autonomous exploration
  crawler/outcomes.py     what an observation MEANS: facts, poisoning, productivity
  crawler/surfaces.py     Surface/SurfaceRegistry/scope_of(): tabs, windows, popups
  functional/steps.py     declarative test model (navigate/click/fill/select/assert)
  functional/runner.py    executes tests; fails closed on destructive actions
  functional/data.py      RUN_ID, test-owned records, cleanup ledger
  functional/evidence.py  screenshot, trace, console/page/network capture
  functional/results.py   functional PASS/FAIL results
  diff.py                 UI diff between two maps
  codegen.py              Playwright asset generation
  reporting/html_report.py self-contained HTML report
  reporting/junit.py      JUnit for discovery health (weak/unstable locators)
  reporting/junit_functional.py JUnit for functional results
  security/               dpapi.py, session_store.py
```

The GUI is a thin shell: it submits named operations to the `Engine` and renders
events off a `queue.Queue`. `Engine` is fully usable without it — that is how the
CLI, Safe Crawl, test generation and the functional runner all drive it.

## Threading

```
main thread            engine thread                  browser process
-----------            -------------                  ---------------
tkinter mainloop  --->  asyncio loop  <--- CDP --->  Chromium
   ^                    (Playwright async API)          |
   |  queue.Queue        ^                              |
   +---- events ---------+------ expose_binding --------+
```

Playwright's **sync** API only dispatches `expose_binding` callbacks while a
Playwright call is in flight — with it, training would need a polling loop
(`wait_for_timeout` forever). On an asyncio loop, binding callbacks arrive as
they happen. That is the whole reason for the async API here: spec §28 forbids
polling where browser events exist.

tkinter is not thread-safe, so the engine never touches widgets; it puts dicts on
a queue that the GUI drains with `after(120ms)`.

## Why the analysis lives in the browser

`injected.py` computes role, accessible name, visibility, enabled state,
test-id attributes, grid metadata, uniqueness counters and page structure in a
**single** `evaluate()` per frame. A Playwright round trip costs milliseconds; a
page with 300 interactive elements would cost seconds if queried element by
element. Measured: ~10 ms in-page for a whole page.

Playwright 1.61 no longer exposes `page.accessibility`, so role/accessible-name
computation is an ARIA + HTML-AAM subset implemented in that file. It is
deliberately approximate — the locator *validation* step is what makes the
result trustworthy, and a name mismatch simply shows up as `matches: 0` and a
downgraded confidence.

## UI-state identity

URL is not enough: `/research-group/123` covers Overview, Germplasms, Variables…
A fingerprint is `sha256(normalised route + active tab + open dialogs + tab set +
landmark roles)`, truncated to 12 hex chars. Deliberately excluded: record ids
(`/research-group/123` → `/research-group/:id`), business names, timestamps,
result counts. So two different research groups with the same layout collapse to
one state — which is what a test author wants — while switching tab or opening a
dialog creates a distinct state.

State **ids** are readable slugs (`research-group-germplasms`) assigned once per
fingerprint and persisted, so they stay stable across sessions.

### Dialog titles are normalised before hashing

A dialog title is structural — "Add Germplasm" and "Confirm delete" are genuinely
different states — but real applications put the *record* in the title: `Edit
INV-0001`. Hashed verbatim, that produces one state per record, so a 500-record
grid yields 500 "edit" states and the map stops being a map.

`normalise_dialog_title()` therefore rewrites the title one **token** at a time.
A token is replaced with an `:id`-style placeholder — the same convention route
segments already use — only when the token itself looks like an identifier, and
a token must contain a digit to be considered at all:

| token shape | example | becomes |
| --- | --- | --- |
| prefixed record id | `INV-0001`, `GP-001` | `:id` |
| letters + 4 digits | `INV0001` | `:id` |
| bare 4+ digits | `918273` | `:id` |
| `#` reference | `#4521` | `:id` |
| UUID | `9f8a7b6c-…` | `:uuid` |
| 24+ hex chars | `a1b2c3…` | `:hash` |
| 28+ char id with a digit | `QA260824abcdef…` | `:token` |
| date | `2025-02-11`, `11/02/2025` | `:date` |
| time | `14:03` | `:time` |

So `Edit INV-0001` and `Edit INV-0002` both become `Edit :id` — one state —
while every alphabetic word survives untouched. Deliberate non-goals:

* **Bare 1–3 digit numbers are kept.** `Step 2 of 3` and `Step 3 of 3` are
  distinct wizard states, and merging them would be worse than the problem being
  solved. The cost is that a count-bearing title such as `Archive 3 items` still
  fragments; that is accepted as the conservative trade.
* **Nothing is stripped, only substituted.** A title that is *entirely* an
  identifier collapses to `:id` rather than to an empty string, so such dialogs
  still merge with each other and remain distinguishable from no dialog at all.
* **Stacked dialogs stay distinct.** Two open dialogs normalise to two entries,
  so a modal-over-modal state does not collapse into the single-modal one.

The state **slug** is built from the surviving words only, so the id reads
`…-dialog-edit`, not `…-dialog-edit-id`. The report **label** shows the
normalised title too: the state represents the whole class of edit dialogs, and
showing one record's name there would be a fiction — and would put business data
in the UI map, which §12 forbids independently of any of this.

**Compatibility.** This changes fingerprint *inputs*, so any state whose dialog
title contains a volatile token gets a new digest, and a UI map recorded before
this change will show that state as new (its old entry simply stops being
matched; nothing is corrupted, and re-scanning re-establishes it). States with a
stable title — every dialog in the existing mock suite: `Add Germplasm`, `Edit
Germplasm`, `Record details` — hash exactly as before, and route, tab, landmark
and element identity are untouched.

## Action attribution

The browser reports which control caused a given state change (`cause` on the
`state-changed` event), rather than Python guessing from "the most recent click".
Without that, a fast click sequence credits the wrong control — a dialog opened
by *Add Germplasm* was being attributed to *Close dialog*. Both real
(`pointerup`) and programmatic (`click`) activations are captured, de-duplicated
within 600 ms.

## Verified browser behaviours

Empirically checked against Playwright 1.61 rather than assumed:

* Of every strategy generated, **only `getByRole` skips CSS-hidden elements**.
  Hence hidden elements get `validation: "deferred-hidden"` and MEDIUM instead of
  a misleading LOW.
* `launch(headless=True)` needs the separate `chromium_headless_shell` download;
  `launch(headless=True, channel="chromium")` runs headless from the full
  Chromium build. That saves 270 MB in the package.
* Chromium fails to start when its own path is very deep — the app warns above
  150 characters.
* `is_visible()`/`is_enabled()` must be given explicit short timeouts, or an
  element that disappeared between collect and validation stalls a scan for the
  full 30 s default.

## Action safety (autonomous discovery foundation)

`crawler/safety.py` decides whether a machine may click something, from the
element record alone - no clicking, no model, no network. Three rules shape it:

1. **Fail closed.** Only positively-recognised navigation (tabs, same-origin
   links, expanders, pagination, menu openers) becomes SAFE_NAVIGATION.
   Everything else lands in CONDITIONAL or UNKNOWN. An unlabelled icon button is
   UNKNOWN - it might be Save, it might be Delete. One corroborated exception: a
   labelled control with no semantics at all becomes SAFE_NAVIGATION when at
   least three controls of the same shape share the page, because a row in a list
   navigates rather than acts (`list-shape`; real dhtmlxTree markup made every
   screen unclickable without it).
2. **Structure beats words.** `<button>` with no `type` inside a form submits it,
   so a button captioned "Go" in a POST form is DANGEROUS. Likewise
   `input[type=submit|reset|image]`, downloads, `mailto:`/`javascript:`/`blob:`/
   `data:` URLs and cross-origin hrefs. A destructive verb in a URL command
   parameter (`?action=delete`) outranks the link text. `target=_blank` is *not*
   in this list: where the click lands is observed after the fact instead
   (`crawler/outcomes.py`), because refusing it made whole parts of an
   application unreachable by construction.
3. **One gate.** `auto_clickable` is the only thing a crawler consults, and it is
   forced False for DANGEROUS and UNKNOWN regardless of what the rules concluded.

Two subtleties worth keeping: "OK"/"Yes"/"Continue" are *not* dismissals - in a
confirm dialog they execute the destructive action - while "Close dialog" is; and
a dismissal verb aimed at something that is not a UI surface ("Close account")
is destructive. Context downgrades too: nothing inside an "Add ..." dialog or a
form counts as plain navigation.

`waitStable()` is the other half of the foundation. It resolves when there have
been no mutations *and* no signature change for a quiet window. `networkidle` is
avoided deliberately: a SaaS page that polls or holds a socket open never
reaches it, and a page is usually settled long before its background traffic is.

## Two directories, deliberately

`INSTALL_DIR` is where the executable and the bundled browser live. `APP_DIR` is
where output/config/logs/sessions are written, and `P1UID_HOME` overrides only
that. They were the same variable until Phase 1, which meant pointing outputs at
a CI workspace silently made Chromium unfindable - Playwright fell back to a
"development mode" cache that does not exist on a clean machine.

## Functional testing (Phase 1)

Discovery and functional testing are separate layers with one shared substrate:

```
             discovery                         functional QA
  scanner -> locator/{generator,validator} -> functional/runner
             state/fingerprint                (navigate/click/fill/select/assert)
             store/uimap  ------------------>  target resolution
             navigation/graph ------------->   route resolution
```

The runner performs actions and assertions; it does not invent selectors. Every
target becomes a `locator.generator.Locator` that `locator.validator.build()`
resolves, and a route comes from `navigation.graph.shortest_path()` over edges
the tool actually observed. So a functional test inherits the confidence,
history and validation of the discovery layer instead of duplicating it.

**Destructive actions fail closed.** A create/update/delete step must declare
`destructive: true`, and the runner refuses to click unless the current state
matches the step's declared state, the target resolves to exactly one element,
and that element is visible and enabled. This is a separate, explicitly
authorised path: `crawler/safety.py` is untouched and Safe Crawl remains
read-only, so autonomous exploration can never perform a write.

## Safety

Training only listens. Listeners are capture-phase and passive, and never call
`preventDefault`, `stopPropagation`, or dispatch synthetic events. No code path
clicks, fills, or submits anything in the target application except the login
form the user explicitly asked for.
