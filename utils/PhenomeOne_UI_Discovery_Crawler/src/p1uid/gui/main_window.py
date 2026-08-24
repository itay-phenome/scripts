"""Tkinter GUI (spec 19). Functional, not decorative.

The GUI owns no Playwright state: it submits operations to the Engine and
renders the events the engine puts on a queue. The password lives in a Tk
variable only until login is submitted, then it is wiped.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from .. import paths
from ..browser.controller import Engine
from ..logging_setup import get, register_secret, setup
from ..security.session_store import SessionStore

log = get("gui")

PAD = 10


class App(tk.Tk):
    def __init__(self, debug: bool = False) -> None:
        super().__init__()
        paths.ensure_dirs()
        self.title(paths.APP_NAME)
        self.geometry("760x820")
        self.minsize(700, 700)

        self.events: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self.engine: Engine | None = None
        self.debug = debug
        self.training = False
        self.training_started = 0.0
        self._settings = self._load_settings()

        self.var_url = tk.StringVar(value=self._settings.get("url", ""))
        self.var_user = tk.StringVar(value=self._settings.get("username", ""))
        self.var_pass = tk.StringVar()
        self.var_remember = tk.BooleanVar(value=bool(self._settings.get("rememberSession", False)))
        self.var_headless = tk.BooleanVar(value=False)
        self.var_auth = tk.StringVar(value="Not connected")
        self.var_browser = tk.StringVar(value="Browser: stopped")
        self.var_training = tk.StringVar(value="Training: idle")
        self.var_duration = tk.StringVar(value="00:00")
        self.stats = {k: tk.StringVar(value="0") for k in
                      ("states", "elements", "paths", "high", "medium", "low")}

        self._build()
        setup(debug=debug, gui_callback=self._log_from_logger)
        log.info("%s ready. Output folder: %s", paths.APP_NAME, paths.APP_DIR)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._pump)
        self.after(500, self._tick)

    # ----------------------------------------------------------------- build
    def _build(self) -> None:
        root = ttk.Frame(self, padding=PAD)
        root.pack(fill="both", expand=True)

        # --- connection
        conn = ttk.LabelFrame(root, text="PhenomeOne", padding=PAD)
        conn.pack(fill="x")
        conn.columnconfigure(1, weight=1)
        ttk.Label(conn, text="URL").grid(row=0, column=0, sticky="w")
        ttk.Entry(conn, textvariable=self.var_url).grid(row=0, column=1, columnspan=3, sticky="ew", pady=2)
        ttk.Label(conn, text="Username").grid(row=1, column=0, sticky="w")
        ttk.Entry(conn, textvariable=self.var_user).grid(row=1, column=1, columnspan=3, sticky="ew", pady=2)
        ttk.Label(conn, text="Password").grid(row=2, column=0, sticky="w")
        ttk.Entry(conn, textvariable=self.var_pass, show="•").grid(row=2, column=1, columnspan=3,
                                                                       sticky="ew", pady=2)
        btns = ttk.Frame(conn)
        btns.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        self.b_login = ttk.Button(btns, text="LOGIN", command=self.on_login)
        self.b_login.pack(side="left")
        self.b_manual = ttk.Button(btns, text="Manual Login", command=self.on_manual_login)
        self.b_manual.pack(side="left", padx=6)
        ttk.Checkbutton(btns, text="Remember authenticated session",
                        variable=self.var_remember).pack(side="left", padx=12)
        self.cb_headless = ttk.Checkbutton(btns, text="Headless", variable=self.var_headless)
        self.cb_headless.pack(side="left")
        ttk.Label(conn, textvariable=self.var_auth, foreground="#0a6").grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(8, 0))
        ttk.Label(conn, textvariable=self.var_browser, foreground="#666").grid(
            row=5, column=0, columnspan=4, sticky="w")

        # --- discovery
        disc = ttk.LabelFrame(root, text="Discovery", padding=PAD)
        disc.pack(fill="x", pady=(PAD, 0))
        row = ttk.Frame(disc)
        row.pack(fill="x")
        self.b_scan = ttk.Button(row, text="SCAN CURRENT PAGE", command=self.on_scan)
        self.b_scan.pack(side="left")
        self.b_train = ttk.Button(row, text="START TRAINING", command=self.on_training)
        self.b_train.pack(side="left", padx=8)
        ttk.Label(row, textvariable=self.var_training).pack(side="left", padx=12)
        ttk.Label(row, textvariable=self.var_duration).pack(side="right")

        grid = ttk.Frame(disc)
        grid.pack(fill="x", pady=(PAD, 0))
        labels = [("UI States", "states"), ("Elements", "elements"), ("Navigation Paths", "paths"),
                  ("HIGH Locators", "high"), ("MEDIUM", "medium"), ("LOW", "low")]
        for i, (text, key) in enumerate(labels):
            col = i % 3
            r = i // 3
            cell = ttk.Frame(grid)
            cell.grid(row=r, column=col, sticky="w", padx=(0, 28), pady=2)
            ttk.Label(cell, textvariable=self.stats[key],
                      font=("Segoe UI", 14, "bold")).pack(side="left")
            ttk.Label(cell, text=" " + text, foreground="#666").pack(side="left")

        # --- outputs
        out = ttk.LabelFrame(root, text="Output", padding=PAD)
        out.pack(fill="x", pady=(PAD, 0))
        r1 = ttk.Frame(out)
        r1.pack(fill="x")
        ttk.Button(r1, text="View UI Map", command=lambda: self._open(paths.UI_MAP_FILE)).pack(side="left")
        ttk.Button(r1, text="View Navigation Map",
                   command=lambda: self._open(paths.NAV_GRAPH_FILE)).pack(side="left", padx=6)
        ttk.Button(r1, text="Open Report", command=lambda: self._open(paths.REPORT_FILE)).pack(side="left")
        ttk.Button(r1, text="Open Output Folder",
                   command=lambda: self._open(paths.OUTPUT_DIR)).pack(side="left", padx=6)
        ttk.Button(r1, text="Clear Saved Session", command=self.on_clear_session).pack(side="right")

        # --- activity
        act = ttk.LabelFrame(root, text="Activity", padding=PAD)
        act.pack(fill="both", expand=True, pady=(PAD, 0))
        self.text = tk.Text(act, height=14, wrap="word", state="disabled",
                            background="#101318", foreground="#dce3ea",
                            insertbackground="#dce3ea", font=("Consolas", 9), relief="flat")
        sb = ttk.Scrollbar(act, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        for tag, colour in (("INFO", "#dce3ea"), ("WARNING", "#e3b341"),
                            ("ERROR", "#f85149"), ("DEBUG", "#7d8590")):
            self.text.tag_configure(tag, foreground=colour)

    # ---------------------------------------------------------------- engine
    def _ensure_engine(self) -> Engine:
        if self.engine is None:
            self.engine = Engine(self.events, headless=self.var_headless.get(),
                                 remember_session=self.var_remember.get())
            self.engine.start()
            # The browser is launched once; headless cannot be switched after that.
            self.cb_headless.configure(state="disabled")
            self._refresh_stats(self.engine.store.counts())
        self.engine.remember_session = self.var_remember.get()
        return self.engine

    # --------------------------------------------------------------- actions
    def on_login(self) -> None:
        url = self.var_url.get().strip()
        if not url:
            messagebox.showwarning(paths.APP_NAME, "Enter the PhenomeOne URL first.")
            return
        user, pwd = self.var_user.get(), self.var_pass.get()
        if not pwd:
            messagebox.showwarning(paths.APP_NAME,
                                   "Enter a password, or use Manual Login to sign in yourself.")
            return
        register_secret(pwd)
        self._save_settings()
        eng = self._ensure_engine()
        self.var_auth.set("Authenticating...")
        eng.submit(lambda: eng.op_login(url, user, pwd), op="login")
        # The password is not kept in the GUI after submitting.
        self.var_pass.set("")

    def on_manual_login(self) -> None:
        url = self.var_url.get().strip()
        if not url:
            messagebox.showwarning(paths.APP_NAME, "Enter the PhenomeOne URL first.")
            return
        self._save_settings()
        eng = self._ensure_engine()
        eng.submit(lambda: eng.op_manual_login(url), op="manual_login")

    def on_scan(self) -> None:
        eng = self._ensure_engine()
        eng.submit(lambda: eng.op_scan(), op="scan")

    def on_training(self) -> None:
        eng = self._ensure_engine()
        if not self.training:
            eng.submit(lambda: eng.op_start_training(), op="start_training")
        else:
            eng.submit(lambda: eng.op_stop_training(), op="stop_training")

    def on_clear_session(self) -> None:
        if not messagebox.askyesno(paths.APP_NAME, "Delete the saved authenticated session?"):
            return
        SessionStore().clear()
        self.var_auth.set("Saved session cleared")

    # ----------------------------------------------------------------- pumps
    def _log_from_logger(self, level: str, message: str) -> None:
        # Called from engine/GUI threads: hand off to Tk via the event queue.
        self.events.put({"type": "log", "level": level, "msg": message})

    def _append(self, level: str, message: str) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", f"{time.strftime('%H:%M:%S')}  {message}\n",
                         level if level in ("INFO", "WARNING", "ERROR", "DEBUG") else "INFO")
        self.text.see("end")
        lines = int(self.text.index("end-1c").split(".")[0])
        if lines > 1200:
            self.text.delete("1.0", "300.0")
        self.text.configure(state="disabled")

    def _pump(self) -> None:
        try:
            while True:
                ev = self.events.get_nowait()
                self._handle(ev)
        except queue.Empty:
            pass
        self.after(120, self._pump)

    def _handle(self, ev: dict[str, Any]) -> None:
        t = ev.get("type")
        if t == "log":
            self._append(ev.get("level", "INFO"), ev.get("msg", ""))
        elif t == "log-info":
            self._append("INFO", ev.get("msg", ""))
        elif t == "status":
            if "auth" in ev:
                self.var_auth.set(str(ev["auth"]))
            if "browser" in ev:
                self.var_browser.set("Browser: running" if ev["browser"] else "Browser: stopped")
            if ev.get("origin"):
                self.var_browser.set(f"Browser: running - {ev['origin']}")
        elif t == "scan":
            r = ev.get("result") or {}
            tm = r.get("timings_ms") or {}
            self._append("INFO", f"Scan complete: state '{r.get('state_id')}' - {r.get('elements')} "
                                 f"elements ({r.get('added')} new)  [scan {tm.get('total','?')} ms: "
                                 f"collect {tm.get('collect','?')} / locators {tm.get('generate','?')} / "
                                 f"validate {tm.get('validate','?')} / merge {tm.get('merge','?')}]")
            self._refresh_stats(ev.get("counts"))
        elif t == "training":
            self.training = bool(ev.get("active"))
            if self.training:
                self.training_started = time.time()
                self.var_training.set("Training: ACTIVE")
                self.b_train.configure(text="STOP TRAINING")
                self.b_scan.configure(state="disabled")
            else:
                self.var_training.set("Training: stopped")
                self.b_train.configure(text="START TRAINING")
                self.b_scan.configure(state="normal")
                self._refresh_stats(ev.get("counts"))
        elif t == "training-progress":
            self._refresh_stats(ev.get("counts"))
        elif t == "error":
            self._append("ERROR", f"{ev.get('op')}: {ev.get('msg')}")
        elif t == "page-closed":
            self._append("WARNING", "The browser page was closed.")

    def _refresh_stats(self, counts: dict[str, Any] | None) -> None:
        if not counts:
            return
        conf = counts.get("confidence") or {}
        self.stats["states"].set(str(counts.get("states", 0)))
        self.stats["elements"].set(str(counts.get("elements", 0)))
        self.stats["paths"].set(str(counts.get("navigationPaths", 0)))
        self.stats["high"].set(str(conf.get("HIGH", 0)))
        self.stats["medium"].set(str(conf.get("MEDIUM", 0)))
        self.stats["low"].set(str(conf.get("LOW", 0)))

    def _tick(self) -> None:
        if self.training and self.training_started:
            secs = int(time.time() - self.training_started)
            self.var_duration.set(f"{secs // 60:02d}:{secs % 60:02d}")
        self.after(500, self._tick)

    # ------------------------------------------------------------- settings
    @staticmethod
    def _load_settings() -> dict[str, Any]:
        try:
            if paths.SETTINGS_FILE.is_file():
                return json.loads(paths.SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_settings(self) -> None:
        # Credentials are NEVER written here - URL, username and flags only.
        data = {
            "url": self.var_url.get().strip(),
            "username": self.var_user.get().strip(),
            "rememberSession": bool(self.var_remember.get()),
        }
        try:
            paths.ensure_dirs()
            paths.SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            log.warning("Could not save settings: %s", exc)

    # ---------------------------------------------------------------- misc
    def _open(self, target) -> None:
        if not os.path.exists(target):
            messagebox.showinfo(paths.APP_NAME,
                                f"{os.path.basename(str(target))} does not exist yet.\n\n"
                                "Run Scan Current Page or a training session first.")
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(target))       # noqa: S606 - user-initiated
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as exc:
            messagebox.showerror(paths.APP_NAME, f"Could not open {target}:\n{exc}")

    def _on_close(self) -> None:
        if self.training and not messagebox.askyesno(
                paths.APP_NAME, "Training is still active. Stop training and exit?"):
            return
        self._save_settings()
        if self.engine is not None:
            self._append("INFO", "Shutting down...")
            self.update_idletasks()
            self.engine.shutdown_blocking()
        self.destroy()


def run(debug: bool = False) -> int:
    app = App(debug=debug)
    app.mainloop()
    return 0
