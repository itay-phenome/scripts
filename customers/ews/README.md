# 📁 customers/ews

Unity deployment scripts for the **EWS (Mumbai)** environment.

---

## EWS_MUM_job.sh
Installs and configures the Unity **Job Server** for EWS Mumbai.
Customer-specific: S3 buckets, RDS endpoint, ap-south-1 region, SQS queue.

**Run:**
```bash
bash EWS_MUM_job.sh
```

---

## EWS_MUM_web.sh
Installs and configures the Unity **Web Server** for EWS Mumbai.
Customer-specific: S3 buckets, RDS endpoint, ap-south-1 region, Apache vhost config.

**Run:**
```bash
bash EWS_MUM_web.sh
```
