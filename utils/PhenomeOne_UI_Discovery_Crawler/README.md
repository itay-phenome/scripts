# PhenomeOne UI Discovery

> **Session handoff:** see [`PROJECT_STATUS.md`](PROJECT_STATUS.md) for what is
> done, what is tested, what is left, and the build path.

A portable Windows tool that learns the PhenomeOne web UI and writes it out as a
deterministic, reusable **UI knowledge layer** for Playwright/Jenkins tests.

The point is to stop paying an LLM to hunt for buttons at test time:

```
PhenomeOne -> Playwright -> deterministic discovery engine -> UI map / navigation graph -> tests
```

**No Claude, no LLM and no API call is involved when the tool runs.** Discovery
is plain DOM + ARIA analysis and Playwright locator validation.

---

## Quick start (portable build)

1. Copy the `PhenomeOne-UI-Discovery` folder anywhere — `C:\Tools\`, a USB stick,
   another workstation. Keep the path reasonably short (see *Known limitations*).
2. Run `PhenomeOne-UI-Discovery.exe`.
3. Enter the URL and press **CONNECT**. A session stored earlier is reused and
   verified; otherwise sign in once in the browser window yourself and it is
   saved for next time. Leave **then Safe Crawl** ticked and the tool hands
   straight over to autonomous exploration once you are in (budget: the **max
   actions** box, default 20). **Try form login** and **Manual Login** remain for
   the older flows.
4. **SCAN CURRENT PAGE** analyses the screen you are looking at.
5. **START TRAINING**, then just use PhenomeOne normally. Every screen, tab,
   dialog and menu you visit is learned. **STOP TRAINING** writes everything out.

The target machine needs **nothing** installed: no Python, Node.js, npm,
Playwright, Chromium, Chrome/Edge, Docker or WSL.

## Command line (CI / Jenkins)

```bat
set P1UID_PASSWORD=...
PhenomeOne-UI-Discovery-cli.exe --cli --url https://phenomeone.example.com ^
    --user qa@example.com --headless --remember
```

A password is never accepted as a command-line argument. It comes from
`P1UID_PASSWORD` or an interactive prompt.

| Flag | Meaning |
|---|---|
| `--cli` | no GUI |
| `--url` | PhenomeOne URL |
| `--user` | username (password from `$P1UID_PASSWORD`) |
| `--manual-login` | authenticate by hand in the browser |
| `--train-seconds N` | observe for N seconds while somebody drives the app |
| `--headless` | run Chromium headless |
| `--remember` | save/reuse the authenticated session (DPAPI-encrypted) |
| `--validate-limit N` | cap locator validations per scan (default 500) |
| `--report-only` | regenerate reports from the existing map |
| `--crawl` | Safe Crawl after login (read-only navigation only) |
| `--crawl-max-states/-actions/-depth/--crawl-seconds` | crawl budgets |
| `--workflow NAME` | record the training session as a named workflow |
| `--generate-tests` | emit Playwright assets into `output/generated/` |
| `--diff BASELINE CURRENT` | diff two UI maps and exit |
| `--fail-on-low N` | CI gate: exit 4 above N LOW locators |
| `--debug` | verbose logging |

---

## Output

```
output\ui-map.json             every UI state, element, and validated locator
output\navigation-graph.json   state -> action -> state graph, plus a readable tree
output\application.json        environments and totals
output\training-summary.json   last training session (timeline, timings)
reports\discovery-report.html  human-readable report
logs\discovery.log             diagnostics (never contains secrets)
```

### ui-map.json shape

```jsonc
{
  "schemaVersion": 1,
  "application": { "environments": [ { "origin": "...", "firstSeen": "...", "timesSeen": 3 } ] },
  "states": {
    "research-group-germplasms": {
      "fingerprint": "40b23819dce1",     // identity: stable across sessions & records
      "label": "Research Group ABC > Germplasms",
      "route": "/research-group/:id",    // record ids normalised away
      // dialog titles are normalised before hashing: "Edit INV-0001" -> "Edit :id",
      // so one state covers the edit dialog for every record (see ARCHITECTURE.md)
      "signals": { "activeTab": "Germplasms", "tabs": [...], "dialogs": [], "landmarkRoles": [...] },
      "firstSeen": "...", "lastSeen": "...", "timesSeen": 14,
      "environmentsSeen": ["https://..."],
      "elements": {
        "tab:tab:germplasms": {
          "logicalName": "Germplasms Tab",
          "type": "tab", "role": "tab", "name": "Germplasms",
          "visible": true, "enabled": true,
          "timesSeen": 14, "confidence": "HIGH",
          "locator": {
            "strategy": "role", "tier": 2,
            "js":     "getByRole('tab', { name: 'Germplasms', exact: true })",
            "python": "get_by_role(\"tab\", name=\"Germplasms\", exact=True)",
            "args":   { "role": "tab", "name": "Germplasms", "exact": true },
            "matches": 1, "unique": true, "validation": "live", "confidence": "HIGH"
          },
          "alternatives": [ { "strategy": "text", "js": "getByText('Germplasms', ...)", ... } ],
          "locatorHistory": [ { "js": "...", "timesSeen": 14, "firstSeen": "...", "lastSeen": "..." } ]
        }
      }
    }
  },
  "navigation": {
    "research-group-overview|tab:Germplasms|research-group-germplasms": {
      "from": "research-group-overview",
      "action": { "type": "tab", "name": "Germplasms",
                  "locator": "getByRole('tab', { name: 'Germplasms', exact: true })" },
      "to": "research-group-germplasms",
      "timesSeen": 6
    }
  }
}
```

Consumers should slice by state (`states["<id>"].elements`) rather than loading
the whole map — one state is a few KB, the full map for a large app is hundreds.

`samples\` holds real output from the mock app so you can see the shape before
running against PhenomeOne: `discovery-report.sample.html`,
`navigation-graph.sample.json`, and `ui-map.sample.json` (one state).

### Locator quality

| Confidence | Meaning |
|---|---|
| `HIGH` | Playwright resolved it to exactly **one** element, via test id, role+name, or label. |
| `MEDIUM` | Resolved uniquely but through a weaker signal (attribute/text/id), **or** the element was hidden at scan time so Playwright could not confirm it (`validation: "deferred-hidden"` — role locators intentionally ignore hidden elements). |
| `LOW` | Ambiguous (`matches > 1`), unmatched, or positional. These carry a `recommendation` naming a `data-testid` to add. |

`flags: ["UNSTABLE LOCATOR"]` marks an element whose preferred locator keeps
changing between runs — a signal that the app needs a stable test id there.

Generated locators never use XPath, `nth-child` chains, absolute DOM paths, or
framework-generated class names / volatile ids (`mat-input-4821`, `:r3:`, …).

---

## Security

* The password lives **in memory only**. It is never written to JSON, YAML, INI,
  logs, reports, UI maps, or command-line arguments, and never appears in
  `config\settings.json` (URL + username + flags only).
* “Remember session” stores the Playwright `storage_state`
  (cookies/localStorage) — **not** the password — in `sessions\session.bin`,
  encrypted with **Windows DPAPI** under your user account. Copy it to another
  machine and it is useless. If DPAPI is unavailable the session is simply not
  saved (fail closed). **Clear Saved Session** shreds and deletes it.
* The log pipeline has a redaction filter: registered secrets plus
  `password=`, `Cookie:`, `Authorization: Bearer …` patterns are replaced with
  `***REDACTED***` before anything is written.
* Field **values are never read** from the page. Password inputs are reduced to
  metadata. Grids are captured as column names + row count, never row contents.
* Training is **observation only**. The tool never clicks anything in
  PhenomeOne — no Save, Delete, Submit, Import or Confirm is ever triggered.

## Performance

Typical mock-app numbers (Chromium headless, ~300 elements/state):

| Phase | Time |
|---|---|
| DOM + ARIA collect (whole page, 1 round trip) | 8–15 ms |
| Locator generation | < 2 ms |
| Locator validation (~40 elements) | 150–400 ms |
| Map merge | < 2 ms |
| **Full scan** | **~0.2–0.5 s** |

Discovery is one `evaluate()` per frame, not one round trip per element.
Training debounces and coalesces change events, keeps a minimum interval between
scans, and reuses previous validation results for unchanged elements, so
revisiting a known screen costs a collect + merge. Timings are logged per scan
and shown in the GUI.

---

## Development

```bat
python -m pip install -r requirements.txt
python -m playwright install chromium

python main.py                       :: GUI from source
python tests\test_units.py           :: 47 unit checks, no browser
python tests\test_e2e_mock.py        :: 30 end-to-end checks against a mock SPA
python tests\test_gui_smoke.py       :: 21 checks driving the real Tk window
python build_portable.py --clean --out C:\Users\me\p1uid-build
python tests\test_packaged.py C:\Users\me\p1uid-build\PhenomeOne-UI-Discovery
```

`tests\mock_app\index.html` is a small PhenomeOne-shaped SPA (login, tabs that do
**not** change the URL, a modal, a grid, a tree, a menu, duplicate button
labels, a volatile id) used by the automated tests. Set `P1UID_HOME` to redirect
config/output/logs somewhere other than next to the executable.

See `ARCHITECTURE.md` for the module map and design decisions.

## Known limitations

* **Long paths.** Chromium will not start if the package sits so deep that its
  own files exceed the Windows 260-character path limit. The app warns when the
  folder path is over 150 characters. Keep it near a drive root.
* **Headless uses `channel="chromium"`** (new headless mode of the full browser)
  so the 270 MB `chromium_headless_shell` download does not have to ship. The
  package is ~578 MB as a result rather than ~850 MB.
* Cross-origin iframes are scanned (up to 6 frames per page) but the page
  *structure*/fingerprint comes from the main frame only.
* `ui-map.json` grows with coverage (~1.4 KB per element). Slice per state.
* Element identity for unnamed, attribute-less controls falls back to DOM order,
  so heavy reordering of anonymous elements can look like new elements.
* Login detection waits up to 20 s and searches **every frame** (the form often
  renders late or sits in an identity-provider iframe), and will click a single
  unambiguous "Sign in" entry point on a landing page. It still refuses to type
  anything when the form cannot be identified confidently — e.g. multi-step
  flows or a redirect to an external IdP. Use **Manual Login** for those; the
  log prints the page structure so you can see what it found.
* Verified against the real PhenomeOne twice — 2026-08-24 (login) and 2026-08-27
  (connect + scan), both of which changed the product. A full Safe Crawl on the
  real application has **not** been completed yet, and every automated suite runs
  against the bundled mock SPA.

## Autonomous discovery (Safe Crawl)

Press **SAFE CRAWL** (or `--crawl`) and the tool explores the application by
itself, clicking **only** controls classified as read-only navigation, and
records what it finds into the same UI map.

* `p1uid.discovery.stability.wait_stable()` - "has the UI finished reacting?",
  driven by mutations plus the structural signature. No fixed sleeps, and
  deliberately not `networkidle` (an app that polls never reaches it).
* Element records carry what a classifier needs: `inputType`, `buttonType` /
  `effectiveButtonType`, `inForm`, `form` (identity/method/action), `link`
  (scheme/origin/download/target), `hasPopup`, `iconOnly`, and structural
  `context` (dialog/toolbar/grid/menu/landmark/row).
* `p1uid.crawler.safety.classify()` - returns `SAFE_NAVIGATION`, `CONDITIONAL`,
  `DANGEROUS` or `UNKNOWN` plus reasons and flags. A crawler may click **only**
  verdicts with `auto_clickable == True`, which is impossible for DANGEROUS and
  UNKNOWN by construction.

Blocked outright: Delete, Remove, Save, Submit, Import, Execute, Archive,
Publish, Approve, Reject, Reset, Send, Logout/Sign out (and ~90 more verbs),
anything that submits or resets a form, POST triggers, downloads, `mailto:`,
`javascript:`, `blob:`, `data:`, non-http schemes, cross-origin navigation, and
`target=_blank`.

**Structure outranks labels.** A button captioned "Go" that implicitly submits a
POST form is DANGEROUS. So is a link captioned "Open record" whose href is
`?action=delete&id=7` - a destructive verb in a command parameter
(`action`/`op`/`do`/`cmd`/`method`/`task`) is read as a command, not decoration.
Benign queries (`?tab=overview&sort=name&page=3`) still navigate.

**Known limitation:** a control whose accessible name misdescribes what it does
("View report" that deletes) cannot be classified from the DOM alone. Crawl
non-production environments.

Guards, all test-asserted: native dialogs are always dismissed and the action
that raised one is never retried; downloads are refused at the browser-context
level; popups are closed; off-origin navigation is reverted; losing the session
aborts the crawl. Budgets bound states, actions, depth, per-state actions and
wall-clock time.

## Workflow recording

During training, name a sequence and bracket it with **Record Workflow** /
**Stop Workflow** (or `--workflow NAME`). Steps are merged into
`output/workflows.json` with the locator for each step. Field values are never
captured.

## UI diff between revisions

    PhenomeOne-UI-Discovery-cli.exe --diff baseline/ui-map.json output/ui-map.json

Prints `+ - ~` lines, writes `output/ui-diff.json` and `reports/ui-diff.html`
(with a "test-breaking locator changes" table), and exits **5** when anything
changed - so a CI job can gate on UI drift.

## Test generation

`--generate-tests` writes `output/generated/`:

| File | Contents |
|---|---|
| `ui-map.ts` | typed Playwright locators per UI state |
| `navigation.ts` | `NAV_STEPS` + `goToState(page, state)` from the learned graph |
| `smoke.spec.ts` | one Playwright test per state asserting its controls |
| `ui_map.py` | the same locators as playwright-python page objects |
| `README.md` | every element that was skipped and the `data-testid` to add |

Only validated HIGH/MEDIUM locators are emitted; LOW ones appear as `// SKIPPED`
with the recommendation, so nobody inherits a flaky test.

## Functional tests (Phase 1)

Discovery answers "what is in this UI?". Functional tests answer "does it still
work?". A test is **data**, not code - a list of steps the runner executes
against the live app, using the locators discovery already validated:

    navigate  go to a discovered UI state, via the learned navigation graph
    click     activate a control
    fill      type into a field
    select    choose an option
    assert    check visible / hidden / count / textContains / state

```bat
PhenomeOne-UI-Discovery-cli.exe --cli --url %URL% --user %USER% --headless ^
    --run-tests tests/functional/germplasm_crud.json --test-level critical
```

Discovery must have run first: targets and routes come from `output/ui-map.json`
and the navigation graph. A test never hard-codes a route.

### Writing a destructive test

Creating, changing or deleting data requires `"destructive": true` on the step.
The runner then **fails closed** and refuses to click unless:

1. the current UI state equals the step's declared `state`,
2. the target resolves to exactly **one** element, and
3. that element is visible and enabled.

Safe Crawl is unaffected and remains read-only: it never performs these actions.
A specific grid row is addressed by scoping, not by index:

```jsonc
{ "action": "click", "destructive": true, "state": "research-group-germplasms",
  "target": { "role": "button", "name": "Delete",
              "within": { "role": "row", "name": "{record}", "exact": false } } }
```

### Test data

Every run gets a `RUN_ID` (`QA-260826-110404-a231`). `{record}` expands to a
unique, test-owned name derived from it, so two runs never collide and residue
is traceable. `cleanup` steps run **even when the test fails**; anything they
could not remove is reported in `output/functional-leftovers.json` and in the
JUnit body rather than silently forgotten.

### Failure evidence

A failing step writes `reports/evidence/<run id>/<test>/`:

| Evidence | Contents |
|---|---|
| `step-N-<action>.png` | full-page screenshot at the moment of failure |
| `trace.zip` | Playwright trace, replayable in `npx playwright show-trace` |
| results JSON + JUnit body | failed step, action, target, **locator used**, expected vs actual, the page's real URL/title/heading, console errors, page errors, failed requests and 4xx/5xx responses |

### Results

`output/functional-results.json` and `reports/junit-functional.xml` - kept
**separate** from `junit-discovery.xml`, because a weak locator is a code-quality
signal while a failed functional test is a broken application. `--run-tests`
exits **6** when any test fails.

## Jenkins

`reports/junit-discovery.xml` is standard JUnit: a case per UI state, a failure
per weak or unstable locator (carrying the suggested test id), skips for
locators that could not be validated because the element was hidden.

    PhenomeOne-UI-Discovery-cli.exe --cli --url %URL% --user %USER% --headless \
        --crawl --generate-tests --fail-on-low 0

Exit codes: `0` ok, `2` bad arguments, `3` not authenticated, `4` CI gate
(too many LOW locators), `5` `--diff` found changes.

Still to build: workflow *replay*, a Jenkinsfile, and an opt-in for CONDITIONAL
actions during a crawl. The engine is GUI-free and importable
(`p1uid.browser.controller.Engine`), so these bolt on without touching the
discovery core.
