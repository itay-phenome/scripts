# PROJECT STATUS — PhenomeOne UI Discovery

**Handoff document. Read this first in a new session.**

| | |
|---|---|
| Last updated | 2026-08-24 |
| Version | 1.1.0 (V1 + autonomous discovery) |
| Source | `scripts/utils/PhenomeOne_UI_Discovery_Crawler/` (uncommitted, nothing pushed) |
| Build output | `C:\Users\itay-b\p1uid-final\PhenomeOne-UI-Discovery\` (555 MB) |
| Executables | `PhenomeOne-UI-Discovery.exe` (GUI), `PhenomeOne-UI-Discovery-cli.exe` (CI) |
| Tests | **311/311 passing** — 281 source + 30 packaged |
| Blocked on | **EKS-LAB / real PhenomeOne validation — no credentials in this session** |

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

---

## 3. Test status

Run from the source directory (`python tests/<name>.py`).

| Suite | Checks | Covers |
|---|---|---|
| `test_units.py` | 47 | fingerprints, locators, store merge, redaction, login analysis, nav tree, report |
| `test_safety.py` | 103 | classifier: 69 unit + 34 live on the hardened mock |
| `test_crawler.py` | 22 | autonomous crawl, budgets, idempotence, **zero side effects** |
| `test_pipeline.py` | 50 | workflows, UI diff, codegen, JUnit, CI exit codes |
| `test_e2e_mock.py` | 30 | login → scan → training → outputs |
| `test_login_variants.py` | 8 | slow form, iframe IdP form, landing page, no form |
| `test_gui_smoke.py` | 21 | real Tk window driving the real browser |
| `test_packaged.py` | 30 | relocated frozen build in a stripped environment |
| **Total** | **311** | all passing as of this update |

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
1. **EKS-LAB / PhenomeOne validation.** Everything above is verified against
   `tests/mock_app` only. Needed: a URL + credentials for a **non-production**
   instance. Then:
   * `PhenomeOne-UI-Discovery.exe` → LOGIN (or Manual Login) → SCAN → TRAINING.
   * Check `logs/discovery.log` for the login diagnostics block if login fails.
   * Only after a clean manual pass, try **SAFE CRAWL** with a small budget
     (`--crawl-max-actions 20`) and read `crawl-summary.json` before widening.
2. **Tune the classifier against the real vocabulary.** PhenomeOne will have verbs
   the word lists do not know. The failure mode is safe (UNKNOWN → not clicked),
   so expect *under*-exploration first. Add real labels to
   `_DANGEROUS_WORDS` / `_NAV_WORDS` in `crawler/safety.py`.
3. **Confirm the long-path limit** on the target workstation (`C:\Tools\` is safe).

### Not blocked — next code steps
4. **Crawl performance**: validation is ~9 ms/element and replays cost 1–2 s.
   Options: cache validation per (state, element) across hops; prefer `go_back()`
   more aggressively; parallelise validation.
5. **CONDITIONAL opt-in**: the crawler currently clicks SAFE_NAVIGATION only.
   A `--allow-conditional` flag (dialog openers, expanders in forms) would widen
   coverage; must stay off by default.
6. **Workflow replay**: workflows are recorded but not replayed. `goToState()` in
   the generated `navigation.ts` is the obvious foundation.
7. **`codegen` uses `eval()`** in `goToState()` to turn a stored locator string
   into a Locator. Fine for generated internal helpers, but worth replacing with
   a structured switch over `locatorSpec.args`.
8. **Jenkinsfile** — not written. The CLI + JUnit XML are ready for it.
9. **GUI crawl budget controls** — currently uses defaults; the CLI exposes them.

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
2. The crawler clicks nothing else, ever.
3. Native dialogs are always dismissed, never accepted.
4. Downloads are refused at the browser-context level.
5. The password is memory-only; sessions are DPAPI-encrypted; logs are redacted.
6. No business data is persisted — grids store column names + row count only.
7. Training observes; it never clicks.

`test_crawler.py` asserts (1)–(4) against a mock that records every side effect
it would have suffered. Keep that test green.
