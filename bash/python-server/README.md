# 📁 bash/python-server

Watchdog and setup scripts for the Unity Waitress (Python) web server.

---

## waitress-server-watchdog.sh
Checks if `waitress_server.py` is running. If not, starts it using the Python virtual environment (`.venv`).
Intended to run as a cron job every few minutes.

**Cron setup:**
```
*/5 * * * * /path/to/waitress-server-watchdog.sh
```
> Log: `/var/log/waitress-server-watchdog.log`

---

## conda-waitress-server-watchdog.sh
Same as above but uses a **Conda environment** instead of `.venv`.
Use this version if the server was set up with `conda-waitress-install.sh`.

**Cron setup:**
```
*/5 * * * * /path/to/conda-waitress-server-watchdog.sh
```
> Log: `/var/log/conda-waitress-server-watchdog.log`

---

## conda-waitress-install.sh
Sets up (or resets) the Conda environment for the Waitress server.
Removes the old environment and creates a new one from `environment.yml`.

**Run:**
```bash
bash conda-waitress-install.sh
```
> Requires: Miniconda at `/opt/miniconda3` and `environment.yml` in the project directory.
