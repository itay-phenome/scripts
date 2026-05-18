# 📁 bash/aws/rds

Scripts for downloading logs and backing up RDS/MySQL databases.

---

## slowquery.sh
Downloads slow query log files from an RDS instance to `/tmp/aws-logs`.

**Configure inside the script:**
```bash
DB_INSTANCE_ID="your-rds-instance-name"
```
**Run:**
```bash
bash slowquery.sh
```

---

## mysqldump_rds.sh
MySQL database backup — dumps to `.sql.gz` and uploads to S3.

**Run:**
```bash
bash mysqldump_rds.sh
```
> Prompts for: MySQL host, user, password, database name, S3 bucket.

---

## weekly_backup.sh
Same as `mysqldump_rds.sh` — intended as a weekly cron job.

**Run:**
```bash
bash weekly_backup.sh
```
> Prompts for: MySQL host, user, password, database name, S3 bucket.

**Cron example (every Sunday at 01:00):**
```
0 1 * * 0 /path/to/weekly_backup.sh
```
