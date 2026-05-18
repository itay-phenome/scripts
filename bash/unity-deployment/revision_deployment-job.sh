#!/bin/bash

echo "================================================"
echo "  Unity Job Server - Revision Deployment"
echo "================================================"

read -p "Enter revision number: " XXXXX

read -p "Enter RDS host: " RDS_HOST
read -p "Enter RDS user [phenome]: " RDS_USER
RDS_USER=${RDS_USER:-phenome}
read -s -p "Enter RDS password: " RDS_PASS
echo
read -p "Enter database name [pheno20]: " RDS_DB
RDS_DB=${RDS_DB:-pheno20}

read -p "Enter S3 bucket for tarballs [phn-p2g-dist]: " S3_BUCKET
S3_BUCKET=${S3_BUCKET:-phn-p2g-dist}
read -p "Enter AWS profile [phn]: " AWS_PROFILE
AWS_PROFILE=${AWS_PROFILE:-phn}

echo ""
echo "Starting deployment of revision R${XXXXX}..."

# ─────────────────────────────────────────────
# Download tarball from S3
# ─────────────────────────────────────────────
cd /home/ubuntu/unity-tarballs/
echo "Downloading from S3..."
/usr/local/bin/aws s3 cp s3://${S3_BUCKET}/unity.R${XXXXX}.tar.gz.md5 . --profile ${AWS_PROFILE}
/usr/local/bin/aws s3 cp s3://${S3_BUCKET}/unity.R${XXXXX}.tar.gz     . --profile ${AWS_PROFILE}

chown 0:0 unity.R${XXXXX}.*
chmod 755 unity.R${XXXXX}.*

# ─────────────────────────────────────────────
# Run update script
# ─────────────────────────────────────────────
cd /home/ubuntu
./update-job-server-application.sh ${XXXXX}

# ─────────────────────────────────────────────
# Run SQL migrations
# ─────────────────────────────────────────────
cd /opt/phn/unity
echo "Running SQL migrations..."
for i in DB/mustAddToDB/*.sql; do
    echo "Applying: $i"
    mysql -h ${RDS_HOST} -u ${RDS_USER} -p${RDS_PASS} ${RDS_DB} < $i
done

# ─────────────────────────────────────────────
# Run Liquibase
# ─────────────────────────────────────────────
cd /opt/phn/unity/DB/
cp /home/ubuntu/files/liquibase.properties .
/opt/liquibase/liquibase --defaultsFile=liquibase.properties --changeLogFile=changelog.sql update

# ─────────────────────────────────────────────
# Restart Job Server
# ─────────────────────────────────────────────
echo "Restarting Job Server..."
pkill -f "job_server.pl" || true
sleep 2
/usr/bin/perl /opt/phn/unity/JobServer/bin/job_server.pl &

echo "✅ Deployment of R${XXXXX} completed successfully."
