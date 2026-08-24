"""Verify the PACKAGED portable build (spec 26).

This does not import the application. It relocates the built folder, strips
Python/Node from the environment, and runs the shipped executables the way a
target machine would.

    python tests/test_packaged.py C:\\Users\\me\\p1uid-build\\PhenomeOne-UI-Discovery
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from serve_mock import MockServer                                   # noqa: E402

PASSWORD = "PackagedRunPass!-secret"
failures: list[str] = []
count = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global count
    count += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """An environment that looks like a machine with no developer tooling:
    no Python, no Node, no npm, no Playwright, nothing on PATH but Windows."""
    # NB: on Windows, Python upper-cases os.environ keys - compare case-insensitively,
    # and SystemRoot must survive or Winsock (asyncio) cannot initialise at all.
    keep = {"systemroot", "windir", "temp", "tmp", "userprofile", "localappdata",
            "appdata", "programdata", "programfiles", "comspec", "systemdrive",
            "number_of_processors", "processor_architecture", "username", "computername",
            "homedrive", "homepath", "sessionname"}
    env = {k: v for k, v in os.environ.items() if k.lower() in keep}
    root = env.get("SYSTEMROOT") or env.get("SystemRoot") or r"C:\Windows"
    env["SystemRoot"] = root
    env["PATH"] = f"{root}\\system32;{root};{root}\\System32\\Wbem"
    env.update(extra or {})
    return env


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    built = Path(sys.argv[1]).resolve()
    if not built.is_dir():
        print(f"not a directory: {built}")
        return 2

    # ---- relocation test: the folder must work from a different path -----
    base = built.parent.parent if built.parent.name.startswith("relocated-") else built.parent
    relocated = base / f"relocated-{time.strftime('%H%M%S')}" / built.name
    relocated.parent.mkdir(parents=True, exist_ok=True)
    print(f"\nrelocating\n  from {built}\n  to   {relocated}")
    shutil.move(str(built), str(relocated))

    gui_exe = relocated / "PhenomeOne-UI-Discovery.exe"
    cli_exe = relocated / "PhenomeOne-UI-Discovery-cli.exe"
    print()
    check("GUI executable present", gui_exe.is_file())
    check("CLI executable present", cli_exe.is_file())
    check("Chromium bundled", bool(list((relocated / "browser").glob("chromium-*/chrome-win*/chrome.exe"))))
    check("Playwright Node driver bundled",
          (relocated / "_internal" / "playwright" / "driver" / "node.exe").is_file())
    check("no session file shipped", not any((relocated / "sessions").glob("*.bin")))

    env = clean_env()
    print("\n[1] --version in a stripped environment (no Python/Node on PATH)")
    r = subprocess.run([str(cli_exe), "--version"], capture_output=True, text=True,
                       env=env, cwd=str(relocated.parent), timeout=180)
    check("runs with no external runtime", r.returncode == 0 and "PhenomeOne" in r.stdout,
          (r.stdout + r.stderr).strip()[:200])

    # Wipe previous run artefacts so the checks below prove this run made them.
    for d in ("output", "reports", "logs"):
        shutil.rmtree(relocated / d, ignore_errors=True)

    with MockServer() as server:
        url = server.url + "?autodrive=1"
        print(f"\n[2] full discovery run against {url}")
        env2 = clean_env({"P1UID_PASSWORD": PASSWORD})
        t0 = time.time()
        r = subprocess.run([str(cli_exe), "--cli", "--url", url,
                           "--user", "tester@example.com", "--headless",
                           "--train-seconds", "22", "--remember"],
                           capture_output=True, text=True, env=env2,
                           cwd=str(relocated.parent), timeout=600)
        took = time.time() - t0
        out = r.stdout + r.stderr
        print("\n".join("    " + l for l in out.strip().splitlines()[-14:]))
        check("packaged run exits successfully", r.returncode == 0, f"rc={r.returncode}")
        check("run completed in reasonable time", took < 240, f"{took:.0f}s")
        check("bundled browser was used (not a system Chrome)",
              "bundled" in out and str(relocated / "browser") in out)
        check("no traceback", "Traceback (most recent call last)" not in out)

        ui_map = relocated / "output" / "ui-map.json"
        check("ui-map.json created next to the exe", ui_map.is_file())
        check("navigation-graph.json created", (relocated / "output" / "navigation-graph.json").is_file())
        check("application.json created", (relocated / "output" / "application.json").is_file())
        check("training-summary.json created", (relocated / "output" / "training-summary.json").is_file())
        check("HTML report created", (relocated / "reports" / "discovery-report.html").is_file())
        check("log file created", (relocated / "logs" / "discovery.log").is_file())

        if ui_map.is_file():
            data = json.loads(ui_map.read_text(encoding="utf-8"))
            states = data.get("states", {})
            nav = data.get("navigation", {})
            print(f"\n    packaged run learned {len(states)} states, {len(nav)} navigation paths")
            check("states discovered by the packaged build", len(states) >= 3, str(sorted(states)))
            check("training in the packaged build learned navigation", len(nav) >= 2, str(len(nav)))
            conf: dict[str, int] = {}
            for st in states.values():
                for el in st.get("elements", {}).values():
                    conf[el.get("confidence")] = conf.get(el.get("confidence"), 0) + 1
            check("HIGH-quality locators produced", conf.get("HIGH", 0) > 0, str(conf))
            check("locators validated against the live page",
                  any((el.get("locator") or {}).get("validation") == "live"
                      for st in states.values() for el in st["elements"].values()))

        check("session saved by the packaged build (DPAPI)",
              (relocated / "sessions" / "session.bin").is_file())

        print("\n[3] secrets never written to disk")
        leaks = []
        for p in relocated.rglob("*"):
            if p.is_file() and p.stat().st_size < 40_000_000:
                try:
                    if PASSWORD.encode() in p.read_bytes():
                        leaks.append(str(p.relative_to(relocated)))
                except OSError:
                    pass
        check("password appears in no file in the package", not leaks, "; ".join(leaks))

        print("\n[4] GUI executable launches")
        log = relocated / "logs" / "discovery.log"
        before = log.stat().st_size if log.is_file() else 0
        proc = subprocess.Popen([str(gui_exe)], env=clean_env(), cwd=str(relocated.parent))
        started = False
        for _ in range(90):
            time.sleep(1)
            if log.is_file() and log.stat().st_size > before and "ready" in \
                    log.read_text(encoding="utf-8", errors="replace")[-4000:]:
                started = True
                break
            if proc.poll() is not None:
                break
        check("GUI process starts and logs readiness", started and proc.poll() is None,
              f"exit={proc.poll()}")
        proc.terminate()
        try:
            proc.wait(20)
        except subprocess.TimeoutExpired:
            proc.kill()

    print(f"\n{'=' * 62}\n{count - len(failures)}/{count} packaging checks passed")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
    else:
        print("PACKAGED BUILD VERIFIED")
    print(f"\npackage now lives at: {relocated}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
