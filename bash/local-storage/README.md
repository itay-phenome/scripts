# 📁 bash/local-storage

Generic Unity installation scripts for **local storage** environments (non-S3).
Use these as a base template when deploying Unity with local disk storage instead of S3.

---

## job_local_storage.sh
Installs and configures the Unity **Job Server** with local storage.

**Run:**
```bash
bash job_local_storage.sh
```

---

## web_local_storage.sh
Installs and configures the Unity **Web Server** with local storage.

**Run:**
```bash
bash web_local_storage.sh
```

---

## job_local_storage_updated.sh
Updated version of `job_local_storage.sh` — includes Ubuntu 22.04 compatibility fixes and improved service management.

**Run:**
```bash
bash job_local_storage_updated.sh
```

---

## web_local_storage_updated.sh
Updated version of `web_local_storage.sh` — includes Ubuntu 22.04 compatibility fixes and improved Apache/Waitress setup.

**Run:**
```bash
bash web_local_storage_updated.sh
```

---

> 💡 For customer-specific versions of these scripts, see the `customers/` folder.
