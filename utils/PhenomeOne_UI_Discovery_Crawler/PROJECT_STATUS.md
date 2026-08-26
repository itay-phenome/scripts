# PROJECT STATUS — PhenomeOne UI Discovery

**Handoff document. Read this first in a new session.**

| | |
|---|---|
| Last updated | 2026-08-26 |
| Version | 1.3.2 (discovery + autonomous crawl + functional QA engine + normalised dialog-state identity + **login-timing fixes from the real app**) |
| Source | `scripts/utils/PhenomeOne_UI_Discovery_Crawler/` on `main` of `github.com/itay-phenome/scripts` (pushed) |
| Build output | `dist\PhenomeOne-UI-Discovery\` in this repo (555 MB, v1.3.2, git-ignored) — built in `C:\Users\itay-b\p1uid-build`, then copied. See §5 |
| Executables | `PhenomeOne-UI-Discovery.exe` (GUI), `PhenomeOne-UI-Discovery-cli.exe` (CI) |
| Tests | **530/530 passing** — 500 source (12 suites) + 30 packaged |
| Blocked on | **EKS-LAB / real PhenomeOne validation — no credentials in this session** |
| First real run | 2026-08-24 against `eksdemo-helm.phenome-networks.com`: exposed 4 bugs, all fixed (see §2.7) |

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
  refused at context level (`accept_downloads=False`); popups closed;
  off-origin navigation reverted + poisoned; **session loss aborts the crawl**.
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

---

## 3. Test status

Run from the source directory (`python tests/<name>.py`).

Run everything three times from a clean state with:
`python tests/run_all.py --runs 3` (flakiness is reported per suite).

| Suite | Checks | Covers |
|---|---|---|
| `test_units.py` | 95 | fingerprints incl. **dialog-title normalisation (40)**, locators, store merge, redaction, login analysis, nav tree, report |
| `test_safety.py` | 103 | classifier: 69 unit + 34 live on the hardened mock |
| `test_crawler.py` | 22 | autonomous crawl, budgets, idempotence, **zero side effects** |
| `test_pipeline.py` | 50 | workflows, UI diff, codegen, JUnit, CI exit codes |
| `test_recovery.py` | 23 | the live-environment failures above, incl. the **Manual Login double-press race** |
| `test_hardgrid.py` | 25 | component-framework UI: portaled combobox, virtualised grid, volatile dialog titles |
| `test_functional.py` | 48 | the functional milestone: full CRUD lifecycle, both fail-closed guards, evidence, cleanup-after-failure, Safe Crawl untouched |
| `test_redteam.py` | 36 | adversarial surface: URL commands, popups, JS downloads, nested iframes, loops, ambiguity, unlabelled controls |
| `test_artifacts.py` | 34 | exact artifact set, schema keys, **generated Python executed against the mock**, leak scan |
| `test_e2e_mock.py` | 30 | login → scan → training → outputs |
| `test_login_variants.py` | 13 | slow form, iframe IdP form, landing page, no form, **late-rendering username field** (appears / never appears) |
| `test_gui_smoke.py` | 21 | real Tk window driving the real browser |
| `test_packaged.py` | 30 | relocated frozen build in a stripped environment |
| **Total** | **530** | 500 source + 30 packaged, all passing as of this update |

`test_packaged.py` takes a path: `python tests/test_packaged.py <dist>/PhenomeOne-UI-Discovery`.
It **moves** the folder (relocation test), so pass the current location.

### Measured behaviour (mock, headless)
* Scan: `stabilise 264 ms / collect 33 ms / locators 1 ms / validate 825 ms` for
  94 elements over 2 frames. Validation dominates — use `validate_new_only` per hop.
* Crawl: 11 states, 89 navigation paths, 120 clicks, 0 side effects, ~150 s.
* Classifier on the Admin surface: 24 SAFE / 11 CONDITIONAL / 34 DANGEROUS / 25 UNKNOWN.

---

## 4. Remaining work

### Blocked — needs real access (do this first next session)
1. **EKS-LAB / PhenomeOne validation.** Still the main gap: only the login path
   has ever touched the real app (one run, 2026-08-24), and it found four bugs
   within 30 seconds - expect more. Needed: a URL + credentials for a
   **non-production** instance. Then:
   * `PhenomeOne-UI-Discovery.exe` → LOGIN (or Manual Login) → SCAN → TRAINING.
   * Check `logs/discovery.log` for the login diagnostics block if login fails.
   * Only after a clean manual pass, try **SAFE CRAWL** with a small budget
     (`--crawl-max-actions 20`) and read `crawl-summary.json` before widening.
2. **Tune the classifier against the real vocabulary.** PhenomeOne will have verbs
   the word lists do not know. The failure mode is safe (UNKNOWN → not clicked),
   so expect *under*-exploration first. Add real labels to
   `_DANGEROUS_WORDS` / `_NAV_WORDS` in `crawler/safety.py`.
3. **Confirm the long-path limit** on the target workstation (`C:\Tools\` is safe).
4. **Stale build folders on this machine** (~2.2 GB) — `p1uid-build` (broken, no
   exe), `p1uid-build-v2` (v1.0.0), `p1uid-final` (v1.1.0), `p1uid-final2`
   (v1.1.1), `QA Build With Spaces` (empty) and `Another QA Folder (v2) & more`
   (portability-test copy) are all superseded by **`p1uid-final3`**. Deleting
   them avoids clicking a dead folder and frees ~2.2 GB.

### Portability status (verified 2026-08-25)
Built into `C:\Users\itay-b\QA Build With Spaces\`, verified there (30/30),
then **relocated to a second unrelated path containing spaces, an ampersand and
parentheses** - `C:\Users\itay-b\Another QA Folder (v2) & more\` - and re-run
end to end (login + scan + training + crawl + codegen) in a stripped environment.
Exit 0, every artifact written, no secret leaked.

### Not blocked — next code steps
5. **Crawl performance**: validation is ~9 ms/element and replays cost 1–2 s.
   Options: cache validation per (state, element) across hops; prefer `go_back()`
   more aggressively; parallelise validation.
6. **CONDITIONAL opt-in**: the crawler currently clicks SAFE_NAVIGATION only.
   A `--allow-conditional` flag (dialog openers, expanders in forms) would widen
   coverage; must stay off by default.
7. **Workflow replay**: workflows are recorded but not replayed. `goToState()` in
   the generated `navigation.ts` is the obvious foundation.
8. **`codegen` uses `eval()`** in `goToState()` to turn a stored locator string
   into a Locator. Fine for generated internal helpers, but worth replacing with
   a structured switch over `locatorSpec.args`.
9. **Jenkinsfile** — not written. The CLI + JUnit XML are ready for it.
10. **GUI crawl budget controls** — currently uses defaults; the CLI exposes them.

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
  locator/               generator + validator
  state/fingerprint.py   UI-state identity
  store/uimap.py         incremental map
  navigation/graph.py    graph + readable tree
  training/trainer.py    action↔state correlation
  training/workflows.py  named workflow recording
  reporting/html_report.py, reporting/junit.py
  diff.py, codegen.py
  security/dpapi.py, security/session_store.py
  gui/main_window.py

tests/                   7 source suites + test_packaged.py + mock_app/
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

`test_crawler.py` asserts (1)–(4) against a mock that records every side effect
it would have suffered. Keep that test green.
