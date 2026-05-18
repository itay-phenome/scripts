# 📁 customers/enza-zaden

Unity deployment scripts for the **Enza Zaden** environment.

---

## enza_job_test.sh
Installs and configures the Unity **Job Server** for Enza Zaden (test environment).
Customer-specific: S3 buckets, RDS endpoint, AWS region, SQS queue.

**Run:**
```bash
bash enza_job_test.sh
```

---

## enza_web.sh
Installs and configures the Unity **Web Server** for Enza Zaden.
Customer-specific: S3 buckets, RDS endpoint, AWS region, Apache vhost config.

**Run:**
```bash
bash enza_web.sh
```
