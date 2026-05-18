# 📁 bash/graphviz

Scripts for installing and removing Graphviz on Ubuntu servers.

---

## graphviz-update.sh
Builds and installs Graphviz from source (v12.2.0).
Removes any existing APT version first to avoid conflicts.

**Run:**
```bash
bash graphviz-update.sh
```
> Installs to: `/usr/local/bin/dot`
> Log: `/var/log/graphviz-install-DATE.log`

To change the version, edit at the top of the script:
```bash
INSTALL_VERSION="12.2.0"
```

---

## graphviz-remove.sh
Completely removes Graphviz — APT packages, manually installed binaries, libraries, and headers.

**Run:**
```bash
bash graphviz-remove.sh
```
> Log: `/var/log/graphviz-removal-DATE.log`
