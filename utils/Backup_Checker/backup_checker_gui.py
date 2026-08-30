#!/usr/bin/env python3
"""
RDS Backup Checker — desktop GUI
Phenome Networks

A dark-themed Tkinter front end for backup_checker.py. Runs the same
validate -> scan -> report pipeline in a background thread and streams
its console output live into the window.
"""

from __future__ import annotations

# ── stdio guard — must run before any other project import ────────────────────
# PyInstaller's windowed mode (--noconsole / --windowed) starts the process with
# no console attached, so Python sets sys.stdout, sys.stderr and sys.stdin to
# None. Any bare `sys.stdout.<attr>` access then raises AttributeError at import
# time — before the GUI can even show a window. Swapping in throwaway in-memory
# buffers fixes the whole class of bug at once: every downstream stdio user
# (backup_checker's ~200 print() calls, the stdout/stderr swap in _run_worker,
# logging's stderr fallback, boto3, any third-party library) keeps working
# unchanged instead of needing its own None check.
#
# In a real terminal all three streams are real objects, so nothing here fires
# and behaviour is byte-for-byte what it was. backup_checker.py carries the same
# guard, so the CLI entry point is covered too.
import io, sys

if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()
if sys.stdin is None:
    sys.stdin = io.StringIO()

import io
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import backup_checker as bc

APP_NAME = "RDS Backup Checker"
APP_VERSION = "1.0"


def app_dir() -> Path:
    """Folder the exe/script lives in (not PyInstaller's temp _MEIPASS)."""
    return bc.app_dir()          # single definition, shared with the CLI


def rel_to_app(path) -> str:
    """Render a path relative to the app folder when it lives inside it.

    settings.json is stored in %APPDATA%, so it outlives any particular copy of
    the app. Saving an absolute path there breaks as soon as the folder moves or
    the app runs on another machine — exactly how the old Google-Drive path got
    stuck. A path outside the app folder has no portable form, so it stays
    absolute.
    """
    try:
        inside = Path(path).resolve().relative_to(app_dir().resolve())
    except (ValueError, OSError):
        return str(path)
    return f".{os.sep}{inside}"


def abs_from_app(path) -> str:
    """Anchor a stored path: relative ones hang off the app folder, not the CWD.

    A GUI launched from a shortcut or the Start menu inherits an arbitrary
    working directory, so a relative path must be resolved explicitly or it
    would point somewhere unpredictable.
    """
    p = Path(path)
    if p.is_absolute():
        return str(p)
    return str((app_dir() / p).resolve())


def settings_path() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home()))
    d = base / "Phenome" / "BackupChecker"
    d.mkdir(parents=True, exist_ok=True)
    return d / "settings.json"


def log_path() -> Path:
    """Where the windowed build writes its log — next to settings.json."""
    return settings_path().with_name("backup_checker.log")


def setup_logging() -> Path:
    """Route log records to a file instead of the console.

    logging's fallback handler — and any StreamHandler a library installs —
    writes to sys.stderr. In a windowed build that is the throwaway buffer from
    the stdio guard at the top of this file, so records would accumulate in
    memory and be lost on exit. A rotating file handler keeps them somewhere a
    user can actually read after a crash.
    """
    path = log_path()
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for existing in list(root.handlers):     # drop console handlers, if any
        root.removeHandler(existing)
    root.addHandler(handler)
    for noisy in ("boto3", "botocore", "urllib3", "s3transfer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return path


DEFAULTS = {
    "config": rel_to_app(app_dir() / "backup_config.xlsx"),
    "output": rel_to_app(app_dir() / "backup_report"),
    "profile": "",
    "region": "us-east-1",
    "min_size_mb": str(bc.DEFAULT_MIN_MB),
    "max_age_days": str(bc.DEFAULT_MAX_DAYS),
    "dry_run": False,
}


def _prefer_local_paths(values: dict) -> dict:
    """Fall back to the copies beside the app when a remembered path is stale.

    settings.json lives in %APPDATA%, not beside the exe, so it follows the user
    across machines and folders while the paths inside it do not. An absolute
    path saved from a mapped drive or a synced folder is often unreachable on
    the next machine, and without this the app would keep pointing there instead
    of at the backup_config.xlsx sitting right next to it.

    A config the user deliberately browsed to is kept as long as it still
    resolves — only genuinely unusable paths are replaced.
    """
    try:
        if not Path(abs_from_app(values["config"])).is_file():
            values["config"] = DEFAULTS["config"]
    except (OSError, ValueError, TypeError, KeyError):
        values["config"] = DEFAULTS["config"]
    try:
        if not Path(abs_from_app(values["output"])).parent.is_dir():
            values["output"] = DEFAULTS["output"]
    except (OSError, ValueError, TypeError, KeyError):
        values["output"] = DEFAULTS["output"]
    return values


def load_settings() -> dict:
    p = settings_path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            merged = dict(DEFAULTS)
            merged.update(data)
            return _prefer_local_paths(merged)
        except Exception:
            pass
    return dict(DEFAULTS)


def save_settings(values: dict):
    try:
        settings_path().write_text(json.dumps(values, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── palette ───────────────────────────────────────────────────────────────────
BG       = "#0f172a"
BG_PANEL = "#161f36"
BG_INPUT = "#1e293b"
FG       = "#e2e8f0"
FG_DIM   = "#94a3b8"
BORDER   = "#2a3752"
ACCENT   = "#38bdf8"
GREEN    = "#22c55e"
RED      = "#ef4444"
YELLOW   = "#f59e0b"
GRAY     = "#64748b"

FONT_UI   = ("Segoe UI", 10)
FONT_UI_B = ("Segoe UI", 10, "bold")
FONT_HDR  = ("Segoe UI Semibold", 15)
FONT_MONO = ("Consolas", 9)


class QueueWriter(io.TextIOBase):
    """Stand-in for sys.stdout/stderr during a pipeline run — pushes each
    write into a thread-safe queue the GUI polls on the Tk main loop."""

    def __init__(self, q: queue.Queue):
        self._q = q
        self._buf = ""

    def write(self, s):
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._q.put(("line", line))
        return len(s)

    def flush(self):
        pass


class BackupCheckerGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = load_settings()
        self.msg_queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.running = False
        self.last_report: dict | None = None

        root.title(APP_NAME)
        root.geometry("980x720")
        root.minsize(860, 600)
        root.configure(bg=BG)
        self._set_icon()

        self._build_style()
        self._build_layout()
        self._poll_queue()

        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── setup ─────────────────────────────────────────────────────────────
    def _set_icon(self):
        try:
            ico = app_dir() / "backup_checker.ico"
            if ico.exists():
                self.root.iconbitmap(str(ico))
        except Exception:
            pass

    def _build_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=BG_PANEL)
        style.configure("TLabel", background=BG, foreground=FG, font=FONT_UI)
        style.configure("Panel.TLabel", background=BG_PANEL, foreground=FG, font=FONT_UI)
        style.configure("Dim.TLabel", background=BG, foreground=FG_DIM, font=FONT_UI)
        style.configure("PanelDim.TLabel", background=BG_PANEL, foreground=FG_DIM, font=FONT_UI)
        style.configure("Header.TLabel", background=BG, foreground=FG, font=FONT_HDR)
        style.configure("Sub.TLabel", background=BG, foreground=FG_DIM, font=FONT_UI)

        style.configure("TEntry", fieldbackground=BG_INPUT, foreground=FG,
                        insertcolor=FG, bordercolor=BORDER, lightcolor=BG_INPUT,
                        darkcolor=BG_INPUT, borderwidth=1)
        style.map("TEntry", fieldbackground=[("readonly", BG_INPUT)])

        style.configure("TCheckbutton", background=BG, foreground=FG, font=FONT_UI)
        style.map("TCheckbutton", background=[("active", BG)])

        style.configure("Accent.TButton", background=ACCENT, foreground="#04202e",
                        font=FONT_UI_B, borderwidth=0, padding=(14, 8))
        style.map("Accent.TButton",
                  background=[("active", "#5cc9fb"), ("disabled", "#2b3a4d")],
                  foreground=[("disabled", "#5b6b7d")])

        style.configure("Ghost.TButton", background=BG_PANEL, foreground=FG,
                        font=FONT_UI, borderwidth=1, padding=(10, 6))
        style.map("Ghost.TButton",
                  background=[("active", BORDER), ("disabled", BG_PANEL)],
                  foreground=[("disabled", GRAY)])

        style.configure("Horizontal.TProgressbar", troughcolor=BG_PANEL,
                        background=ACCENT, bordercolor=BG_PANEL, lightcolor=ACCENT,
                        darkcolor=ACCENT)

    def _build_layout(self):
        root = self.root
        root.rowconfigure(3, weight=1)
        root.columnconfigure(0, weight=1)

        # ── header ──────────────────────────────────────────────────────
        hdr = ttk.Frame(root, style="TFrame")
        hdr.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 4))
        hdr.columnconfigure(0, weight=1)
        ttk.Label(hdr, text="RDS Backup Checker", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(hdr, text="Phenome Networks  ·  S3 weekly backup verification",
                  style="Sub.TLabel").grid(row=1, column=0, sticky="w")

        # ── settings panel ──────────────────────────────────────────────
        panel = tk.Frame(root, bg=BG_PANEL, highlightthickness=1, highlightbackground=BORDER)
        panel.grid(row=1, column=0, sticky="ew", padx=20, pady=8)
        for c in (1, 3):
            panel.columnconfigure(c, weight=1)

        pad = {"padx": 8, "pady": 6}

        # config file
        tk.Label(panel, text="Config file", bg=BG_PANEL, fg=FG, font=FONT_UI).grid(
            row=0, column=0, sticky="w", **pad)
        self.var_config = tk.StringVar(value=self.settings["config"])
        tk.Entry(panel, textvariable=self.var_config, bg=BG_INPUT, fg=FG,
                  insertbackground=FG, relief="flat", font=FONT_UI).grid(
            row=0, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Button(panel, text="Browse…", style="Ghost.TButton",
                   command=self._browse_config).grid(row=0, column=3, sticky="e", **pad)

        # output base
        tk.Label(panel, text="Output folder / name", bg=BG_PANEL, fg=FG, font=FONT_UI).grid(
            row=1, column=0, sticky="w", **pad)
        self.var_output = tk.StringVar(value=self.settings["output"])
        tk.Entry(panel, textvariable=self.var_output, bg=BG_INPUT, fg=FG,
                  insertbackground=FG, relief="flat", font=FONT_UI).grid(
            row=1, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Button(panel, text="Browse…", style="Ghost.TButton",
                   command=self._browse_output).grid(row=1, column=3, sticky="e", **pad)

        # min size / max age
        tk.Label(panel, text="Min size (MB)", bg=BG_PANEL, fg=FG, font=FONT_UI).grid(
            row=2, column=0, sticky="w", **pad)
        self.var_min_size = tk.StringVar(value=self.settings["min_size_mb"])
        tk.Entry(panel, textvariable=self.var_min_size, bg=BG_INPUT, fg=FG,
                  insertbackground=FG, relief="flat", font=FONT_UI, width=10).grid(
            row=2, column=1, sticky="w", **pad)

        tk.Label(panel, text="Max age (days)", bg=BG_PANEL, fg=FG, font=FONT_UI).grid(
            row=2, column=2, sticky="w", **pad)
        self.var_max_age = tk.StringVar(value=self.settings["max_age_days"])
        tk.Entry(panel, textvariable=self.var_max_age, bg=BG_INPUT, fg=FG,
                  insertbackground=FG, relief="flat", font=FONT_UI, width=10).grid(
            row=2, column=3, sticky="w", **pad)

        self.var_dry_run = tk.BooleanVar(value=bool(self.settings.get("dry_run", False)))
        ttk.Checkbutton(panel, text="Dry run (validate only, no S3 scan)",
                        variable=self.var_dry_run).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=8, pady=(2, 4))

        # advanced (AWS profile / region) — collapsed by default, rarely needed
        self.var_advanced_open = tk.BooleanVar(value=False)
        self.btn_advanced = tk.Label(panel, text="▸ Advanced (AWS profile / region)",
                                      bg=BG_PANEL, fg=ACCENT, font=FONT_UI, cursor="hand2")
        self.btn_advanced.grid(row=4, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))
        self.btn_advanced.bind("<Button-1>", lambda e: self._toggle_advanced())

        self.adv_frame = tk.Frame(panel, bg=BG_PANEL)
        self.var_profile = tk.StringVar(value=self.settings["profile"])
        self.var_region = tk.StringVar(value=self.settings["region"])
        tk.Label(self.adv_frame, text="AWS profile", bg=BG_PANEL, fg=FG, font=FONT_UI).grid(
            row=0, column=0, sticky="w", **pad)
        tk.Entry(self.adv_frame, textvariable=self.var_profile, bg=BG_INPUT, fg=FG,
                  insertbackground=FG, relief="flat", font=FONT_UI, width=18).grid(
            row=0, column=1, sticky="w", **pad)
        tk.Label(self.adv_frame, text="Region", bg=BG_PANEL, fg=FG, font=FONT_UI).grid(
            row=0, column=2, sticky="w", **pad)
        tk.Entry(self.adv_frame, textvariable=self.var_region, bg=BG_INPUT, fg=FG,
                  insertbackground=FG, relief="flat", font=FONT_UI, width=18).grid(
            row=0, column=3, sticky="w", **pad)
        # not gridded yet — _toggle_advanced() shows/hides it (starts collapsed)

        # ── summary cards + action buttons ────────────────────────────────
        self._build_summary_and_buttons(root)

        # ── log console ─────────────────────────────────────────────────
        log_frame = tk.Frame(root, bg="#0b1222", highlightthickness=1, highlightbackground=BORDER)
        log_frame.grid(row=3, column=0, sticky="nsew", padx=20, pady=(8, 12))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log = tk.Text(log_frame, bg="#0b1222", fg="#cbd5e1", insertbackground=FG,
                            font=FONT_MONO, relief="flat", wrap="none", padx=12, pady=10,
                            state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=yscroll.set)

        self.log.tag_configure("ok", foreground=GREEN)
        self.log.tag_configure("fail", foreground=RED)
        self.log.tag_configure("warn", foreground=YELLOW)
        self.log.tag_configure("info", foreground=GRAY)
        self.log.tag_configure("head", foreground=ACCENT, font=FONT_MONO + ("bold",))
        self.log.tag_configure("rule", foreground=BORDER)
        self.log.tag_configure("plain", foreground="#cbd5e1")

        # ── status bar ──────────────────────────────────────────────────
        status = ttk.Frame(root, style="TFrame")
        status.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 14))
        status.columnconfigure(0, weight=1)

        self.var_status = tk.StringVar(value="Ready.")
        ttk.Label(status, textvariable=self.var_status, style="Dim.TLabel").grid(
            row=0, column=0, sticky="w")

        self.progress = ttk.Progressbar(status, mode="indeterminate", length=160)
        self.progress.grid(row=0, column=1, sticky="e")

    def _build_summary_and_buttons(self, root):
        row = ttk.Frame(root, style="TFrame")
        row.grid(row=2, column=0, sticky="ew", padx=20, pady=(4, 0))
        row.columnconfigure(0, weight=1)

        cards_holder = ttk.Frame(row, style="TFrame")
        cards_holder.grid(row=0, column=0, sticky="w")
        self.card_vars = {}
        specs = [("ok", "OK", GREEN), ("missing", "Missing", RED),
                 ("suspect", "Suspect", YELLOW), ("na", "N/A", GRAY),
                 ("total", "Total", ACCENT)]
        for i, (key, label, color) in enumerate(specs):
            box = tk.Frame(cards_holder, bg=BG_PANEL, highlightthickness=1,
                            highlightbackground=BORDER)
            box.grid(row=0, column=i, padx=(0 if i == 0 else 8, 0), ipadx=14, ipady=6)
            v = tk.StringVar(value="—")
            self.card_vars[key] = v
            n = tk.Label(box, textvariable=v, bg=BG_PANEL, fg=color,
                         font=("Segoe UI Semibold", 16))
            n.pack(anchor="w")
            tk.Label(box, text=label.upper(), bg=BG_PANEL, fg=FG_DIM,
                     font=("Segoe UI", 8)).pack(anchor="w")

        btns = ttk.Frame(row, style="TFrame")
        btns.grid(row=0, column=1, sticky="e")
        row.columnconfigure(1, weight=0)

        self.btn_html = ttk.Button(btns, text="Open HTML report", style="Ghost.TButton",
                                    command=self._open_html, state="disabled")
        self.btn_html.pack(side="left", padx=(0, 6))
        self.btn_folder = ttk.Button(btns, text="Open output folder", style="Ghost.TButton",
                                      command=self._open_folder, state="disabled")
        self.btn_folder.pack(side="left", padx=(0, 12))
        self.btn_run = ttk.Button(btns, text="Run check", style="Accent.TButton",
                                   command=self._on_run)
        self.btn_run.pack(side="left")

    # ── advanced section toggle ─────────────────────────────────────────
    def _toggle_advanced(self):
        open_now = not self.var_advanced_open.get()
        self.var_advanced_open.set(open_now)
        if open_now:
            self.btn_advanced.configure(text="▾ Advanced (AWS profile / region)")
            self.adv_frame.grid(row=5, column=0, columnspan=4, sticky="w")
        else:
            self.btn_advanced.configure(text="▸ Advanced (AWS profile / region)")
            self.adv_frame.grid_remove()

    # ── file pickers ────────────────────────────────────────────────────
    def _browse_config(self):
        start = Path(abs_from_app(self.var_config.get())).parent if self.var_config.get() else app_dir()
        path = filedialog.askopenfilename(
            title="Select backup config file",
            initialdir=str(start) if start.exists() else str(app_dir()),
            filetypes=[("Excel / JSON config", "*.xlsx *.xlsm *.json"), ("All files", "*.*")],
        )
        if path:
            self.var_config.set(rel_to_app(path))

    def _browse_output(self):
        start = Path(abs_from_app(self.var_output.get())).parent if self.var_output.get() else app_dir()
        path = filedialog.asksaveasfilename(
            title="Select output base name (no extension)",
            initialdir=str(start) if start.exists() else str(app_dir()),
            initialfile=Path(abs_from_app(self.var_output.get())).name or "backup_report",
            defaultextension="",
        )
        if path:
            self.var_output.set(rel_to_app(path))

    # ── run pipeline ─────────────────────────────────────────────────────
    def _current_values(self) -> dict:
        return {
            "config": self.var_config.get().strip(),
            "output": self.var_output.get().strip(),
            "profile": self.var_profile.get().strip(),
            "region": self.var_region.get().strip() or "us-east-1",
            "min_size_mb": self.var_min_size.get().strip(),
            "max_age_days": self.var_max_age.get().strip(),
            "dry_run": self.var_dry_run.get(),
        }

    def _on_run(self):
        if self.running:
            return
        vals = self._current_values()

        if not vals["config"]:
            messagebox.showerror(APP_NAME, "Please choose a config file.")
            return
        if not vals["output"]:
            messagebox.showerror(APP_NAME, "Please choose an output folder / name.")
            return
        try:
            min_size_mb = int(vals["min_size_mb"])
            max_age_days = int(vals["max_age_days"])
            if min_size_mb <= 0 or max_age_days <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(APP_NAME, "Min size and max age must be positive whole numbers.")
            return

        save_settings(vals)

        self._clear_log()
        self._reset_cards()
        self.btn_run.configure(state="disabled")
        self.btn_html.configure(state="disabled")
        self.btn_folder.configure(state="disabled")
        self.running = True
        self.var_status.set("Running…")
        self.progress.start(12)

        self.worker = threading.Thread(
            target=self._run_worker,
            args=(abs_from_app(vals["config"]), abs_from_app(vals["output"]),
                  vals["profile"] or None,
                  vals["region"], min_size_mb, max_age_days, vals["dry_run"]),
            daemon=True,
        )
        self.worker.start()

    def _run_worker(self, config, output, profile, region, min_size_mb, max_age_days, dry_run):
        writer = QueueWriter(self.msg_queue)
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = writer
        sys.stderr = writer
        report = None
        error = None
        aborted = False
        try:
            report = bc.run_pipeline(config, output, profile, region,
                                      min_size_mb, max_age_days, dry_run)
        except bc.CheckerAbort:
            aborted = True
        except Exception as e:
            error = str(e)
        finally:
            sys.stdout, sys.stderr = old_out, old_err
        self.msg_queue.put(("done", {"report": report, "error": error, "aborted": aborted,
                                      "dry_run": dry_run}))

    # ── queue polling / log rendering ────────────────────────────────────
    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "line":
                    self._append_log(payload)
                elif kind == "done":
                    self._on_run_done(payload)
        except queue.Empty:
            pass
        self.root.after(60, self._poll_queue)

    def _append_log(self, line: str):
        stripped = line.strip()
        if stripped.startswith("✓"):
            tag = "ok"
        elif stripped.startswith("✗"):
            tag = "fail"
        elif stripped.startswith("⚠"):
            tag = "warn"
        elif stripped.startswith("·"):
            tag = "info"
        elif set(stripped) <= {"─"} and stripped:
            tag = "rule"
        elif set(stripped) <= {"═"} and stripped:
            tag = "rule"
        elif stripped.isupper() and ("STEP" in stripped or "DRY RUN" in stripped or "RDS" in stripped):
            tag = "head"
        else:
            tag = "plain"

        self.log.configure(state="normal")
        self.log.insert("end", line + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _reset_cards(self):
        for v in self.card_vars.values():
            v.set("—")

    def _on_run_done(self, payload):
        self.running = False
        self.progress.stop()
        self.btn_run.configure(state="normal")

        report = payload["report"]
        self.last_report = report

        if payload["error"]:
            self.var_status.set("Failed — see log for details.")
            messagebox.showerror(APP_NAME, f"Unexpected error:\n{payload['error']}")
            return

        if payload["aborted"]:
            self.var_status.set("Stopped — a validation step failed. See log for details.")
            return

        if payload["dry_run"] or report is None:
            self.var_status.set("Dry run complete — no report written.")
            return

        summary = report["summary"]
        self.card_vars["ok"].set(str(summary["ok"]))
        self.card_vars["missing"].set(str(summary["missing"]))
        self.card_vars["suspect"].set(str(summary["suspect"]))
        self.card_vars["na"].set(str(summary["na"]))
        self.card_vars["total"].set(str(summary["total"]))

        self.html_path = Path(report["outputPaths"]["html"])
        self.output_dir = self.html_path.parent
        self.btn_html.configure(state="normal")
        self.btn_folder.configure(state="normal")

        if summary["missing"] > 0:
            self.var_status.set(f"Done — {summary['missing']} missing backup(s) found.")
        elif summary["suspect"] > 0:
            self.var_status.set(f"Done — {summary['suspect']} suspect backup(s) found.")
        else:
            self.var_status.set("Done — all backups OK.")

    def _open_html(self):
        if getattr(self, "html_path", None) and self.html_path.exists():
            webbrowser.open(self.html_path.as_uri())

    def _open_folder(self):
        d = getattr(self, "output_dir", None)
        if d and d.exists():
            try:
                os.startfile(str(d))  # Windows
            except Exception:
                subprocess.Popen(["explorer", str(d)])

    def _on_close(self):
        if self.running:
            if not messagebox.askyesno(APP_NAME, "A check is still running. Quit anyway?"):
                return
        save_settings(self._current_values())
        self.root.destroy()


def main():
    log_file = setup_logging()
    logging.info("%s %s starting (frozen=%s) — log: %s",
                 APP_NAME, APP_VERSION, bool(getattr(sys, "frozen", False)), log_file)

    # A windowed build has no console for a traceback to land on, so send both
    # the interpreter's and Tk's unhandled-exception paths to the log file.
    sys.excepthook = lambda *exc: logging.critical("Unhandled exception", exc_info=exc)

    root = tk.Tk()
    root.report_callback_exception = lambda *exc: logging.critical(
        "Unhandled exception in Tk callback", exc_info=exc)
    BackupCheckerGUI(root)
    root.mainloop()
    logging.info("%s exiting", APP_NAME)


if __name__ == "__main__":
    main()
