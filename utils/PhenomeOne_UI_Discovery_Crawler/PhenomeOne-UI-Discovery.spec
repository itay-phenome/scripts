# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec - portable onedir build (spec 25).

Produces ONE folder containing two entry points that share a single runtime:

    PhenomeOne-UI-Discovery.exe       GUI (no console window)
    PhenomeOne-UI-Discovery-cli.exe   headless / CI entry point (console)

Chromium is NOT bundled by PyInstaller; build_portable.py copies it into
`browser\\` afterwards, because dragging 400 MB through the Analysis step is
slow and pointless - Playwright locates it at runtime via
PLAYWRIGHT_BROWSERS_PATH.
"""
from PyInstaller.utils.hooks import collect_all

APP = "PhenomeOne-UI-Discovery"

datas, binaries, hiddenimports = [], [], []

# The Playwright wheel carries its Node driver under playwright/driver - that
# whole tree must ship, or nothing can launch.
for pkg in ("playwright",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += [
    "pyee", "pyee.asyncio", "greenlet",
    "tkinter", "tkinter.ttk", "tkinter.messagebox",
    # Imported lazily inside functions; list them so nothing is missed.
    "p1uid.app", "p1uid.paths", "p1uid.logging_setup",
    "p1uid.gui.main_window", "p1uid.browser.controller", "p1uid.browser.injected",
    "p1uid.auth.login", "p1uid.discovery.scanner",
    "p1uid.locator.generator", "p1uid.locator.validator",
    "p1uid.state.fingerprint", "p1uid.store.uimap",
    "p1uid.training.trainer", "p1uid.navigation.graph",
    "p1uid.reporting.html_report", "p1uid.reporting.junit",
    "p1uid.security.dpapi", "p1uid.security.session_store",
    # Autonomous discovery + consumer phases (imported lazily inside functions).
    "p1uid.crawler", "p1uid.crawler.safety", "p1uid.crawler.bfs",
    "p1uid.crawler.surfaces", "p1uid.crawler.outcomes",
    "p1uid.discovery.stability", "p1uid.training.workflows",
    "p1uid.diff", "p1uid.codegen",
    # Functional QA layer (Phase 1) - all imported lazily inside functions.
    "p1uid.functional", "p1uid.functional.steps", "p1uid.functional.runner",
    "p1uid.functional.data", "p1uid.functional.evidence", "p1uid.functional.results",
    "p1uid.reporting.junit_functional",
    "xml.etree.ElementTree",
]

a = Analysis(
    ["main.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "numpy", "pandas", "matplotlib", "PIL", "setuptools", "pip"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe_gui = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=APP,
    console=False,               # GUI: no console window
    disable_windowed_traceback=False,
    strip=False, upx=False,
)

exe_cli = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=APP + "-cli",
    console=True,                # CLI: keep stdout for Jenkins
    strip=False, upx=False,
)

coll = COLLECT(
    exe_gui, exe_cli,
    a.binaries, a.datas,
    strip=False, upx=False,
    name=APP,
)
