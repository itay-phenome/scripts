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
  discovery/stability.py  waitStable(): settle detection for autonomous discovery
  crawler/safety.py       SAFE_NAVIGATION / CONDITIONAL / DANGEROUS / UNKNOWN
  reporting/html_report.py self-contained HTML report
  security/               dpapi.py, session_store.py
```

The GUI is a thin shell: it submits named operations to the `Engine` and renders
events off a `queue.Queue`. `Engine` is fully usable without it — that is how the
CLI and every test drives it, and how Safe Crawl / test generation would later.

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
   UNKNOWN - it might be Save, it might be Delete.
2. **Structure beats words.** `<button>` with no `type` inside a form submits it,
   so a button captioned "Go" in a POST form is DANGEROUS. Likewise
   `input[type=submit|reset|image]`, downloads, `mailto:`/`javascript:`/`blob:`/
   `data:` URLs, cross-origin hrefs and `target=_blank`.
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

## Safety

Training only listens. Listeners are capture-phase and passive, and never call
`preventDefault`, `stopPropagation`, or dispatch synthetic events. No code path
clicks, fills, or submits anything in the target application except the login
form the user explicitly asked for.
