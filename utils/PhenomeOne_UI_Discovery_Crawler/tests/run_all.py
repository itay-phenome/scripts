"""Run every source suite N times from a clean state and report flakiness.

    python tests/run_all.py [--runs 3] [--debug]

Each suite runs as its own process with its own temporary P1UID_HOME, so no run
can inherit state from another. A suite that does not produce identical results
across runs is reported as FLAKY - that is the whole point of running it more
than once.

`test_packaged.py` is excluded: it needs a built distribution and relocates it,
so it is driven separately by the portable-build check.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SUITES = [
    "test_units.py",
    "test_safety.py",
    "test_surfaces.py",
    "test_artifacts.py",
    "test_crawler.py",
    "test_multisurface.py",
    "test_redteam.py",
    "test_pipeline.py",
    "test_recovery.py",
    "test_functional.py",
    "test_hardgrid.py",
    "test_e2e_mock.py",
    "test_login_variants.py",
    "test_gui_smoke.py",
]

RESULT_RE = re.compile(r"(\d+)/(\d+)\s+[a-zA-Z\- ]*checks passed")


def clean() -> None:
    for pyc in ROOT.rglob("__pycache__"):
        shutil.rmtree(pyc, ignore_errors=True)
    tmp = Path(tempfile.gettempdir())
    for stale in list(tmp.glob("p1uid-*")):
        shutil.rmtree(stale, ignore_errors=True)


def run_suite(name: str, debug: bool) -> tuple[bool, int, int, float, str]:
    cmd = [sys.executable, str(ROOT / "tests" / name)] + (["--debug"] if debug else [])
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=2400)
    took = time.time() - t0
    out = proc.stdout + proc.stderr
    m = None
    for m in RESULT_RE.finditer(out):
        pass
    passed, total = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    fails = [l.strip() for l in out.splitlines()
             if l.strip().startswith("FAIL ") or l.strip().startswith("- FAIL")][:4]
    ok = proc.returncode == 0 and total > 0 and passed == total
    return ok, passed, total, took, "; ".join(fails)


def main() -> int:
    runs = 3
    if "--runs" in sys.argv:
        runs = int(sys.argv[sys.argv.index("--runs") + 1])
    debug = "--debug" in sys.argv
    # `--only a.py,b.py` runs a subset. The whole suite now takes ~10 minutes,
    # which can exceed a caller's timeout, so it must be splittable without
    # hand-running each file and losing the flakiness summary.
    if "--only" in sys.argv:
        wanted = [s.strip() for s in sys.argv[sys.argv.index("--only") + 1].split(",") if s.strip()]
        unknown = [w for w in wanted if w not in SUITES]
        if unknown:
            print(f"unknown suite(s): {', '.join(unknown)}")
            return 2
        SUITES[:] = wanted

    history: dict[str, list[tuple[bool, int, int]]] = {s: [] for s in SUITES}
    durations: dict[str, list[float]] = {s: [] for s in SUITES}

    for run in range(1, runs + 1):
        print(f"\n{'=' * 74}\nRUN {run}/{runs}  (clean state)\n{'=' * 74}")
        clean()
        for suite in SUITES:
            ok, passed, total, took, detail = run_suite(suite, debug)
            history[suite].append((ok, passed, total))
            durations[suite].append(took)
            status = "PASS" if ok else "FAIL"
            print(f"  {status}  {suite:26} {passed:>4}/{total:<4} {took:6.1f}s"
                  + (f"   {detail}" if detail else ""))

    print(f"\n{'=' * 74}\nSUMMARY OVER {runs} RUNS\n{'=' * 74}")
    flaky, failing, total_checks = [], [], 0
    for suite in SUITES:
        results = history[suite]
        oks = {r[0] for r in results}
        counts = {(r[1], r[2]) for r in results}
        avg = sum(durations[suite]) / len(durations[suite])
        total_checks += results[-1][2]
        state = "PASS" if oks == {True} else ("FLAKY" if len(oks) > 1 else "FAIL")
        if state == "FLAKY" or len(counts) > 1:
            flaky.append(f"{suite} {sorted(counts)}")
            state = "FLAKY"
        if state == "FAIL":
            failing.append(suite)
        print(f"  {state:5} {suite:26} {sorted(counts)}  avg {avg:6.1f}s")

    print(f"\n  checks per run : {total_checks}")
    print(f"  failing suites : {', '.join(failing) if failing else 'none'}")
    print(f"  flaky suites   : {', '.join(flaky) if flaky else 'none'}")
    ok = not failing and not flaky
    print(f"\n  {runs} consecutive clean runs: {'ALL GREEN' if ok else 'NOT CLEAN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
