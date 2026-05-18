# 🛠️ DevOps Scripts — Phenome Networks

A collection of DevOps and infrastructure scripts organized by format and category.

---

## 📁 Repository Structure

```
scripts/
├── bash/
│   ├── aws/
│   │   ├── rds/           — RDS slow query logs, MySQL backups
│   │   └── s3/            — S3 copy and policy scan scripts
│   ├── graphviz/          — Graphviz install and removal
│   ├── local-storage/     — Unity installation for local storage environments
│   ├── mysql/             — Advanced universal MySQL backup
│   ├── perl/              — Perl environment setup and diagnostics
│   ├── python-server/     — Waitress server watchdog and setup
│   └── unity-deployment/  — Deploy Unity (PhenomeOne) revisions
│
├── customers/
│   ├── basf/              — BASF DEV environment
│   ├── danzinger/         — Danzinger 2024 environment
│   ├── ews/               — EWS Mumbai environment
│   ├── enza-zaden/        — Enza Zaden environment
│   └── gdm/               — GDM environment
│
├── python/
│   └── aws/
│       ├── cloudtrail/    — IAM user activity investigation
│       ├── s3/            — S3 audit and management tools
│       └── waf/           — WAF IP blocking and ACL cloning
│
├── powershell/
│   └── aws/
│       └── ssm/           — Copy SSM Documents between regions
│
└── utils/
    └── aws/
        └── ssm/           — SSM Document definitions + CMD utility
```

---

## ⚡ Quick Reference

| Script | What it does |
|--------|-------------|
| `bash/mysql/mysql_backup_universal.sh` | Production MySQL backup with full validation |
| `bash/unity-deployment/revision_deployment-job.sh` | Deploy Unity Job Server revision |
| `bash/unity-deployment/revision_deployment-web.sh` | Deploy Unity Web Server revision |
| `bash/unity-deployment/web.sh` | Full web server installation from scratch |
| `bash/local-storage/job_local_storage.sh` | Job Server install — local storage environment |
| `bash/local-storage/web_local_storage.sh` | Web Server install — local storage environment |
| `python/aws/s3/s3_public_access_audit.py` | Audit S3 Block Public Access settings |
| `python/aws/waf/IP-Check-Script.py` | Check IPs against AbuseIPDB |
| `python/aws/waf/HOSTILE-IPS-BLOCK.py` | Auto-block hostile IPs in AWS WAF |
| `python/aws/waf/clone_waf_acl.py` | Clone WAF WebACL between regions |
| `python/aws/cloudtrail/iam_user_investigator.py` | Investigate IAM user activity |
| `powershell/aws/ssm/Copy-SSMDocuments-YAML.ps1` | Copy SSM Documents between regions |

---

## 🔐 Security

- No credentials are hardcoded — all sensitive values are prompted at runtime.
- AWS access uses IAM roles where possible.
- See each folder's `README.md` for specific requirements.

---

## ✅ Requirements

- **AWS CLI** configured (`aws configure` or IAM role attached to the instance)
- **Python 3.8+** with `boto3` for Python scripts
- **PowerShell 5+** with AWS CLI for PowerShell scripts
- **MySQL client** for backup scripts
