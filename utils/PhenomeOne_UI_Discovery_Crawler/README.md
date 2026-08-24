# PhenomeOne UI Discovery

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
3. Enter URL / username / password and press **LOGIN**, or press **Manual Login**
   and sign in yourself in the browser window.
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
* “Remember authenticated session” stores the Playwright `storage_state`
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
* Not tested against the real PhenomeOne application; all verification here is
  against the bundled mock SPA.

## Not built yet (designed for, deliberately out of scope for v1)

Safe Crawl (autonomous exploration of safe controls), workflow recording, UI diff
between revisions, Jenkins pipeline integration, and test generation. The engine
is GUI-free and importable (`p1uid.browser.controller.Engine`), so these can be
added without touching the discovery core.
