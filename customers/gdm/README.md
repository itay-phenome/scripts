# 📁 customers/gdm

Unity deployment and configuration scripts for the **GDM** environment.

---

## job_local_storage.sh
Installs and configures the Unity **Job Server** for GDM, including local storage setup.

**Run:**
```bash
bash job_local_storage.sh
```

---

## web_local_storage.sh
Installs and configures the Unity **Web Server** for GDM, including local storage setup.

**Run:**
```bash
bash web_local_storage.sh
```

---

## job_server.conf
Job Server configuration file for GDM.
Contains worker count, queue settings, and environment-specific parameters.

> Copy to the appropriate config directory before starting the Job Server.
