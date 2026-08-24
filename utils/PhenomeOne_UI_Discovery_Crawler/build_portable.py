#!/usr/bin/env python3
"""Build the portable Windows distribution (spec 25).

    python build_portable.py [--clean] [--out DIR]

Result:

    dist/PhenomeOne-UI-Discovery/
        PhenomeOne-UI-Discovery.exe        <- double-click this
        PhenomeOne-UI-Discovery-cli.exe    <- headless / CI
        _internal/                         <- Python runtime + Playwright driver
        browser/chromium-<rev>/            <- bundled Chromium
        config/ sessions/ output/ reports/ logs/
        README.txt

Nothing outside this folder is needed at runtime: no Python, no Node, no
npm, no Playwright install, no Chrome/Edge.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = "PhenomeOne-UI-Discovery"
SPEC = ROOT / f"{APP}.spec"


def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


def fail(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"[build] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def find_chromium() -> Path:
    """Locate the Chromium that Playwright downloaded on this machine."""
    roots = []
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        roots.append(Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(Path(local) / "ms-playwright")
    for root in roots:
        if not root.is_dir():
            continue
        cands = sorted(root.glob("chromium-*"), key=lambda p: p.name, reverse=True)
        for c in cands:
            if list(c.glob("chrome-win*/chrome.exe")):
                return c
    fail("could not find a downloaded Chromium. Run:  python -m playwright install chromium")


def dir_size_mb(path: Path) -> float:
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / 1_000_000


README = r"""PhenomeOne UI Discovery - portable build
=======================================

Requirements on the target machine: none. No Python, Node.js, npm, Playwright,
Chrome/Edge, Docker or WSL is required. Everything is in this folder.

HOW TO RUN
  1. Copy this whole folder anywhere (C:\Tools\, a USB stick, another PC).
     Keep the path reasonably short - Chromium cannot start if its own files
     end up deeper than the Windows 260-character path limit.
  2. Double-click PhenomeOne-UI-Discovery.exe
  3. Enter the PhenomeOne URL, username and password -> LOGIN
     (or press "Manual Login" and sign in yourself in the browser window).
  4. SCAN CURRENT PAGE analyses the screen you are on.
  5. START TRAINING, then use PhenomeOne normally. Everything you visit is
     learned. STOP TRAINING writes the map and the report.

OUTPUT
  output\ui-map.json            every UI state, element and validated locator
  output\navigation-graph.json  state -> action -> state graph
  output\application.json       environment + totals
  output\training-summary.json  last training session
  reports\discovery-report.html readable report
  logs\discovery.log            diagnostics

SAFE CRAWL (autonomous)
  Press SAFE CRAWL to let the tool explore by itself. It clicks ONLY controls it
  classified as read-only navigation - tabs, same-origin links, expanders,
  pagination. It never clicks Save/Delete/Submit/Import/Logout or anything it
  does not recognise, never accepts a confirmation dialog, refuses downloads and
  never leaves the site. Results land in output\crawl-summary.json.

COMMAND LINE (CI / Jenkins)
  PhenomeOne-UI-Discovery-cli.exe --cli --url https://... --user me@example.com --headless
  The password is read from the P1UID_PASSWORD environment variable - never
  from a command-line argument.

  Useful flags:
    --crawl              explore autonomously after login (read-only actions)
    --workflow NAME      record a training session as a named workflow
    --generate-tests     write Playwright assets to output\generated\
    --diff A B           compare two ui-map.json files (exit 5 if they differ)
    --fail-on-low N      CI gate: exit 4 above N weak locators
  Reports for Jenkins: reports\junit-discovery.xml

SECURITY
  * The password is kept in memory only. It is never written to any file.
  * "Remember authenticated session" stores the browser session under
    sessions\, encrypted with Windows DPAPI (only your Windows account on this
    machine can decrypt it). Use "Clear Saved Session" to delete it.
  * sessions\ is never included in reports, UI maps or logs.

NOTE
  Training mode only observes. It never clicks anything in PhenomeOne.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true", help="remove build/ and dist/ first")
    ap.add_argument("--out", default=str(ROOT / "dist"), help="output directory")
    ap.add_argument("--skip-pyinstaller", action="store_true",
                    help="only refresh the browser/ and folder layout")
    args = ap.parse_args()

    t0 = time.time()
    out_root = Path(args.out).resolve()
    dist = out_root / APP

    if not SPEC.is_file():
        fail(f"missing spec file: {SPEC}")
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        fail("PyInstaller is not installed. Run:  python -m pip install pyinstaller")

    chromium = find_chromium()
    log(f"Chromium source: {chromium}  ({dir_size_mb(chromium):.0f} MB)")

    if args.clean:
        for d in (ROOT / "build", out_root):
            if d.exists():
                log(f"removing {d}")
                shutil.rmtree(d, ignore_errors=True)

    if not args.skip_pyinstaller:
        log("running PyInstaller (this takes a minute)...")
        cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm",
               "--distpath", str(out_root), "--workpath", str(ROOT / "build"),
               str(SPEC)]
        res = subprocess.run(cmd, cwd=str(ROOT))
        if res.returncode != 0:
            fail(f"PyInstaller failed with exit code {res.returncode}")

    exe = dist / f"{APP}.exe"
    if not exe.is_file():
        fail(f"expected executable not found: {exe}")

    # --- bundle Chromium --------------------------------------------------
    target = dist / "browser" / chromium.name
    if target.exists():
        log(f"Chromium already present: {target.name}")
    else:
        log(f"copying Chromium -> browser\\{chromium.name} (400+ MB, please wait)")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(chromium, target)
    if not list(target.glob("chrome-win*/chrome.exe")):
        fail("Chromium copy looks wrong: chrome.exe not found")

    # --- runtime folders + docs -------------------------------------------
    for d in ("config", "sessions", "output", "reports", "logs"):
        (dist / d).mkdir(parents=True, exist_ok=True)
    (dist / "README.txt").write_text(README, encoding="utf-8")
    (dist / "sessions" / "DO-NOT-COMMIT.txt").write_text(
        "Files here contain an authenticated browser session. Treat them as secrets.\n"
        "They are DPAPI-encrypted and only usable by your Windows account on this machine.\n",
        encoding="utf-8")

    size = dir_size_mb(dist)
    path_len = len(str(dist))
    log("-" * 60)
    log(f"BUILD OK in {time.time() - t0:.0f}s")
    log(f"portable folder : {dist}")
    log(f"executable      : {exe.name}  (+ {APP}-cli.exe)")
    log(f"bundled browser : browser\\{chromium.name}")
    log(f"total size      : {size:.0f} MB")
    if path_len > 150:
        log(f"WARNING: this folder path is {path_len} characters long. Chromium may fail to "
            f"start from here - move the folder closer to a drive root before running it.")
    log("-" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
