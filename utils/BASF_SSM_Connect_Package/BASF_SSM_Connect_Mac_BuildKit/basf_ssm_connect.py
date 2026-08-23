"""
BASF SSM Connect
================
A small GUI wrapper around the "Connecting to BASF Servers via AWS SSM
Session Manager" guide. Lets you manage AWS CLI profiles, browse/refresh
server inventories per environment/account, and connect with one click by
opening a new PowerShell window running the right `aws ssm start-session`
command.

Requirements (must already be installed per the setup guide):
  - AWS CLI v2  (aws --version)
  - Session Manager Plugin  (session-manager-plugin)

Run with:  pythonw basf_ssm_connect.py   (no console window)
       or: python basf_ssm_connect.py    (console window stays open for errors)
"""

import configparser
import datetime
import json
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

CONFIG_PATH = Path.home() / ".basf_ssm_connect" / "config.json"
AWS_DIR = Path.home() / ".aws"
CREDENTIALS_PATH = AWS_DIR / "credentials"
AWS_CONFIG_PATH = AWS_DIR / "config"

IS_WINDOWS = sys.platform == "win32"

CREATE_NEW_CONSOLE = 0x00000010  # subprocess.CREATE_NEW_CONSOLE, spelled out for clarity
CREATE_NO_WINDOW = 0x08000000  # subprocess.CREATE_NO_WINDOW - suppress the console AWS CLI would otherwise spawn


def _bg_kwargs():
    """Extra subprocess kwargs to suppress a console popping up. Windows-only concept."""
    return {"creationflags": CREATE_NO_WINDOW} if IS_WINDOWS else {}

# Baked-in inventory from the setup guide (used until a Refresh is run, or
# until the user removes/edits it).
DEFAULT_ENVIRONMENTS = {
    "DEV": {
        "profile": "basf_dev",
        "region": "us-east-1",
        "account": "891376961316",
        "servers": [
            {"name": "Phen_Basf_Dev_Web_Virginia", "id": "i-09501fb8a153b5c4d", "type": "x8i.xlarge", "state": "running", "ip": "10.193.162.73"},
            {"name": "Phen_Basf_Dev_Job_VIRGINIA", "id": "i-073c3cdf5ff77cb0c", "type": "x8i.large", "state": "running", "ip": "10.193.162.92"},
            {"name": "Phen_Basf_Dev_Logstash_VIRGINIA", "id": "i-06fb6679e91bdbaf0", "type": "m7i.large", "state": "running", "ip": "10.193.162.72"},
            {"name": "phenome-docker-env", "id": "i-0d7c75a8e25582957", "type": "m6i.xlarge", "state": "running", "ip": "10.193.161.219"},
        ],
    },
    "QA": {
        "profile": "basf_qa",
        "region": "us-east-1",
        "account": "589860219747",
        "servers": [
            {"name": "basf_qual_web", "id": "i-0a31308a77baf2d12", "type": "m7i.2xlarge", "state": "running", "ip": "10.193.162.23"},
            {"name": "basf_qual_job", "id": "i-012f4e634c01672f2", "type": "m7i.2xlarge", "state": "running", "ip": "10.193.162.25"},
            {"name": "basf_qual_logstash", "id": "i-0c0efcd4a4b690186", "type": "m7i.xlarge", "state": "running", "ip": "10.193.162.10"},
        ],
    },
    "Migration": {
        "profile": "basf_mig",
        "region": "us-east-1",
        "account": "942237908740",
        "servers": [
            {"name": "basf_mig_web", "id": "i-0ef421b74b2fa3767", "type": "c7i-flex.xlarge", "state": "running", "ip": "10.193.180.69"},
            {"name": "basf_mig_job", "id": "i-0618e844b93c29243", "type": "r6i.xlarge", "state": "running", "ip": "10.193.180.70"},
        ],
    },
    "PROD": {
        "profile": "basf_prod",
        "region": "us-east-1",
        "account": "439763252024",
        "servers": [
            {"name": "basf-prod-web", "id": "i-05b6924480fdce479", "type": "m7i.xlarge", "state": "running", "ip": "10.193.160.38"},
            {"name": "basf-prod-logstash", "id": "i-0d75c3fda96f39566", "type": "m7i.xlarge", "state": "running", "ip": "10.193.160.62"},
            {"name": "basf-prod-job", "id": "i-0f972ee9bb6137b19", "type": "m7i.xlarge", "state": "running", "ip": "10.193.161.232"},
        ],
    },
}

DESCRIBE_QUERY = (
    "Reservations[].Instances[].{"
    "Name:Tags[?Key=='Name']|[0].Value,"
    "InstanceId:InstanceId,"
    "Type:InstanceType,"
    "State:State.Name,"
    "PrivateIP:PrivateIpAddress}"
)


# --------------------------------------------------------------------------
# Config persistence (environments + which built-ins the user deleted)
# --------------------------------------------------------------------------

def load_config():
    saved = {}
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except (json.JSONDecodeError, OSError):
            saved = {}

    deleted_builtin = set(saved.get("deleted_builtin", []))
    saved_environments = saved.get("environments", {})

    environments = {}

    # Built-ins first (unless the user explicitly removed them).
    for env_name, defaults in DEFAULT_ENVIRONMENTS.items():
        if env_name in deleted_builtin:
            continue
        entry = {
            "profile": defaults["profile"],
            "region": defaults["region"],
            "account": defaults["account"],
            "servers": list(defaults["servers"]),
        }
        overrides = saved_environments.get(env_name, {})
        entry["profile"] = overrides.get("profile", entry["profile"])
        entry["region"] = overrides.get("region", entry["region"])
        if overrides.get("servers"):
            entry["servers"] = overrides["servers"]
        environments[env_name] = entry

    # Then any custom environments the user added.
    for env_name, entry in saved_environments.items():
        if env_name in DEFAULT_ENVIRONMENTS:
            continue
        environments[env_name] = {
            "profile": entry.get("profile", ""),
            "region": entry.get("region", ""),
            "account": entry.get("account", ""),
            "servers": entry.get("servers", []),
        }

    return environments, deleted_builtin


def save_config(environments, deleted_builtin):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "environments": environments,
        "deleted_builtin": sorted(deleted_builtin),
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


# --------------------------------------------------------------------------
# AWS CLI profile helpers
# --------------------------------------------------------------------------

def list_aws_profiles():
    if not shutil.which("aws"):
        return []
    try:
        result = subprocess.run(
            ["aws", "configure", "list-profiles"],
            capture_output=True, text=True, timeout=15, **_bg_kwargs(),
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def get_profile_field(profile, key):
    try:
        result = subprocess.run(
            ["aws", "configure", "get", key, "--profile", profile],
            capture_output=True, text=True, timeout=15, **_bg_kwargs(),
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def set_profile_field(profile, key, value):
    result = subprocess.run(
        ["aws", "configure", "set", key, value, "--profile", profile],
        capture_output=True, text=True, timeout=15, **_bg_kwargs(),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Failed to set {key} for profile {profile}.")


def backup_aws_files():
    """Copy credentials/config once per call before a destructive edit."""
    AWS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    for path in (CREDENTIALS_PATH, AWS_CONFIG_PATH):
        if path.exists():
            shutil.copy2(path, path.with_name(path.name + f".basf-ssm-connect.bak-{stamp}"))


def remove_aws_profile(profile_name):
    """Removes a profile's sections from ~/.aws/credentials and ~/.aws/config."""
    backup_aws_files()

    creds = configparser.ConfigParser()
    if CREDENTIALS_PATH.exists():
        creds.read(CREDENTIALS_PATH)
    if creds.has_section(profile_name):
        creds.remove_section(profile_name)
        with open(CREDENTIALS_PATH, "w", encoding="utf-8") as f:
            creds.write(f)

    cfg = configparser.ConfigParser()
    if AWS_CONFIG_PATH.exists():
        cfg.read(AWS_CONFIG_PATH)
    config_section = "default" if profile_name == "default" else f"profile {profile_name}"
    if cfg.has_section(config_section):
        cfg.remove_section(config_section)
        with open(AWS_CONFIG_PATH, "w", encoding="utf-8") as f:
            cfg.write(f)


# --------------------------------------------------------------------------
# Profile add/edit dialog
# --------------------------------------------------------------------------

class ProfileDialog(tk.Toplevel):
    def __init__(self, parent, existing_name=None, prefill=None):
        super().__init__(parent)
        self.title("Edit Profile" if existing_name else "New Profile")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None
        prefill = prefill or {}

        pad = {"padx": 8, "pady": 5}
        row = 0

        ttk.Label(self, text="Profile name:").grid(row=row, column=0, sticky="w", **pad)
        self.name_var = tk.StringVar(value=existing_name or "")
        name_entry = ttk.Entry(self, textvariable=self.name_var, width=30)
        name_entry.grid(row=row, column=1, columnspan=2, sticky="we", **pad)
        if existing_name:
            name_entry.state(["disabled"])
        row += 1

        ttk.Label(self, text="Access Key ID:").grid(row=row, column=0, sticky="w", **pad)
        self.access_key_var = tk.StringVar(value=prefill.get("access_key", ""))
        access_key_entry = ttk.Entry(self, textvariable=self.access_key_var, width=30)
        access_key_entry.grid(row=row, column=1, columnspan=2, sticky="we", **pad)
        row += 1

        ttk.Label(self, text="Secret Access Key:").grid(row=row, column=0, sticky="w", **pad)
        self.secret_var = tk.StringVar()
        self.secret_entry = ttk.Entry(self, textvariable=self.secret_var, width=30, show="*")
        self.secret_entry.grid(row=row, column=1, sticky="we", **pad)
        self.show_secret_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self, text="Show", variable=self.show_secret_var, command=self._toggle_secret_visibility
        ).grid(row=row, column=2, sticky="w")
        row += 1
        if existing_name:
            ttk.Label(
                self, text="Leave blank to keep the existing secret key unchanged.",
                foreground="#666666", font=("", 8),
            ).grid(row=row, column=0, columnspan=3, sticky="w", padx=8)
            row += 1

        ttk.Label(self, text="Region:").grid(row=row, column=0, sticky="w", **pad)
        self.region_var = tk.StringVar(value=prefill.get("region", "us-east-1"))
        ttk.Entry(self, textvariable=self.region_var, width=30).grid(row=row, column=1, columnspan=2, sticky="we", **pad)
        row += 1

        ttk.Label(self, text="Output format:").grid(row=row, column=0, sticky="w", **pad)
        self.output_var = tk.StringVar(value=prefill.get("output", "json"))
        ttk.Combobox(
            self, textvariable=self.output_var, values=["json", "yaml", "yaml-stream", "text", "table"],
            width=27, state="readonly",
        ).grid(row=row, column=1, columnspan=2, sticky="we", **pad)
        row += 1

        btns = ttk.Frame(self)
        btns.grid(row=row, column=0, columnspan=3, pady=(10, 8))
        ttk.Button(btns, text="Save", command=self._on_save).pack(side="left", padx=6)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=6)

        if existing_name:
            access_key_entry.focus_set()
        else:
            name_entry.focus_set()

    def _toggle_secret_visibility(self):
        self.secret_entry.configure(show="" if self.show_secret_var.get() else "*")

    def _on_save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing name", "Profile name is required.", parent=self)
            return
        self.result = {
            "name": name,
            "access_key": self.access_key_var.get().strip(),
            "secret_key": self.secret_var.get().strip(),
            "region": self.region_var.get().strip(),
            "output": self.output_var.get().strip() or "json",
        }
        self.destroy()


# --------------------------------------------------------------------------
# AWS Profiles tab
# --------------------------------------------------------------------------

class ProfilesTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app

        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 8))
        ttk.Button(top, text="New Profile", command=self.new_profile).pack(side="left")
        ttk.Button(top, text="Edit Selected", command=self.edit_profile).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Remove Selected", command=self.remove_profile).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Verify Selected", command=self.verify_profile).pack(side="left", padx=(8, 0))
        self.refresh_btn = ttk.Button(top, text="Refresh list", command=self.refresh)
        self.refresh_btn.pack(side="left", padx=(8, 0))

        columns = ("name", "access_key", "region", "output")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=10, selectmode="browse")
        headings = {"name": "Profile", "access_key": "Access Key ID (masked)", "region": "Region", "output": "Output"}
        widths = {"name": 160, "access_key": 220, "region": 120, "output": 90}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")
        self.tree.pack(fill="both", expand=True)

        ttk.Label(
            self,
            text="Secret access keys are never displayed. Changes are made via 'aws configure set' "
                 "(add/edit) or by editing ~/.aws/credentials and ~/.aws/config directly (remove) — "
                 "a timestamped backup of both files is made before any removal.",
            foreground="#666666", wraplength=700, justify="left",
        ).pack(fill="x", pady=(8, 0))

        self.after(100, self.refresh)

    def selected_profile(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self.tree.item(sel[0], "values")[0]

    def refresh(self):
        if not shutil.which("aws"):
            self.app.set_status("AWS CLI not found — cannot list profiles.")
            return
        self.refresh_btn.state(["disabled"])
        self.app.set_status("Loading AWS profiles...")

        def worker():
            names = list_aws_profiles()
            rows = []
            for name in names:
                access_key = get_profile_field(name, "aws_access_key_id")
                masked = ("*" * max(len(access_key) - 4, 0) + access_key[-4:]) if access_key else ""
                region = get_profile_field(name, "region")
                output = get_profile_field(name, "output")
                rows.append((name, masked, region, output))
            self.after(0, lambda: self._populate(rows))

        threading.Thread(target=worker, daemon=True).start()

    def _populate(self, rows):
        self.refresh_btn.state(["!disabled"])
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            self.tree.insert("", "end", values=row)
        self.app.set_status(f"Loaded {len(rows)} AWS profile(s).")
        self.app.refresh_profile_choices()

    def new_profile(self):
        dialog = ProfileDialog(self.app)
        self.wait_window(dialog)
        if not dialog.result:
            return
        data = dialog.result
        if not shutil.which("aws"):
            messagebox.showerror("AWS CLI not found", "Install the AWS CLI before creating profiles.")
            return
        try:
            if data["access_key"]:
                set_profile_field(data["name"], "aws_access_key_id", data["access_key"])
            if data["secret_key"]:
                set_profile_field(data["name"], "aws_secret_access_key", data["secret_key"])
            if data["region"]:
                set_profile_field(data["name"], "region", data["region"])
            set_profile_field(data["name"], "output", data["output"])
        except RuntimeError as e:
            messagebox.showerror("Failed to save profile", str(e))
            return
        self.app.set_status(f"Profile '{data['name']}' saved.")
        self.refresh()

    def edit_profile(self):
        name = self.selected_profile()
        if not name:
            messagebox.showinfo("No profile selected", "Select a profile in the list first.")
            return
        prefill = {
            "access_key": get_profile_field(name, "aws_access_key_id"),
            "region": get_profile_field(name, "region"),
            "output": get_profile_field(name, "output") or "json",
        }
        dialog = ProfileDialog(self.app, existing_name=name, prefill=prefill)
        self.wait_window(dialog)
        if not dialog.result:
            return
        data = dialog.result
        try:
            if data["access_key"]:
                set_profile_field(name, "aws_access_key_id", data["access_key"])
            if data["secret_key"]:
                set_profile_field(name, "aws_secret_access_key", data["secret_key"])
            if data["region"]:
                set_profile_field(name, "region", data["region"])
            set_profile_field(name, "output", data["output"])
        except RuntimeError as e:
            messagebox.showerror("Failed to update profile", str(e))
            return
        self.app.set_status(f"Profile '{name}' updated.")
        self.refresh()

    def remove_profile(self):
        name = self.selected_profile()
        if not name:
            messagebox.showinfo("No profile selected", "Select a profile in the list first.")
            return
        if not messagebox.askyesno(
            "Remove profile",
            f"Remove profile '{name}' from ~/.aws/credentials and ~/.aws/config?\n\n"
            "A timestamped backup of both files will be saved first. This cannot be undone "
            "from within this app.",
        ):
            return
        try:
            remove_aws_profile(name)
        except OSError as e:
            messagebox.showerror("Failed to remove profile", str(e))
            return
        self.app.set_status(f"Profile '{name}' removed (backup saved next to the original files).")
        self.refresh()

    def verify_profile(self):
        name = self.selected_profile()
        if not name:
            messagebox.showinfo("No profile selected", "Select a profile in the list first.")
            return
        if not shutil.which("aws"):
            messagebox.showerror("AWS CLI not found", "Install the AWS CLI first.")
            return
        self.app.set_status(f"Verifying profile '{name}'...")

        def worker():
            try:
                result = subprocess.run(
                    ["aws", "sts", "get-caller-identity", "--profile", name, "--output", "json"],
                    capture_output=True, text=True, timeout=20, **_bg_kwargs(),
                )
            except (subprocess.TimeoutExpired, OSError) as e:
                self.after(0, lambda: messagebox.showerror("Verify failed", str(e)))
                return
            if result.returncode != 0:
                self.after(0, lambda: messagebox.showerror("Verify failed", result.stderr.strip() or "Unknown error."))
                return
            try:
                identity = json.loads(result.stdout)
            except json.JSONDecodeError:
                self.after(0, lambda: messagebox.showerror("Verify failed", "Could not parse AWS CLI output."))
                return
            msg = (
                f"Profile: {name}\n"
                f"Account: {identity.get('Account', '')}\n"
                f"User ARN: {identity.get('Arn', '')}"
            )
            self.after(0, lambda: messagebox.showinfo("Profile verified", msg))
            self.after(0, lambda: self.app.set_status(f"Profile '{name}' verified: account {identity.get('Account', '')}."))

        threading.Thread(target=worker, daemon=True).start()


# --------------------------------------------------------------------------
# Add-environment dialog
# --------------------------------------------------------------------------

class AddEnvironmentDialog(tk.Toplevel):
    def __init__(self, parent, existing_names, profile_choices):
        super().__init__(parent)
        self.title("Add Environment")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None
        self.existing_names = {n.lower() for n in existing_names}

        pad = {"padx": 8, "pady": 5}
        ttk.Label(self, text="Environment name:").grid(row=0, column=0, sticky="w", **pad)
        self.name_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.name_var, width=28).grid(row=0, column=1, sticky="we", **pad)

        ttk.Label(self, text="AWS profile:").grid(row=1, column=0, sticky="w", **pad)
        self.profile_var = tk.StringVar()
        ttk.Combobox(self, textvariable=self.profile_var, values=profile_choices, width=25).grid(row=1, column=1, sticky="we", **pad)

        ttk.Label(self, text="Region:").grid(row=2, column=0, sticky="w", **pad)
        self.region_var = tk.StringVar(value="us-east-1")
        ttk.Entry(self, textvariable=self.region_var, width=28).grid(row=2, column=1, sticky="we", **pad)

        ttk.Label(self, text="Account ID (optional):").grid(row=3, column=0, sticky="w", **pad)
        self.account_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.account_var, width=28).grid(row=3, column=1, sticky="we", **pad)

        btns = ttk.Frame(self)
        btns.grid(row=4, column=0, columnspan=2, pady=(10, 8))
        ttk.Button(btns, text="Add", command=self._on_add).pack(side="left", padx=6)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=6)

    def _on_add(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing name", "Environment name is required.", parent=self)
            return
        if name.lower() in self.existing_names:
            messagebox.showwarning("Duplicate name", f"An environment named '{name}' already exists.", parent=self)
            return
        self.result = {
            "name": name,
            "profile": self.profile_var.get().strip(),
            "region": self.region_var.get().strip() or "us-east-1",
            "account": self.account_var.get().strip(),
        }
        self.destroy()


# --------------------------------------------------------------------------
# Environment tab (server inventory + connect)
# --------------------------------------------------------------------------

class EnvironmentTab(ttk.Frame):
    def __init__(self, parent, app, env_name, env_data, is_builtin):
        super().__init__(parent, padding=10)
        self.app = app
        self.env_name = env_name
        self.env_data = env_data
        self.is_builtin = is_builtin

        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 8))

        ttk.Label(top, text="Profile:").grid(row=0, column=0, sticky="w")
        self.profile_var = tk.StringVar(value=env_data["profile"])
        self.profile_combo = ttk.Combobox(top, textvariable=self.profile_var, width=16, values=self.app.profile_names())
        self.profile_combo.grid(row=0, column=1, padx=(4, 16))

        ttk.Label(top, text="Region:").grid(row=0, column=2, sticky="w")
        self.region_var = tk.StringVar(value=env_data["region"])
        ttk.Entry(top, textvariable=self.region_var, width=14).grid(row=0, column=3, padx=(4, 16))

        account_label = env_data.get("account") or "—"
        ttk.Label(top, text=f"Account: {account_label}").grid(row=0, column=4, padx=(0, 16))

        ttk.Button(top, text="Save profile/region", command=self.save_settings).grid(row=0, column=5, padx=(0, 8))
        ttk.Button(top, text="Remove environment", command=self.remove_self).grid(row=0, column=6)

        filter_row = ttk.Frame(self)
        filter_row.pack(fill="x", pady=(0, 8))
        ttk.Label(filter_row, text="List instances:").pack(side="left")
        self.state_filter_var = tk.StringVar(value="All states")
        ttk.Combobox(
            filter_row, textvariable=self.state_filter_var, values=["All states", "Running only"],
            width=14, state="readonly",
        ).pack(side="left", padx=(4, 16))
        self.refresh_btn = ttk.Button(filter_row, text="Refresh from AWS", command=self.refresh_from_aws)
        self.refresh_btn.pack(side="left")

        columns = ("name", "id", "type", "state", "ip")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=9, selectmode="browse")
        headings = {"name": "Name", "id": "Instance ID", "type": "Type", "state": "State", "ip": "Private IP"}
        widths = {"name": 220, "id": 170, "type": 100, "state": 80, "ip": 120}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(0, 8))
        self.tree.bind("<Double-1>", lambda e: self.connect())

        bottom = ttk.Frame(self)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Connect", command=self.connect).pack(side="left")
        ttk.Button(bottom, text="Copy command", command=self.copy_command).pack(side="left", padx=(8, 0))

        adhoc = ttk.Frame(self)
        adhoc.pack(fill="x", pady=(8, 0))
        ttk.Label(adhoc, text="Connect by Instance ID (not in list above):").pack(side="left")
        self.adhoc_id_var = tk.StringVar()
        ttk.Entry(adhoc, textvariable=self.adhoc_id_var, width=22).pack(side="left", padx=(6, 6))
        ttk.Button(adhoc, text="Connect", command=self.connect_adhoc).pack(side="left")

        self.populate_tree(env_data["servers"])

    def populate_tree(self, servers):
        self.tree.delete(*self.tree.get_children())
        for s in servers:
            self.tree.insert("", "end", values=(s.get("name") or "(unnamed)", s["id"], s.get("type", ""), s.get("state", ""), s.get("ip", "")))

    def refresh_profile_choices(self):
        self.profile_combo.configure(values=self.app.profile_names())

    def save_settings(self):
        self.env_data["profile"] = self.profile_var.get().strip()
        self.env_data["region"] = self.region_var.get().strip()
        self.app.persist()
        self.app.set_status(f"[{self.env_name}] Profile/region saved.")

    def remove_self(self):
        if not messagebox.askyesno(
            "Remove environment",
            f"Remove the '{self.env_name}' tab and its cached server list from this app?\n\n"
            "This does not touch AWS itself, and a built-in environment can be re-added later.",
        ):
            return
        self.app.remove_environment(self.env_name)

    def selected_server(self):
        sel = self.tree.selection()
        if not sel:
            return None
        values = self.tree.item(sel[0], "values")
        return {"name": values[0], "id": values[1]}

    def _launch_session(self, instance_id, label):
        if not shutil.which("aws"):
            messagebox.showerror(
                "AWS CLI not found",
                "The 'aws' command was not found on your PATH.\n\n"
                "Install the AWS CLI and Session Manager Plugin per the setup guide, "
                "then restart this app.",
            )
            return
        profile = self.profile_var.get().strip()
        region = self.region_var.get().strip()
        cmd = f"aws ssm start-session --target {instance_id} --region {region} --profile {profile}"
        try:
            if IS_WINDOWS:
                subprocess.Popen(
                    ["powershell.exe", "-NoExit", "-Command", cmd],
                    creationflags=CREATE_NEW_CONSOLE,
                )
            else:
                escaped = cmd.replace("\\", "\\\\").replace('"', '\\"')
                subprocess.Popen([
                    "osascript",
                    "-e", 'tell application "Terminal" to activate',
                    "-e", f'tell application "Terminal" to do script "{escaped}"',
                ])
            self.app.set_status(f"[{self.env_name}] Connecting to {label}...")
        except OSError as e:
            messagebox.showerror("Failed to launch PowerShell", str(e))

    def connect(self):
        server = self.selected_server()
        if not server:
            messagebox.showinfo("No server selected", "Select a server in the list first.")
            return
        self._launch_session(server["id"], f"{server['name']} ({server['id']})")

    def connect_adhoc(self):
        instance_id = self.adhoc_id_var.get().strip()
        if not instance_id:
            messagebox.showinfo("No Instance ID", "Enter an Instance ID first (e.g. i-0123456789abcdef0).")
            return
        self._launch_session(instance_id, instance_id)

    def copy_command(self):
        server = self.selected_server()
        if not server:
            messagebox.showinfo("No server selected", "Select a server in the list first.")
            return
        profile = self.profile_var.get().strip()
        region = self.region_var.get().strip()
        cmd = f"aws ssm start-session --target {server['id']} --region {region} --profile {profile}"
        self.clipboard_clear()
        self.clipboard_append(cmd)
        self.app.set_status(f"[{self.env_name}] Command copied to clipboard.")

    def refresh_from_aws(self):
        if not shutil.which("aws"):
            messagebox.showerror(
                "AWS CLI not found",
                "The 'aws' command was not found on your PATH.\n\n"
                "Install the AWS CLI per the setup guide, then restart this app.",
            )
            return

        profile = self.profile_var.get().strip()
        region = self.region_var.get().strip()
        running_only = self.state_filter_var.get() == "Running only"
        self.refresh_btn.state(["disabled"])
        self.app.set_status(f"[{self.env_name}] Querying AWS ({profile} / {region})...")

        def worker():
            cmd = [
                "aws", "ec2", "describe-instances",
                "--profile", profile,
                "--region", region,
                "--query", DESCRIBE_QUERY,
                "--output", "json",
            ]
            if running_only:
                cmd[3:3] = ["--filters", "Name=instance-state-name,Values=running"]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, **_bg_kwargs())
            except subprocess.TimeoutExpired:
                self.after(0, lambda: self._refresh_failed("Request timed out after 30s."))
                return
            except OSError as e:
                self.after(0, lambda: self._refresh_failed(str(e)))
                return

            if result.returncode != 0:
                self.after(0, lambda: self._refresh_failed(result.stderr.strip() or "Unknown AWS CLI error."))
                return

            try:
                raw = json.loads(result.stdout)
            except json.JSONDecodeError:
                self.after(0, lambda: self._refresh_failed("Could not parse AWS CLI output."))
                return

            servers = sorted(
                (
                    {
                        "name": r.get("Name") or "(unnamed)",
                        "id": r["InstanceId"],
                        "type": r.get("Type", ""),
                        "state": r.get("State", ""),
                        "ip": r.get("PrivateIP") or "",
                    }
                    for r in raw
                ),
                key=lambda s: s["name"],
            )
            self.after(0, lambda: self._refresh_succeeded(servers))

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_succeeded(self, servers):
        self.refresh_btn.state(["!disabled"])
        self.env_data["servers"] = servers
        self.populate_tree(servers)
        self.app.persist()
        self.app.set_status(f"[{self.env_name}] Refreshed: {len(servers)} server(s) found.")

    def _refresh_failed(self, message):
        self.refresh_btn.state(["!disabled"])
        self.app.set_status(f"[{self.env_name}] Refresh failed.")
        messagebox.showerror("Refresh failed", message)


# --------------------------------------------------------------------------
# Main app
# --------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BASF SSM Connect")
        self.geometry("820x480")
        self.minsize(700, 400)

        self.environments, self.deleted_builtin = load_config()

        toolbar = ttk.Frame(self, padding=(10, 8, 10, 0))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="+ Add Environment", command=self.prompt_add_environment).pack(side="left")

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(6, 0))

        self.profiles_tab = ProfilesTab(self.notebook, self)
        self.notebook.add(self.profiles_tab, text="AWS Profiles")

        self.env_tabs = {}
        for env_name, env_data in self.environments.items():
            self._add_environment_tab(env_name, env_data)

        self.status_var = tk.StringVar(value="Ready.")
        status_bar = ttk.Label(self, textvariable=self.status_var, anchor="w", relief="sunken", padding=(6, 3))
        status_bar.pack(fill="x", side="bottom")

    def _add_environment_tab(self, env_name, env_data):
        is_builtin = env_name in DEFAULT_ENVIRONMENTS
        tab = EnvironmentTab(self.notebook, self, env_name, env_data, is_builtin)
        self.notebook.add(tab, text=env_name)
        self.env_tabs[env_name] = tab
        return tab

    def profile_names(self):
        return list_aws_profiles()

    def refresh_profile_choices(self):
        for tab in self.env_tabs.values():
            tab.refresh_profile_choices()

    def prompt_add_environment(self):
        dialog = AddEnvironmentDialog(self, self.environments.keys(), self.profile_names())
        self.wait_window(dialog)
        if not dialog.result:
            return
        data = dialog.result
        env_data = {"profile": data["profile"], "region": data["region"], "account": data["account"], "servers": []}
        self.environments[data["name"]] = env_data
        tab = self._add_environment_tab(data["name"], env_data)
        self.notebook.select(tab)
        self.persist()
        self.set_status(f"Environment '{data['name']}' added.")

    def remove_environment(self, env_name):
        tab = self.env_tabs.pop(env_name, None)
        if tab is not None:
            self.notebook.forget(tab)
        self.environments.pop(env_name, None)
        if env_name in DEFAULT_ENVIRONMENTS:
            self.deleted_builtin.add(env_name)
        self.persist()
        self.set_status(f"Environment '{env_name}' removed.")

    def set_status(self, message):
        self.status_var.set(message)

    def persist(self):
        save_config(self.environments, self.deleted_builtin)


if __name__ == "__main__":
    App().mainloop()
