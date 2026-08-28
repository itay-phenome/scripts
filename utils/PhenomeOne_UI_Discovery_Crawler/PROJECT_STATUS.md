# PROJECT STATUS — PhenomeOne UI Discovery

**Handoff document. Read this first in a new session.**

| | |
|---|---|
| Last updated | 2026-08-28 |
| Version | 1.7.0 (discovery + outcome-driven multi-surface crawl + functional QA engine + session-first connect + semantics-free controls + **data-vs-control separation**) |
| Source | `scripts/utils/PhenomeOne_UI_Discovery_Crawler/` on `main` of `github.com/itay-phenome/scripts` (pushed) |
| Build output | `dist\PhenomeOne-UI-Discovery\` in this repo (553 MB, git-ignored) - **1.7.0, verified 2026-08-28** (`test_packaged.py` 30/30 on the relocated folder) and used for the crawls in Phase 15. See §5 |
| Executables | `PhenomeOne-UI-Discovery.exe` (GUI), `PhenomeOne-UI-Discovery-cli.exe` (CI) |
| Tests | **669/669 source passing** — 14 suites, one clean run measured 2026-08-28 on 1.7.0, no flaky suite. Plus `test_packaged.py` 30/30 on the 1.7.0 build |
| Blocked on | **Nothing local.** The intended workflow - a human signs in once, then the tool runs itself - is implemented, test-proven, and now the primary GUI path (CONNECT + "then Safe Crawl"). What is missing is one **completed Safe Crawl on the real application, with its artifacts kept**. See §4 |
| Real access so far | 2026-08-24 against `eksdemo-helm.phenome-networks.com` - login only, exposed 4 bugs (Phase 7). 2026-08-27 - connect + scan, produced Phases 13 and 14. **No `crawl-summary.json` or real `ui-map.json` exists on disk**: those findings survive as code comments only |

---

## 1. What this is

A portable Windows tool that learns the PhenomeOne web UI and emits a deterministic
**UI knowledge layer** (states, elements, validated Playwright locators, navigation
graph) so automated tests never pay an LLM to hunt for buttons.

**No LLM/API call happens at discovery time.** Everything is DOM + ARIA analysis
and Playwright locator validation.

---

## 2. Completed work

### V1 (delivered earlier)
| Area | State |
|---|---|
| Portable Windows build | onedir + bundled Chromium, no runtime deps, relocation-tested |
| GUI (tkinter) | login, manual login, scan, training, outputs, session controls |
| CLI | headless entry point for CI, password only via `$P1UID_PASSWORD` |
| Login | confidence-gated; waits ≤20 s; searches **all frames**; clicks a single unambiguous "Sign in" entry point; refuses when unsure |
| Discovery engine | one `evaluate()` per frame; ARIA role/name computed in-page |
| Locator engine | 7-tier strategy, validated through Playwright, HIGH/MEDIUM/LOW |
| State fingerprinting | route + active tab + dialogs + tab set + landmark roles |
| Training mode | observation-only; browser reports the *causing* action per state change |
| Incremental map | merge, `timesSeen`, `locatorHistory`, `UNSTABLE LOCATOR` flag |
| Reports | self-contained HTML, JSON outputs |
| Security | password memory-only, DPAPI session, log redaction, no business data |

### Phase 1 — Safe Crawl foundation
* `discovery/stability.py` — `wait_stable()`: MutationObserver + structural
  signature quiet window. No sleeps, no `networkidle` (asserted by test).
* Extended element records: `inputType`, `buttonType`/`effectiveButtonType`,
  `inForm`, `form{identity,method,action}`, `link{scheme,origin,sameOrigin,
  download,fileLike,target,empty}`, `hasPopup`, `iconOnly`, `context{dialog,
  toolbar,grid,menu,landmark,inRow}`.
* `crawler/safety.py` — SAFE_NAVIGATION / CONDITIONAL / DANGEROUS / UNKNOWN with
  reasons, flags and a single `auto_clickable` gate.
* Mock app hardened into a deliberate minefield (Admin tab).

### Phase 2 — BFS Safe Crawler
* `crawler/bfs.py` — breadth-first exploration clicking **only** `auto_clickable`
  actions; budgets (states/actions/depth/time/per-state); deterministic order.
* Returns to a state via `go_back()` first, else replays the discovered locator
  path from the start URL. Roots itself at the start URL so replay always works.
* Guards: native dialogs always dismissed + the action poisoned; downloads
  refused at context level (`accept_downloads=False`); off-origin navigation
  reverted + poisoned; **session loss aborts the crawl**.
  (Popups were closed on sight here; **superseded by Phase 12E**, which decides
  from the observed surface instead.)
* Writes `output/crawl-summary.json`; edges tagged `trigger: "safe-crawl"` with
  the safety class that authorised them.

### Phase 3 — Workflow recording
* `training/workflows.py` + trainer hooks + GUI field/button + `--workflow NAME`.
* Named step sequences (`navigate`/`activate`/`fill`) merged across sessions into
  `output/workflows.json`. **No field values are ever captured.**

### Phase 4 — UI diff
* `diff.py` — compares two `ui-map.json` by identity (fingerprint / element key).
* `+ - ~` text lines, `output/ui-diff.json`, `reports/ui-diff.html` with a
  "test-breaking locator changes" table. CLI `--diff BASELINE CURRENT`, exit 5 on
  differences.

### Phase 5 — Test generation
* `codegen.py` → `output/generated/`: `ui-map.ts` (typed locators per state),
  `navigation.ts` (`NAV_STEPS` + `goToState()`), `smoke.spec.ts` (one test per
  state), `ui_map.py` (playwright-python page objects), `README.md` listing what
  was skipped and the `data-testid` to add. Only validated HIGH/MEDIUM locators
  are emitted; LOW appear as `// SKIPPED` with the recommendation.

### Phase 6 — Jenkins integration
* `reporting/junit.py` → `reports/junit-discovery.xml`: a case per state,
  failures for LOW locators (with the suggested test id) and UNSTABLE locators,
  skipped for `deferred-hidden`.
* CLI gate `--fail-on-low N` → exit **4**. Exit codes: 0 ok · 2 bad args ·
  3 not authenticated · 4 CI gate · 5 diff found changes.

### Phase 7 — Live-environment hardening (from the first real PhenomeOne run)

The first run against `eksdemo-helm.phenome-networks.com` produced four failures.
All are fixed and covered by `tests/test_recovery.py` (15 checks):

| Symptom in the live log | Cause | Fix |
|---|---|---|
| "Authentication successful (manual)" 1 s after load | the SPA had not rendered its login form, so "no password field" read as "signed in" | Manual Login now waits for the form to **appear** before its disappearance can mean success; if none appears it probes for app markers and says "existing session" or "no sign-in form detected" + diagnostics |
| `TargetClosedError` on every action after the browser was closed | the engine kept a dead handle | `_revive()`/`_teardown()`: a closed tab gets a fresh one (navigated back to the app), a closed browser is relaunched |
| `login: another operation is still running` | the 600 s manual-login wait held the exclusive lock | `manual_login` is non-exclusive, and pressing LOGIN cancels the wait |
| "New browser tab detected; observing it" at startup | our own first tab fired the popup handler | the `page` listener is registered after the first tab exists |

Also fixed while in there:
* **GUI single instance** — a second launch raises the existing window and exits
  instead of starting a rival copy behind it ("the app doesn't open").
* **Window placement** — the window is clamped to the work area and raised to
  the front on startup.
* **No blank states** — `about:blank`/error pages are never recorded as UI states.

### Phase 8 — Local QA / red-team pass (2026-08-25)

Adversarial pass whose goal was to make the tool do damage. Bugs found and fixed:

| # | Severity | Bug | Fix |
|---|---|---|---|
| 1 | **CRITICAL (safety)** | A destructive command hidden in a query string was invisible to the classifier: `<a href="/germplasm?action=delete&id=7">Open record</a>` classified **SAFE_NAVIGATION** and *would have been clicked* by the crawler. The injected core never exposed `location.search`. | Core now reports `link.search`; the classifier treats a destructive verb in a command parameter (`action`/`op`/`do`/`cmd`/`method`/`task`/…) as structural, with its own `dangerous-query` flag, evaluated before any label vocabulary. Benign queries (`?tab=overview&sort=name&page=3`) still navigate. |
| 2 | Medium (precision) | An embedded sign-in widget (an IdP iframe on a page) aborted a healthy crawl as "session lost". | Session loss now requires a visible password field **and** the app no longer rendering (`looks_authenticated`). |
| 3 | Medium (efficiency) | Naive BFS re-clicked global controls from every state: 120 clicks / 151 s for 11 states, hitting the action budget with 30 no-op clicks. | Inert elements are learned and skipped globally; one element may be retried from at most `max_repeats_per_element` (3) states. **40 clicks / 56 s for the same 11 states** — no budget exhaustion. |
| 4 | Low (consumer) | Generated page objects listed dialog/menu locators with no hint that they cannot resolve until that surface is open, so a consumer sees them as broken. | Each such property is annotated `NOT VISIBLE in this state: open <dialog> first`, plus machine-readable `NEEDS_OPENING` / `STATES` registries in both TS and Python. |
| 5 | Low (self-inflicted) | Scripted edits silently mangled backslash-escapes (backslash-b, backslash-n, backslash-s) into raw control bytes, once disabling a live regex rule. | Every scripted edit is followed by a control-byte scan of `src/` (command in section 5). |

Test-premise defects corrected (not product bugs, but they made a test lie):
* the "report is self-contained" check rejected an environment URL printed as
  *data*; it now checks for resource **loading** (`<script`, `src=`, `href=`, `@import`);
* the artifact list asserted files the tool never wrote — it is now the exact
  produced set, missing **and** unexpected;
* a red-team control was named "Browse archive", so the dangerous-verb rule fired
  before the empty-`href` path it was meant to exercise.

Accepted limitation (documented, not fixed): a control whose accessible name
**misdescribes** its behaviour ("View report" that deletes) cannot be classified
from the DOM. Mitigation: crawl only non-production environments, and the
per-app vocabulary tuning in §4.

### Phase 9 — Functional QA engine (Phase 1 of the QA platform, 2026-08-26)

The discovery engine now has a functional-testing layer on top of it. Discovery
is unchanged; nothing was refactored broadly.

**1. Fixed: the data home hijacked the browser lookup.** `BROWSER_DIR` was derived
from `APP_DIR`, so `P1UID_HOME` (used to put outputs in a CI workspace) silently
moved the bundled-Chromium lookup too and fell back to a "development mode" cache
that does not exist on a clean machine. Now `INSTALL_DIR` (executable + browser)
and `APP_DIR` (data) are separate; `P1UID_BROWSERS_PATH` overrides the browser
explicitly.

**2. Declarative step model** — `functional/steps.py`. A test is JSON:
`navigate | click | fill | select | assert`, with targets resolved against the
existing UI map (`state#key`, test id, role+name, text, or a raw locator spec) and
`within` for scoping to a grid row. Levels (`smoke`/`critical`/`full`) are declared
and selectable via `--test-level`.

**3. Execution reuses discovery, does not duplicate it** — `functional/runner.py`.
Targets become `locator.generator.Locator` objects resolved by
`locator.validator.build()`; routes come from the new
`navigation.graph.shortest_path()` over observed edges; state identity comes from
`discovery.scanner`; settling from `discovery.stability`. The runner adds only
actions, assertions and guards.

**4. Destructive actions fail closed.** A create/update/delete step must declare
`destructive: true`; the runner then refuses to click unless the current state
equals the declared state, the target resolves to exactly one element, and it is
visible and enabled. **Safe Crawl and `crawler/safety.py` are untouched** - the
functional path is separate and explicitly authorised, so autonomous exploration
still cannot write. Asserted by the test suite.

**5. Deterministic test data** — `functional/data.py`. `RUN_ID`
(`QA-260826-110404-a231`), `{record}` / `{RUN_ID}` substitution in values *and*
targets, an ownership ledger, cleanup that runs even after failure, and
`output/functional-leftovers.json` for anything cleanup could not remove.

**6. Failure evidence** — `functional/evidence.py`. Screenshot, Playwright trace
(one chunk per test, kept only on failure), failed step/action/target, the locator
used, expected vs actual, the page's real URL/title/visible heading, plus console
messages, page errors and network failures (`requestfailed` and 4xx/5xx) sliced to
the failing test.

**7. Separate results** — `output/functional-results.json` and
`reports/junit-functional.xml`, distinct from `junit-discovery.xml`. New exit
code **6** for functional failure (0 ok, 2 args, 3 auth, 4 locator gate, 5 diff).

**Milestone proven**: `tests/functional/germplasm_crud.json` runs
create -> verify -> update (row-scoped Edit) -> delete (row-scoped Delete) ->
verify deletion, against the mock, 17 steps, all green. The mock gained real CRUD
(sessionStorage-backed) seeded with the same two rows it always had, so every
existing discovery test sees an unchanged screen. Row action buttons keep generic
labels on purpose - a record name in an `aria-label` would leak business data into
the UI map.

Also fixed: the evidence page-snapshot reported the first `h1` even when hidden,
so a failure in the SPA claimed the heading was "PhenomeOne" (the hidden login
view). It now reports the first *visible* heading.

Deliberately **not** done in this phase, as instructed: geometry capture,
automatic locator healing, Jenkinsfile, GUI button for functional runs.

### Phase 10 — Hardening against component-framework UIs (2026-08-26)

Chosen over real-environment validation because credentials were not available.
`tests/mock_app/hardgrid.html` was built to break the engine's comfortable
assumptions the way a real Angular/Material SaaS will, and then the engine was
fixed until it coped.

What the adversarial page does: a `role=combobox` whose `role=listbox` is
**portaled to `<body>`** and does not exist until clicked; a **virtualised grid**
(500 records, ~13 rows in the DOM); rows identified only by cell text; and an
edit dialog whose **heading contains the record name**.

| Assumption tested | Verdict |
|---|---|
| Row addressing by accessible name | **Held.** `get_by_role('row', name='INV-0001')` matches a rendered row from its cell text. |
| Options are discoverable from the map | **Failed, by design of the framework.** `options` is only captured for a real `<select>`; a portaled listbox has no DOM until opened. Recorded as a documented gap - the functional layer opens the control instead. |
| `assert count == 0` means "deleted" | **Dangerous.** With virtualisation an existing record is simply absent from the DOM. The suite now uses **filter-then-assert**, so an absence check is meaningful; the trap itself is asserted by the test. |

Engine changes:
* **`select` is polymorphic** - native `<select>` uses `select_option`; anything
  else is opened, the `role=option` is located *anywhere on the page* (the overlay
  is not a child of the control), clicked, and then the control is **read back** to
  confirm it took the value rather than trusting the click. Ambiguous or absent
  options fail closed, and a stray overlay is dismissed on failure.
* **Inter-test UI reset** - a test that failed with a modal open used to poison
  every later test, because everything behind a modal is inert and the next click
  merely timed out. The runner now clears stray modal/overlay surfaces between
  tests (Escape, then a return to the start URL if that is not enough).
* `scroll_into_view_if_needed` before a click, for long grids.

A finding about the *mock*, not the engine: the first version combined a native
`<dialog>` opened with `showModal()` **and** a body-portaled listbox. The native
modal occupies the top layer, so the portaled option is visible but **inert** - a
hit-test at its centre returns the dialog. No component framework ships that
combination (Material uses `div[aria-modal]` + a CDK backdrop precisely so overlay
siblings stay interactive), so the page was corrected. The engine's timeout was
the right behaviour.

Measured on this page: a volatile dialog title fragmented the state map. Editing
two records yielded `hardgrid-html-dialog-edit-inv-0001` and `...-inv-0002` - one
state per record. Reported rather than silently fixed, because it changes
fingerprint inputs. **Approved by you on 2026-08-26 and now fixed** - see Phase
10a.

### Phase 10a — Volatile dialog-title normalisation (2026-08-26, approved)

`state/fingerprint.py` gained `normalise_dialog_title()`, applied to every open
dialog title before it is hashed, slugged or labelled. The rule is
token-by-token: a token is replaced with an `:id`-style placeholder - the same
convention route segments already use - only when the token itself looks like an
identifier, and it must contain a digit to be considered at all. Full rule table
and rationale: **ARCHITECTURE.md → "Dialog titles are normalised before
hashing"**.

| | |
|---|---|
| Collapses | `INV-0001`/`GP-001` → `:id`, `INV0001` → `:id`, 4+ bare digits → `:id`, `#4521` → `:id`, UUID → `:uuid`, 24+ hex → `:hash`, 28+ char id containing a digit → `:token`, `2025-02-11`/`11/02/2025` → `:date`, `14:03` → `:time` |
| Never touched | every alphabetic word; bare 1-3 digit numbers |
| Result | `Edit INV-0001` and `Edit INV-0002` are **one** state, `hardgrid-html-dialog-edit`; `Add Germplasm` stays a separate state |

Deliberate limits, all test-asserted:
* **1-3 digit numbers survive**, so `Step 2 of 3` and `Step 3 of 3` remain
  distinct wizard states. The accepted cost: a count-bearing title such as
  `Archive 3 items` still fragments. Merging wizard steps would be worse than
  the problem being solved.
* **Substitution, never deletion.** An all-identifier title collapses to `:id`,
  so those dialogs still merge with each other and a dialog is still
  distinguishable from no dialog.
* **Stacked dialogs stay distinct** - two open dialogs normalise to two entries.
* The state **slug** is built from surviving words only (`...-dialog-edit`, not
  `...-dialog-edit-id`), and the report **label** shows the normalised title,
  because the state represents the whole class of edit dialogs - and showing a
  record name there would put business data in the UI map, which §12 of the spec
  forbids independently.

**Compatibility.** Fingerprint *inputs* changed, so a state whose dialog title
contains a volatile token gets a new digest; a UI map recorded before this change
shows that state as new, and re-scanning re-establishes it (nothing is
corrupted). Every dialog in the existing mock suite has a stable title - `Add
Germplasm`, `Edit Germplasm`, `Record details` - so those digests are **byte-identical
to before**. Routes, tabs, landmarks and element identity are untouched.

Regression cover: `test_units.py::test_dialog_title_normalisation` (40 checks -
7 volatile pairs proved to collapse, 7 stable pairs proved to stay distinct, plus
idempotence, all-volatile, stacked-dialog and route-untouched guards) and
`test_hardgrid.py` section 5, which now proves in a live browser that editing two
records yields **one** state id while Add remains its own.

### Phase 11 — Login fixes from the second real PhenomeOne run (2026-08-26)

Two runs against `eksdemo-helm.phenome-networks.com` produced two defects. Both
were **timing** bugs, not heuristic gaps — the login vocabulary was never touched.

**1. Manual Login double-press sabotaged itself.** Pressing Manual Login again
during the wait started a second attempt that re-navigated, destroying the form
the first attempt was waiting for; the first then reported "No sign-in form
appeared within 20 s" about a page that no longer existed. The live log made the
timing unambiguous: navigation at 13:41:50, second press 13:42:08, stale verdict
13:42:10 — exactly 20 s after the *first* navigation.

`op_manual_login` now carries a generation number. A new press increments it and
older waits stand down silently instead of publishing a verdict; when a wait is
already in progress the new press does **not** re-navigate. The waiting half
moved to `_manual_login_wait()` so one `finally` releases the in-progress flag
across both phases — form discovery *and* the 600 s sign-in wait. Covering only
the first phase would have left a second press during SSO still reloading.

**2. A late-rendering username field defeated automatic login.** The refusal said
only "no username field candidate found". The new diagnostics answered it in one
run:

```
[0] type=text placeholder='User' id='usernameLoginInput' NOT-VISIBLE usernameScore=85
[1] type=password placeholder='Enter password' id='passwordLoginInput' visible
```

The field existed and scored 85 — enough for HIGH confidence. It simply was not
visible yet: `find_login_form` returns the instant a *password* field appears, and
on this app the form takes ~18 s to render, so the snapshot caught it half-built.

`analyse_when_ready()` now re-reads and re-analyses while there is something
specific to wait for — an invisible, enabled, strongly-scoring (≥85) username
candidate — for up to 10 s. **The gate is not loosened, only given time:** if the
field never becomes visible the original refusal stands, and the wait ends
immediately when nothing is pending. `FIELDS_JS` also reports *why* an element is
invisible (`NOT-VISIBLE(self display:none)`, `NOT-VISIBLE(div#panel opacity:0)`,
`zero-size 0x0`), which is the difference between "wait" and "give up".

Diagnostics on refusal now list every input's type, label, placeholder,
autocomplete, name, id, testid, visibility with cause, disabled state, form
grouping, and **its username score with the reason** — metadata only; `FIELDS_JS`
never reads a value, asserted by test.

Cover: `test_recovery.py` §7 (6 checks incl. a **control** that clears the
in-progress flag to force the pre-fix path and asserts the reload then *does*
happen — without it the other assertions could pass vacuously) and
`test_login_variants.py` §5–6 via the new `?userlate=N` mock parameter, which
reproduces the PhenomeOne shape exactly: password visible, username still
`display:none`. Both the "appears late" and "never appears" outcomes are pinned.

**Still not validated against the real app:** whether automatic login now
completes there. The mock reproduces the *shape* of the failure; only a real run
proves the fix. Manual Login was never the blocked path and remains the
recommended route for the first real discovery run.

### Phase 12 — Real-application tuning + outcome-driven crawling (2026-08-26)

Driven by the first real discovery run (4 states, 583 elements from
`eksdemo-helm`) and by the `phenome-agronomist-breeder` skill, which documents
PhenomeOne's URL scheme and navigation vocabulary. Both are cited below where
they changed a decision.

**A. Route normalisation for a hash-routed SPA.** PhenomeOne keeps its whole
location in one hash fragment - `#v=1&r=m&p=8.393426.541306&oid=541306~24&otype=24&oname=List`
\- so segment-level id matching never saw the ids. Every record opened minted a
new state, and the record's *name* landed inside the state id
(`...otype-4-oname-test`), which is business data in the map. `normalise_route`
now normalises `key=value` pairs: a 4+ digit run, dotted digits, `123~45`, uuid
or long hex becomes `:id`; a naming parameter (`name`, `oname`, …) becomes
`:name`. Short enums survive, so `otype=4` (Program) and `otype=23` (Study) stay
different states - they *are* different screens, 180 vs 210 elements. Two
Programs now collapse to one `v-1-r-m-otype-4`.

**B. The classifier could not move.** Measured against all 54 documented
PhenomeOne labels: **3 were auto-clickable**. Every tab and sidebar view was
UNKNOWN, so Safe Crawl would explore nothing. Added `_APP_NAV_WORDS` - the
documented tabs, Trial sidebar children, hamburger modules, record-detail tabs -
kept separate from the generic verb list so what is application-specific stays
obvious. Also promoted `calculate`, `define`, `distribute` to destructive: on
the real vocabulary "Calculate variables", "Define germplasm columns" and
"Distribute lots" were UNKNOWN, i.e. safe only by accident. Result: **23
navigation / 30 dangerous / 3 unknown**, with destructive precedence intact
("Delete columns" and "Upload lots - List" stay DANGEROUS).

**C. 38% of the map was layout tables.** 222 of 583 elements were unnamed nested
`<table>`s, every one LOW with a `getByRole('table').nth(11)` locator no test can
use. `isLayoutTable()` skips a table only when it is *dominated by another table*
and has no name, caption, test id, or non-table role - so the outermost data grid
can never be lost. Excluding them, LOW drops from **49% to ~18%**. The remaining
real gap is 55 of 71 textboxes unlabelled: that is the `data-testid` ask for
whoever owns the front end.

**D. "Already signed in" was unreachable.** `APP_MARKERS_JS` required an ARIA
landmark, and PhenomeOne's fully rendered main frame has none - so no amount of
waiting could satisfy it. Widened: landmarks now include grid/tree/toolbar, and a
landmark-free application qualifies on ≥8 controls or ≥5 data rows. **A visible
password field always means not authenticated**, which keeps Safe Crawl's
session-loss detection intact. `looks_authenticated(page, wait_s=0.0)` - the
default is unchanged so the crawler's per-click check keeps its exact timing;
only interactive sign-in passes a budget.

**E. Outcome-driven multi-surface crawling.** The crawler encoded four fixed
rules: a popup was closed on sight, a new tab was refused during a crawl, and
`target=_blank` plus cross-origin were *blocking flags evaluated before the
click*. Any part of an application living in another browsing context was
therefore unreachable by construction - including PhenomeOne's germplasm detail
page, which opens in a new tab.

Replaced with observation. New `crawler/outcomes.py` turns an `Observation` into
a set of facts - `no-change`, `same-surface-new-state`,
`surface-changed-same-state`, `new-surface-in-scope|irrelevant|external|unknown`,
`native-dialog`, `left-origin`, `session-lost`, `unscannable` - with `POISONING`
and `PRODUCTIVE` sets driving behaviour. It touches no browser, so the whole
decision table is unit-tested. New `crawler/surfaces.py` holds `Surface`,
`SurfaceRegistry` and `scope_of()`; a surface records the state and action that
opened it, and in-scope surfaces get a real `parent -> action -> child` edge
tagged `opensSurface`.

Three findings worth keeping:

* **Scope cannot be inferred from the page.** The first design was "same
  registrable domain **and** it looks like an application" - but
  `knowledge-base.phenome-networks.com` renders 12 visible controls, so every
  app-shell heuristic calls a documentation site an application, and it would
  have been crawled. Scope is now origin-based with an explicit `extra_origins`
  allow-list. Both real cases land correctly.
* **The signature could not see visibility.** `domSignature` counts interactive
  nodes whether shown or not (its comment claimed otherwise), so toggling a menu
  changed nothing and `surface-changed-same-state` never fired. Added a separate
  `visibleSignature` rather than touching `domSignature`, which drives the
  timing-sensitive `waitStable`. Measured on the mock: `v=6|s=0` -> `v=11|s=1`.
* **New contexts were credited to the wrong action.** `window.open()` returns
  before Playwright has a Page, so the external popup was consistently attributed
  to the *next* control clicked. Fixed by snapshotting page identities before the
  click plus a bounded 600 ms poll that exits on first appearance - correct by
  construction. This was the flake, 2 runs in 3.

`target=_blank` no longer blocks; **cross-origin deliberately still does** - a
link advertising that it leaves the application offers a crawler nothing, while
an external surface the application produces itself is observed and handled.

**Child surfaces are crawled, not glanced at.** `_crawl_surface` explores within
a child context one level deep, anchored on its landing state: the first
candidate is often a "Back" link, and without returning to the anchor every
remaining candidate vanishes - which made depth inside a child depend on DOM
order. Bounded by `per_surface_actions` (8) and by the global budgets. Three
outcomes on a child are handled explicitly: it is a **sign-in gate** (refused
before any scan, so no credential control ever enters the map), the application
**closes it** underneath us (recorded, parent carries on), or it **navigates out
of scope** (exploration stops there). Guards - native dialogs, downloads - are
installed on the child too and handed back to the parent afterwards.

Deliberate limit: a child surface is not queued for later BFS. Re-reaching it
would mean re-opening the tab by replaying the parent action, and its state may
not survive that; the edge is recorded either way.

**The intended workflow is test-proven.** The user's expectation - "i will login
to the application and after the login the application will work autonomous" -
does not need automatic login at all. `op_crawl` is gated only on having an open
page and no active training, and the GUI's SAFE CRAWL button is disabled only
while training or crawling. `test_multisurface.py` §7 signs in as a human would,
leaves `engine.authenticated` False, and asserts the crawl still explores.

**Known gap, not fixed:** the query string is not part of the state fingerprint
(`normalise_route` takes path + hash). Harmless for PhenomeOne, whose state lives
in the hash, but `?tab=overview` and `?tab=admin` would collide in an application
that routes by query. Changing it means touching fingerprint inputs again.

Two test assertions had to change, both because they encoded removed rules, and
both replaced with the stronger property rather than deleted:
* `test_safety.py` required "target=_blank is never auto-clicked" -> now asserts
  a same-origin blank link **is** clickable while destructive and cross-origin
  ones are still refused;
* `test_redteam.py` required a `popup-closed` incident -> now asserts a popup is
  either explored or disposed of **and** none is left open. Its popup opens a
  same-origin page, so the crawler now *discovers* `outer_frame.html` ("Outer
  widget"), a state the old rule made permanently invisible.

**Retracted:** a predicted Dojo volatile-id problem (`dijit_form_TextBox_0`).
Zero elements in the real map carry an `id` at all, so no id-based locator was
ever generated. No change made.

### Phase 13 — Session-first connect, and what the map was really made of (2026-08-27, v1.5.0)

Driven by real access to PhenomeOne on 2026-08-27. Both the way in and the scan
boundary changed. Every number below is a measurement from that access, dated in
the code where it changed a decision - not a prediction.

**A. CONNECT replaces "guess the login form" as the supported way in.** The
user's framing (2026-08-27): *an authenticated browser session, then an
autonomous full-site crawl*. Reading somebody's login form and typing into it is
a guessing game that a two-step or scripted form wins; a stored Playwright
`storage_state` is deterministic. New `Engine.op_connect(url)`: open the app, try
the stored session, otherwise wait — no form parsing, no typing — until the
application itself becomes reachable, then store the state DPAPI-encrypted and
emit `connected`. `save_session()` and `session_is_valid()` are separate and
public; the latter requires **both** no visible password field in any frame
**and** `looks_authenticated()`, with a 15 s budget because PhenomeOne has taken
up to 38 s to paint after a load.

GUI: **CONNECT** is now the primary button, with a **"then Safe Crawl"** checkbox
(default on) that hands straight over to autonomous exploration when `connected`
arrives; form login is demoted to "Try form login". `remember_session` defaults
to True.

**`op_connect` is GUI-only so far.** The CLI still offers `--manual-login` and
form login, so the CI path cannot use the supported entry point yet - see §4
item 12.

*Bug this fixed:* the stored session was loaded only when a checkbox had been
ticked before launch, and "no login form present **and** I hold a saved session"
was inferred to mean signed in — which is wrong for any page that simply has no
form: a dashboard, an error page, a docs site. It is verified now, never assumed.

**B. The crawl started in the wrong place.** `op_crawl` rooted itself at the URL
in the box. PhenomeOne is hash-routed, so after signing in the location is
`...#v=1&r=m&...&t=Overview`, and navigating back to the bare origin threw that
away: the first real crawl explored a welcome screen whose only content was an
embedded help widget. The crawl now roots where the browser actually **is**, and
logs the location it adopted.

**C. 75 of 80 elements on a screen belonged to somebody else's website.** An
embedded support widget served from `knowledge-base.phenome-networks.com`
contributed **75 of 80** elements on one screen and **75 of 107** on another. All
cross-origin: the crawler can never click them and no generated test can ever
target them, so the map was mostly a third-party help centre with the
application's own controls as a rounding error inside it. `_scannable_frames`
now maps the main frame plus **same-origin** children only (strict
scheme+host+port), and logs what it skipped. Login detection still searches
**every** frame — an identity provider legitimately lives in a cross-origin
iframe. This is the scan-boundary counterpart to Phase 12's origin-based crawl
scope, which had already caught the same host.

**D. "0 safe action(s) of 80 elements" is not a diagnosis.** Two additions, both
running only when a state offered nothing:
* `SafeCrawler._explain_nothing_clickable()` re-classifies the state's rows and
  logs histograms — by frame host, by classification, by the rule that decided —
  plus up to 14 sample elements. Metadata only: names, types, rule names, no
  field values. It has to report at the point of decision: persisted records drop
  `attrs` and keep only part of `link`, so replaying the classifier over the
  stored map gives a different, more permissive answer than the live run.
* `missedClickables(n)` in the injected core reports visible leaf nodes with
  `cursor: pointer` that the harvester did **not** collect, with tag, class,
  role, tabindex and clipped text. This is the probe that found Phase 14.

**E. The GUI could not run a small crawl.** It called `op_crawl()` with no
limits, so it always ran the 250-action default, and the only way to try a
20-action first crawl was the CLI — which needs its own login. There is now a
**max actions** spinbox next to SAFE CRAWL, defaulting to 20.

`test_recovery.py` gained 9 checks over the connect flow: one manual sign-in
reaches authenticated and stores the session, the blob is a Playwright
`storage_state` containing **no password**, a later run opens already
authenticated with no sign-in, and an expired session authenticates nobody and
asks for one more sign-in.

### Phase 14 — Controls with no semantics at all (2026-08-27, v1.6.0)

The probe from Phase 13D answered the question the second real run raised: why
did an entire application screen yield 5 harvested elements, none of them
navigation, so that an autonomous crawl had nothing to click **on any screen**?

Because the PhenomeOne research-group tree — Mine, Tomato, Tomato Demo,
Eggplant, Pepper-ID1533, Sorghum — is dhtmlxTree markup:
`<td class="dhxTextCell standartTreeRow"><span>Tomato</span></td>`. No role, no
`href`, no `tabindex`, no test id. It matched none of the harvester's selectors,
and anything that did reach the classifier was `clickable` with no semantics, so
it was UNKNOWN and therefore never clicked. This is the Phase 12B problem one
layer lower: there the vocabulary could not move, here there was nothing to
classify in the first place.

**Harvest.** `isPointerLeaf(el)` in the injected core accepts a visible, enabled
leaf `DIV/SPAN/TD/LI/P/I/A/B` with a direct label, no nested real control, and a
computed `cursor: pointer` — the signal a design system leaves behind when it
makes something clickable. Cheap tag and child tests run first because reading a
computed style forces layout work and this is evaluated over the whole document.
It takes the **innermost** such node: dhtmlx wraps every row twice, and
harvesting both would make each row's locator match two elements, which the
crawler skips as ambiguous — the tree would have stayed unreachable. `classify()`
consults it **before** a layout role wins, or the row would be reported as a
table cell.

**Corroboration, not a guess.** `leafSignature(el)` (tag + sorted class list) is
stored as `leafSig`, and a pass at the end of `collect()` counts how many
harvested controls share each shape into `leafSiblings`. One pointer-div could be
anything; one row among seven identical rows is a list.

**Classification.** In `safety._classify`, an opaque `clickable` with an own
label and `leafSiblings >= _LIST_SHAPE_MIN` (**3** — the smallest number that
cannot be a coincidence of layout; a two-item menu is better left UNKNOWN) is
SAFE_NAVIGATION under a new `list-shape` rule: *a row in a list navigates, it
does not act*. It is the **last** thing tried. Every veto above it has already
run — a destructive verb in the label, form participation, a POST, cross-origin,
hidden, disabled — so this only decides the leftover case of a labelled row among
peers.

**Corrected by Phase 15B**: this rule also collected every data-grid cell, so
record names and counts entered the map. Read the two together.

New mock page `tests/mock_app/tree.html` reproduces the real dhtmlxTree DOM, and
`test_safety.py` gained 11 checks (105 → 116): every row is discovered, counted,
SAFE_NAVIGATION and auto-clickable with a **unique** text locator; a lone pointer
node stays UNKNOWN; exactly two of a shape is still not a list; a destructive
label stays DANGEROUS however list-shaped; no auto-clickable row carries a
blocking flag.

### Phase 15 — What the first real crawls taught (2026-08-28, v1.7.0)

Two crawls of the real application: 20 actions from the GUI, then 400 actions /
900 s from the CLI reusing the stored session. The first exposed a budget trap,
the second produced an 8.2 MB map of mostly junk. Both are fixed here. Every
number is measured, not predicted.

**A. A crawl budget below `per_state_actions` can never leave the first state.**
The landing screen offers 30 candidates (`per_state_actions`, the default), and
the crawler finishes a state's candidate list before dequeuing the next. With
`--crawl-max-actions 20` it clicked 20 research-group rows and stopped:
`statesVisited: 1`, `limitHit: max_actions`. Nothing was wrong with the crawler -
the budget guaranteed one layer. Raised to 400 actions / 900 s it explored 3
states, found 2 new ones, opened 1 child surface and averaged 11 s per action.

*Operational consequence, not a code change:* a first crawl needs
`max_actions > per_state_actions`, and the GUI still fixes the time budget at
300 s, so a GUI run cannot exceed ~66 actions. §4 item 13 tracks exposing both.

**B. Phase 14 was harvesting the data, not just the tree.** The pointer-leaf rule
that rescued the research-group tree also collected every cell of every data
grid, because a data row is *exactly* what corroboration looks for: many
controls of identical shape, each with its own label. The map filled with
records:

```
clickable::parchita pumkin - gimel g_1001.3 - observation - 2025-09-21
clickable::itay-test - - list - 2023-10-22
clickable::1,241        locator: getByText('1,241', { exact: true })
clickable::5,547
```

Three separate harms: business data in the UI map (safety invariant 6), locators
built from data that break when the data changes, and a crawl budget spent
clicking rows. `isPointerLeaf` now refuses a node whose label **is** a value - a
bare number, a measurement, a date - and a node whose siblings are mostly values,
which catches the word-labelled column ("Approved", "Draft") that the label test
alone cannot see. `safety._looks_like_a_value` is the same rule where it can be
unit-tested without a browser, and it also covers a record read back from a
stored map; it reports a new `value-label` verdict.

*The first version of the sibling rule was wrong and the mock caught it.*
Counting *labelled* siblings vetoed `Mystery control` - an element whose parent
is `<body>`, so its siblings are the whole page - and it would have killed any
flat list of navigation divs, which is the very thing Phase 14 exists to find. A
list of rows has just as many labelled siblings as a row of columns; what differs
is what the text **is**. `tests/mock_app/tree.html` §9 is now a flat sibling list
of names with no table wrapper, asserting navigation survives.

*Accepted cost, stated plainly:* a navigation row named `5.6.1` or `1533` is now
left UNKNOWN and never clicked. The real application has a research group named
`5.6.1`. This is the fail-closed direction and the log names the rule.

**C. 231 of 272 elements in one state were anonymous tables, and the map grew on
every visit.** `isLayoutTable` only dropped a table nested *inside* another
table, but this UI lays each widget out as its own **top-level** table. Those
tables have no name, so their identity fell back to a position -
`table:table:#219` - which shifts between visits: 44 elements became 272 over 19
visits of the same screen, and the deep crawl reached ~1000 elements per state,
8.2 MB, with one scan spending **33 s** in locator validation.

The rule is now "anonymous **and** header-free", wherever the table sits. Column
headers separate a data grid from a layout box, and skipping a table never skips
its contents - every control inside is still harvested on its own merits.

This moved a Phase 12C assertion, deliberately. `test_hardgrid.py` required the
outermost layout table to be recorded, labelled "the data grid is never lost" -
but the element it pinned is a single cell wrapping nested tables, not a grid.
The intent is now held by a stronger test: `hardgrid.html` gained an anonymous
`<table>` **with** `<th>` columns, and both suites assert it survives while the
header-free wrappers do not. 7 tables in the DOM, 3 recorded (named, test-id'd,
and the headed grid).

**D. One screen had two identities.** `p=8.393426.541306&oid=541306~24`
normalised to `:id`, but the research group at `p=8&oid=8` kept its digits,
because the value rule reads 1-3 digits as an enum and 4+ as an id. So 19
research groups collapsed to `v-1-r-m-otype-5` while one minted its own state,
decided by how many digits its record id happened to have. `p` and `oid` are
identifiers by **name** now, not by value length - but only when the value
contains a digit, so `oid=m` ("Mine") stays the structural position it is.
`otype` is untouched: `otype=4` (Program) and `otype=23` (Study) are different
screens and must stay different states.

**E. Measured on the real application**, same budget before and after
(400 actions / 900 s, CLI, stored session):

| | before | after |
|---|---|---|
| elements in the landing state | 1005, growing +12 per visit | **40, unchanged over 31 visits** |
| `ui-map.json` | 8.2 MB, 7 states | **0.18 MB** |
| UNKNOWN skips | 10 291 | **31** |
| worst single validation | 33 s | **1.6 s** |
| seconds per action | 11.2 | **3.4** |
| record names or dates in the map | many | **0** |
| layout-table records | 231 in one state | **0** |

**The remaining limit is candidate selection, not budget.** All 60 clicks of the
post-fix run - 30 from the landing screen, 30 from the research-group screen -
were research-group tree rows, and every one landed on `v-1-r-m-otype-5`. The
tree is global chrome, so every state offers the same 30 rows, and
`per_state_actions` is spent on them before a tab, sidebar item or hamburger
module is ever clicked; the crawl then ended with its queue empty and no limit
hit. Now that identity is correct those 30 rows are **one edge clicked 30 times**.

Phase 8 poisons an *inert* element and limits repeats of the *same* element
across states, but these are 30 distinct elements that do change state - to a
state already known. That case has no rule yet. The fix is an equivalence class
on actions: once two or three controls sharing a `leafSig` have led from this
state to the same target, treat the remaining siblings as the same edge. See §4
item 14.

---

## 3. Test status

Run from the source directory (`python tests/<name>.py`).

Run everything three times from a clean state with:
`python tests/run_all.py --runs 3` (flakiness is reported per suite).

**Last measured 2026-08-28** on the 1.6.0 source: `--runs 1`, **637/637, no
failing and no flaky suite**, 9 min 40 s wall clock. Slowest suites:
`test_crawler.py` 210 s, `test_login_variants.py` 91 s, `test_redteam.py` 84 s.
`test_packaged.py` was **not** re-run - it needs a build, and the build in `dist/`
is older than the 1.6.0 source (see §5).

| Suite | Checks | Covers |
|---|---|---|
| `test_units.py` | 123 | fingerprints incl. **dialog-title normalisation (40)**, locators, store merge, redaction, login analysis, nav tree, report |
| `test_safety.py` | 142 | classifier: unit + live on the hardened mock, incl. the real PhenomeOne vocabulary and the **semantics-free dhtmlxTree rows (11)** |
| `test_crawler.py` | 22 | autonomous crawl, budgets, idempotence, **zero side effects** |
| `test_surfaces.py` | 45 | surface scope + the outcome decision table (no browser) |
| `test_multisurface.py` | 35 | **autonomous crawling across tabs/windows**: menu with no fingerprint change, same-origin tab and popup explored, off-origin closed, parent crawl survives |
| `test_pipeline.py` | 50 | workflows, UI diff, codegen, JUnit, CI exit codes |
| `test_recovery.py` | 32 | the live-environment failures above, incl. the **Manual Login double-press race** and the **CONNECT/stored-session flow (9)** |
| `test_hardgrid.py` | 32 | component-framework UI: portaled combobox, virtualised grid, volatile dialog titles |
| `test_functional.py` | 48 | the functional milestone: full CRUD lifecycle, both fail-closed guards, evidence, cleanup-after-failure, Safe Crawl untouched |
| `test_redteam.py` | 37 | adversarial surface: URL commands, popups, JS downloads, nested iframes, loops, ambiguity, unlabelled controls |
| `test_artifacts.py` | 34 | exact artifact set, schema keys, **generated Python executed against the mock**, leak scan |
| `test_e2e_mock.py` | 30 | login → scan → training → outputs |
| `test_login_variants.py` | 13 | slow form, iframe IdP form, landing page, no form, **late-rendering username field** (appears / never appears) |
| `test_gui_smoke.py` | 21 | real Tk window driving the real browser |
| `test_packaged.py` | 30 | relocated frozen build in a stripped environment |
| **Total** | **699** | 669 source (measured 2026-08-28 on 1.7.0, all green, no flaky suite) + 30 packaged (30/30 on the 1.7.0 build) |

`test_packaged.py` takes a path: `python tests/test_packaged.py <dist>/PhenomeOne-UI-Discovery`.
It **moves** the folder (relocation test), so pass the current location.

### Measured behaviour (mock, headless)
* Scan: `stabilise 264 ms / collect 33 ms / locators 1 ms / validate 825 ms` for
  94 elements over 2 frames. Validation dominates — use `validate_new_only` per hop.
* Crawl: 11 states, 89 navigation paths, 120 clicks, 0 side effects, ~150 s.
* Classifier on the Admin surface: 24 SAFE / 11 CONDITIONAL / 34 DANGEROUS / 25 UNKNOWN.

---

## 4. Remaining work

### Next real-application run (do this first next session)

Real access has happened twice: 2026-08-24 (login only, four bugs) and
2026-08-27, which produced Phases 13 and 14. What is still missing is
**a completed Safe Crawl with artifacts on disk**: no run has yet written a
`crawl-summary.json` or a `ui-map.json` from the real application, so those
findings survive only as code comments and as log reads at the time.

1. ~~Rebuild `dist/`~~ **done 2026-08-28.** The previous build predated the
   1.6.0 commit, so it may not have contained the `list-shape` classifier -
   without which the crawl has nothing to click. Rebuilt from 1.6.0 and verified
   with `test_packaged.py` (30/30) before copying, per §5.
2. **Run it:** CONNECT → leave "then Safe Crawl" ticked → 20 actions → read
   `output/crawl-summary.json` and `logs/discovery.log` before widening. The log
   now explains any state that offered nothing (Phase 13D), so an
   under-exploring crawl is diagnosable without a rerun.
   **There is no stored PhenomeOne session**, so this takes one manual sign-in,
   which CONNECT then stores for every run after it. The `session.bin` that used
   to sit in the build was a *mock* session (one `127.0.0.1` / `p1uidMockAuth`
   cookie) written by `test_packaged.py`, not a real login - it has been removed
   so it cannot be mistaken for one. `config/settings.json` **is** real: it
   carries the URL and username (never a password), and was carried across the
   rebuild.
3. **Keep the artifacts this time.** Copy `output/` and `logs/discovery.log` out
   of `dist/` (both git-ignored, and both empty as of 2026-08-28) so the next
   session can compare instead of re-measuring.
4. **Tune the classifier against the real vocabulary** — still the expected next
   gap. The failure mode is safe (UNKNOWN → not clicked), so expect
   *under*-exploration first. Add real labels to `_DANGEROUS_WORDS` /
   `_NAV_WORDS` / `_APP_NAV_WORDS` in `crawler/safety.py`.
5. **Confirm the long-path limit** on the target workstation (`C:\Tools\` is safe).
6. **Build leftovers** (checked 2026-08-28): the six stale folders this item used
   to list are gone. What remains is
   `C:\Users\itay-b\p1uid-build\relocated-115359` (553 MB) - the copy
   `test_packaged.py` verified and moved, already copied into `dist/`. The next
   `build_portable.py --clean` removes it; delete it sooner if the space matters.

### Portability status (verified 2026-08-25)
Built into `C:\Users\itay-b\QA Build With Spaces\`, verified there (30/30),
then **relocated to a second unrelated path containing spaces, an ampersand and
parentheses** - `C:\Users\itay-b\Another QA Folder (v2) & more\` - and re-run
end to end (login + scan + training + crawl + codegen) in a stripped environment.
Exit 0, every artifact written, no secret leaked.

### Not blocked — next code steps
7. **Crawl performance**: validation is ~9 ms/element and replays cost 1–2 s.
   Options: cache validation per (state, element) across hops; prefer `go_back()`
   more aggressively; parallelise validation.
8. **CONDITIONAL opt-in**: the crawler currently clicks SAFE_NAVIGATION only.
   A `--allow-conditional` flag (dialog openers, expanders in forms) would widen
   coverage; must stay off by default.
9. **Workflow replay**: workflows are recorded but not replayed. `goToState()` in
   the generated `navigation.ts` is the obvious foundation.
10. **`codegen` uses `eval()`** in `goToState()` to turn a stored locator string
   into a Locator. Fine for generated internal helpers, but worth replacing with
   a structured switch over `locatorSpec.args`.
11. **Jenkinsfile** — not written. The CLI + JUnit XML are ready for it.
14. **Action equivalence classes** (Phase 15E, the current ceiling on depth): a
   state offering 30 controls of the same shape that all lead to the same target
   spends its whole budget proving the same edge 30 times. Once 2-3 members of a
   `leafSig` from this state land on the same known state, skip the rest. That
   frees ~27 of 30 candidates per state for the tabs and menus that open new
   screens - which is what "crawl inside a research group" needs.
13. **Expose the crawl budgets** (Phase 15A): the GUI sets only `max_actions`,
   so its runs are silently capped at 300 s (~66 actions), and neither the GUI
   nor the CLI can change `per_state_actions` - which is what makes a budget
   below 30 unable to leave the landing screen. Both belong in the GUI next to
   max actions, and `--crawl-per-state` in the CLI.
12. **`--connect` for the CLI**: `op_connect()` (Phase 13A) is wired to the GUI
   button only. The CLI, which is the CI path, still has `--manual-login` and
   form login. A `--connect` flag reusing the stored session would let Jenkins
   run the whole thing unattended after one human sign-in on the agent.

---

## 5. Build path

**One temp build folder, then copy into `dist/`.** Decided 2026-08-26: a new
`p1uid-<version>` folder per build meant the user's shortcut broke on every
rebuild, and nine abandoned folders had accumulated (4.9 GB, since deleted).
`dist/` is git-ignored in both this project and the repo root, so the copy can
never be committed.

```bat
:: from the source directory
python -m pip install -r requirements.txt
python -m playwright install chromium

:: 1. BUILD into the single reusable temp folder - short path, outside OneDrive
python build_portable.py --clean --out C:\Users\itay-b\p1uid-build

:: 2. VERIFY there (it relocates the folder, so verify before copying)
python tests\test_packaged.py C:\Users\itay-b\p1uid-build\PhenomeOne-UI-Discovery

:: 3. COPY the verified build over the stable location the user launches
robocopy C:\Users\itay-b\p1uid-build\relocated-*\PhenomeOne-UI-Discovery ^
         dist\PhenomeOne-UI-Discovery /E /PURGE /MT:8
```

Wipe `output/ reports/ logs/` from the copy afterwards - the packaged test fills
them with mock-app data, and handing that over looks like a real run.

**And delete `sessions/session.bin`.** The packaged test signs into the mock, so
the build ships a DPAPI session holding a `127.0.0.1` / `p1uidMockAuth` cookie.
It is harmless but it makes `sessions.exists()` true, so CONNECT announces a
stored session it cannot use, and anyone reading the folder assumes a real login
is saved. `config/settings.json` (URL + username, never a password) is worth
carrying across a rebuild; the session is not.

**Build in the temp folder, never directly into `dist/`.** PyInstaller writing
579 MB inside a OneDrive-synced tree invites file locks mid-write and a corrupt
distribution; copying a finished tree in is safe. The deep OneDrive path also
eats into the 260-character limit that Chromium's nested files can hit.

The user launches:
`dist\PhenomeOne-UI-Discovery\PhenomeOne-UI-Discovery.exe`

### Gotchas that cost time before
* PyInstaller spec lists `hiddenimports` explicitly — **add any new module there**.
* Bash-heredoc patching mangles `\b`, `\n`, `\s` into control characters. After
  scripted edits, run:
  `python -c "import pathlib;[print(f) for f in pathlib.Path('src').rglob('*.py') if any(bytes([b]) in f.read_bytes() for b in range(32) if b not in (9,10,13))]"`
* Only `getByRole` ignores CSS-hidden elements — hence `deferred-hidden`/MEDIUM.
* Headless needs `channel="chromium"`, else Playwright wants the 270 MB shell.
* `is_visible()`/`is_enabled()` need explicit short timeouts.
* The mock keeps a session in `sessionStorage`; tests that expect a login form
  must clear it first (`reset_session()` in `test_login_variants.py`).

---

## 6. Layout

```
src/p1uid/
  app.py                 CLI/GUI entry, exit codes, CI gate
  paths.py               portable paths (P1UID_HOME override for tests)
  logging_setup.py       logging + secret redaction
  browser/controller.py  Engine: asyncio loop in a thread, all ops
  browser/injected.py    CORE_JS: analysis, observation, waitStable
  auth/login.py          frame-aware, confidence-gated login
  discovery/scanner.py   collect → locators → validate → merge
  discovery/stability.py wait_stable()
  crawler/safety.py      action classification
  crawler/bfs.py         Safe Crawl
  crawler/outcomes.py    observation -> facts (no browser, fully unit-tested)
  crawler/surfaces.py    Surface, SurfaceRegistry, scope_of()
  locator/               generator + validator
  state/fingerprint.py   UI-state identity
  store/uimap.py         incremental map
  navigation/graph.py    graph + readable tree
  training/trainer.py    action↔state correlation
  training/workflows.py  named workflow recording
  functional/           declarative steps, runner, test data, evidence, results
  reporting/html_report.py, reporting/junit.py, reporting/junit_functional.py
  diff.py, codegen.py
  security/dpapi.py, security/session_store.py
  gui/main_window.py

tests/                   14 source suites + test_packaged.py + run_all.py
tests/mock_app/          12 pages incl. redteam.html, hardgrid.html, tree.html
tests/functional/        declarative CRUD test definitions (JSON)
samples/                 real output from the mock (report, map, graph, generated TS)
```

Outputs land next to the exe: `output/` (ui-map, navigation-graph, application,
training-summary, crawl-summary, workflows, ui-diff, generated/), `reports/`
(discovery-report.html, ui-diff.html, junit-discovery.xml), `logs/`.

---

## 7. Safety invariants (do not regress)

1. `auto_clickable` is **only** true for SAFE_NAVIGATION with no blocking flag,
   and is forced false for DANGEROUS and UNKNOWN.
1a. A destructive verb in a **URL command parameter** outranks the link text:
   `?action=delete` is DANGEROUS however the link is labelled.
2. The crawler clicks nothing else, ever.
3. Native dialogs are always dismissed, never accepted.
4. Downloads are refused at the browser-context level.
5. The password is memory-only; sessions are DPAPI-encrypted; logs are redacted.
6. No business data is persisted — grids store column names + row count only.
7. Training observes; it never clicks.
8. A control with **no semantics** is auto-clickable only with corroboration:
   `clickable` + its own label + at least 3 same-shaped peers on the page, and
   only after every veto in (1) has already run. A lone pointer node, or two of
   a shape, stays UNKNOWN. (Phase 14.)
9. Cross-origin frames are never mapped and never crawled. **Login detection is
   the one exception** and still reads every frame, because an identity provider
   legitimately lives in a cross-origin iframe. (Phase 13C.)
10. Authentication never guesses: `session_is_valid()` requires no visible
   password field **and** the application rendering. A visible password field
   always means not authenticated. (Phase 13A.)
11. **A value is not a control.** A semantics-free node whose label is a number,
   a measurement or a date - or whose siblings are mostly such values - is never
   harvested and never clicked. This is what keeps business data out of the map
   and stops locators being built from data (`getByText('1,241')`). Enforced
   twice: `isValueLabel` in the harvester, `_looks_like_a_value` in the
   classifier. (Phase 15B.)

`test_crawler.py` asserts (1)–(4) against a mock that records every side effect
it would have suffered. Keep that test green.
