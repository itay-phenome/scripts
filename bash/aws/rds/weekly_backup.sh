#!/usr/bin/bash

LOG_PATH="/var/log"
LOG_FILE_NAME="mysql_backup.log"

[ -d $LOG_PATH ] || mkdir -p $LOG_PATH
[ -f $LOG_PATH/$LOG_FILE_NAME ] || touch $LOG_PATH/$LOG_FILE_NAME

DATE_FORMAT=$(date +"%Y-%m-%d")

# ─────────────────────────────────────────────
# Prompt for all sensitive values at runtime
# ─────────────────────────────────────────────
echo "================================================"
echo "  MySQL Weekly Backup Script"
echo "================================================"
read -p "Enter MySQL host: "     MYSQL_HOST
read -p "Enter MySQL user: "     MYSQL_USER
read -s -p "Enter MySQL password: " MYSQL_PASSWORD
echo
read -p "Enter database name [pheno20]: " DB
DB=${DB:-pheno20}
read -p "Enter S3 bucket name: " S3_BUCKET_NAME
read -p "Enter S3 path [rds_weekly_backup]: " S3_BUCKET_PATH
S3_BUCKET_PATH=${S3_BUCKET_PATH:-rds_weekly_backup}

echo ""
echo "Starting weekly backup of '${DB}'..."

# ─────────────────────────────────────────────
# Backup
# ─────────────────────────────────────────────
LOCAL_BACKUP_DIR="/tmp"
mkdir -p ${LOCAL_BACKUP_DIR}/${DATE_FORMAT}
LOCAL_DIR=${LOCAL_BACKUP_DIR}/${DATE_FORMAT}
REMOTE_DIR=s3://${S3_BUCKET_NAME}/${S3_BUCKET_PATH}

mysqldump \
    -h ${MYSQL_HOST} \
    -u ${MYSQL_USER} \
    -p${MYSQL_PASSWORD} \
    --set-gtid-purged=OFF \
    --single-transaction \
    --column-statistics=0 --triggers --routines --events --databases ${DB} \
    | gzip -9 > ${LOCAL_DIR}/${DB}-${DATE_FORMAT}.sql.gz

aws s3 cp ${LOCAL_DIR}/${DB}-${DATE_FORMAT}.sql.gz ${REMOTE_DIR}/${DATE_FORMAT}/

if [ $? -eq 0 ]; then
    echo "Weekly backup successful." >> $LOG_PATH/$LOG_FILE_NAME
    echo "✅ Weekly backup uploaded to S3 successfully."
else
    echo "Weekly backup failed." >> $LOG_PATH/$LOG_FILE_NAME
    echo "❌ S3 upload failed."
    exit 1
fi

rm -f ${LOCAL_DIR}/${DB}-${DATE_FORMAT}.sql.gz
