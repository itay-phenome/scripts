# 📁 bash/mysql

Advanced MySQL backup with full validation.

---

## mysql_backup_universal.sh
Production-grade MySQL backup. Works with RDS, EC2, Percona, Docker, or any MySQL target.

**Features:**
- Auto-detects MySQL version, GTID mode, and supported flags
- Full validation: file size, gzip integrity, table count, SHA256 checksum
- Rewrites DEFINER clauses so the dump works on any destination server
- Optional S3 upload and automatic retention cleanup

**Configure at the top of the script:**
```bash
DB="pheno20"
TARGET_DB_USER="phenome"
LOCAL_BACKUP_DIR="/var/backups/mysql"
RETENTION_DAYS=7
S3_BUCKET=""          # Leave empty to skip S3 upload
S3_REGION="us-east-1"
```

**Authentication** — create `/root/.my.cnf`:
```ini
[client]
user     = your_user
password = your_password
host     = your_rds_host
```

**Run:**
```bash
bash mysql_backup_universal.sh
```
> Output: `/var/backups/mysql/YYYY-MM-DD_HH-MM-SS/DB-DATE.sql.gz` + `.sha256`
> Log: `/var/log/mysql_backup.log`
