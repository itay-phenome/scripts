"""Portable path resolution.

Every runtime path is derived from the application directory so the whole folder
can be moved to any drive / machine. Nothing is written outside APP_DIR.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "PhenomeOne UI Discovery"
APP_SLUG = "PhenomeOne-UI-Discovery"


def _install_dir() -> Path:
    """Where the application is INSTALLED - the folder holding the executable.

    The bundled browser ships beside the executable, so it must be found here
    and never from the data directory: pointing outputs at a CI workspace must
    not make Chromium unfindable.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _app_dir() -> Path:
    """Where the application WRITES - config, output, reports, logs, sessions.

    P1UID_HOME (if set): explicit override, used by the test suite and by anyone
        who wants config/output somewhere other than next to the executable
        (a Jenkins workspace, for instance).
    Otherwise: the install directory.
    """
    override = os.environ.get("P1UID_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return _install_dir()


INSTALL_DIR: Path = _install_dir()
APP_DIR: Path = _app_dir()

# Browser follows the executable; everything else follows the data home.
# P1UID_BROWSERS_PATH overrides it for unusual deployments.
BROWSER_DIR = Path(os.environ["P1UID_BROWSERS_PATH"]).expanduser().resolve() \
    if os.environ.get("P1UID_BROWSERS_PATH") else INSTALL_DIR / "browser"
CONFIG_DIR = APP_DIR / "config"
SESSIONS_DIR = APP_DIR / "sessions"
OUTPUT_DIR = APP_DIR / "output"
REPORTS_DIR = APP_DIR / "reports"
LOGS_DIR = APP_DIR / "logs"

UI_MAP_FILE = OUTPUT_DIR / "ui-map.json"
NAV_GRAPH_FILE = OUTPUT_DIR / "navigation-graph.json"
APPLICATION_FILE = OUTPUT_DIR / "application.json"
TRAINING_SUMMARY_FILE = OUTPUT_DIR / "training-summary.json"
CRAWL_SUMMARY_FILE = OUTPUT_DIR / "crawl-summary.json"
WORKFLOWS_FILE = OUTPUT_DIR / "workflows.json"
REPORT_FILE = REPORTS_DIR / "discovery-report.html"
DIFF_JSON_FILE = OUTPUT_DIR / "ui-diff.json"
DIFF_REPORT_FILE = REPORTS_DIR / "ui-diff.html"
JUNIT_FILE = REPORTS_DIR / "junit-discovery.xml"
# Functional QA artefacts, kept separate from the discovery-health ones.
FUNCTIONAL_RESULTS_FILE = OUTPUT_DIR / "functional-results.json"
FUNCTIONAL_JUNIT_FILE = REPORTS_DIR / "junit-functional.xml"
LEFTOVERS_FILE = OUTPUT_DIR / "functional-leftovers.json"
EVIDENCE_DIR = REPORTS_DIR / "evidence"
GENERATED_DIR = OUTPUT_DIR / "generated"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
SESSION_FILE = SESSIONS_DIR / "session.bin"

_WRITABLE = (CONFIG_DIR, SESSIONS_DIR, OUTPUT_DIR, REPORTS_DIR, LOGS_DIR)


def ensure_dirs() -> None:
    for d in _WRITABLE:
        d.mkdir(parents=True, exist_ok=True)


# Chromium fails to start when its own files sit too deep: chrome.exe plus its
# nested resources must stay under the 260-character Windows path limit.
MAX_SAFE_BROWSER_PATH = 150


def browser_path_warning() -> str:
    """Non-empty when the install path is too deep for Chromium to start."""
    n = len(str(BROWSER_DIR))
    if n > MAX_SAFE_BROWSER_PATH:
        return (f"The application folder path is very long ({n} characters). Chromium may fail "
                f"to start because its internal files would exceed the Windows 260-character "
                r"path limit. Move the folder closer to a drive root, e.g. C:\Tools\.")
    return ""


def configure_browser_env() -> str:
    """Point Playwright at the bundled browser folder.

    Must run before the first Playwright launch. Returns a human-readable note
    describing which browser location will be used.
    """
    if BROWSER_DIR.is_dir() and any(BROWSER_DIR.glob("chromium-*")):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSER_DIR)
        return f"bundled ({BROWSER_DIR})"
    # Development fallback: whatever Playwright already has installed.
    os.environ.setdefault("PLAYWRIGHT_SKIP_BROWSER_GC", "1")
    return "system Playwright cache (development mode)"


def rel(p: Path | str) -> str:
    """Path relative to APP_DIR when possible — keeps logs/reports portable."""
    try:
        return str(Path(p).resolve().relative_to(APP_DIR))
    except (ValueError, OSError):
        return str(p)
