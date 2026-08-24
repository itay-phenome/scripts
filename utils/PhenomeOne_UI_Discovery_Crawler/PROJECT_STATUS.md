# PROJECT STATUS — PhenomeOne UI Discovery

**Handoff document. Read this first in a new session.**

| | |
|---|---|
| Last updated | 2026-08-24 |
| Version | 1.1.2 (V1 + autonomous discovery + live hardening + QA/red-team pass) |
| Source | `scripts/utils/PhenomeOne_UI_Discovery_Crawler/` (uncommitted, nothing pushed) |
| Build output | `C:\Users\itay-b\p1uid-final2\PhenomeOne-UI-Discovery\` (555 MB) |
| Executables | `PhenomeOne-UI-Discovery.exe` (GUI), `PhenomeOne-UI-Discovery-cli.exe` (CI) |
| Tests | **395/395 passing** — 365 source (10 suites) + 30 packaged |
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
| 5 | Low (self-inflicted) | Scripted edits silently mangled ``, `
` and `\s` into control bytes, once disabling a live regex rule. | Every scripted edit is followed by a control-byte scan of `src/` (command in §5). |

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

---

## 3. Test status

Run from the source directory (`python tests/<name>.py`).

Run everything three times from a clean state with:
`python tests/run_all.py --runs 3` (flakiness is reported per suite).

| Suite | Checks | Covers |
|---|---|---|
| `test_units.py` | 47 | fingerprints, locators, store merge, redaction, login analysis, nav tree, report |
| `test_safety.py` | 103 | classifier: 69 unit + 34 live on the hardened mock |
| `test_crawler.py` | 22 | autonomous crawl, budgets, idempotence, **zero side effects** |
| `test_pipeline.py` | 50 | workflows, UI diff, codegen, JUnit, CI exit codes |
| `test_recovery.py` | 15 | the four live-environment failures above |
| `test_redteam.py` | 35 | adversarial surface: URL commands, popups, JS downloads, nested iframes, loops, ambiguity, unlabelled controls |
| `test_artifacts.py` | 34 | exact artifact set, schema keys, **generated Python executed against the mock**, leak scan |
| `test_e2e_mock.py` | 30 | login → scan → training → outputs |
| `test_login_variants.py` | 8 | slow form, iframe IdP form, landing page, no form |
| `test_gui_smoke.py` | 21 | real Tk window driving the real browser |
| `test_packaged.py` | 30 | relocated frozen build in a stripped environment |
| **Total** | **326** | all passing as of this update |

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
4. **Stale build folders on this machine** — `C:\Users\itay-b\p1uid-build`
   (broken, no exe), `p1uid-build-v2` (v1.0.0) and `p1uid-final` (v1.1.0) are all
   superseded by `p1uid-final2`. Delete the first three to avoid clicking a dead
   folder.

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

```bat
:: from the source directory
python -m pip install -r requirements.txt
python -m playwright install chromium

:: build OUTSIDE OneDrive and keep the path short (Chromium + 260-char limit)
python build_portable.py --clean --out C:\Users\itay-b\p1uid-next
python tests\test_packaged.py C:\Users\itay-b\p1uid-next\PhenomeOne-UI-Discovery
```

The packaged test relocates the folder and leaves it at
`<out>\relocated-<HHMMSS>\PhenomeOne-UI-Discovery`; move it back and wipe
`output/ reports/ logs/ config/ sessions/` before handing it over.

**Do not build into the OneDrive-synced repo** — 579 MB would sync, and the deep
path can stop Chromium from launching.

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
