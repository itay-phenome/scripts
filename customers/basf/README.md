# 📁 customers/basf

Unity deployment scripts for the **BASF DEV** environment.

---

## basf-dev_job.sh
Installs and configures the Unity **Job Server** for BASF DEV.
Customer-specific: S3 buckets, RDS endpoint, AWS region, SQS queue.

**Run:**
```bash
bash basf-dev_job.sh
```

---

## basf-dev_web.sh
Installs and configures the Unity **Web Server** for BASF DEV.
Customer-specific: S3 buckets, RDS endpoint, AWS region, Apache vhost config.

**Run:**
```bash
bash basf-dev_web.sh
```
