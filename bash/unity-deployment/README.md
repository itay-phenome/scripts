# 📁 bash/unity-deployment

Scripts for deploying Unity (PhenomeOne) application revisions.

---

## revision_deployment-job.sh
Full Job Server deployment — downloads tarball from S3, runs DB migrations, and starts the job server.

**Run:**
```bash
bash revision_deployment-job.sh
```
> Prompts for: revision number, RDS host/user/password, database name, S3 bucket, AWS profile.

---

## revision_deployment-web.sh
Full Web Server deployment — downloads tarball from S3 and runs the web server update.

**Run:**
```bash
bash revision_deployment-web.sh
```
> Prompts for: revision number, S3 bucket, AWS profile.

---

## update-job-server-application.sh
Stops Job Server, validates tarball (MD5), extracts, updates symlink, installs R package, restarts cron.

**Run:**
```bash
bash update-job-server-application.sh <REVISION>
# Example:
bash update-job-server-application.sh 14689
```

---

## update-web-server-application.sh
Stops Apache + Waitress, validates tarball, extracts, updates symlinks, sets up Python venv, restarts Apache.

**Run:**
```bash
bash update-web-server-application.sh <REVISION>
# Example:
bash update-web-server-application.sh 14689
```

---

## web.sh
Full installation of a Unity Web Server from scratch on a new machine.
Installs all system packages, Perl CPAN modules, Apache, FCGI, Flask/Waitress, and deploys the Unity tarball.

> ⚠️ Run this **only on a fresh server**. Not safe to run twice.

**Run:**
```bash
bash web.sh
```
> Prompts for: revision, MySQL host/user/password, AWS region, S3 bucket names (uploads/images/analyses/reports/documents), SQS ARN.
