# 📁 python/aws/s3

Python scripts for auditing and managing S3 buckets.

---

## s3_public_access_audit.py
Audits all S3 buckets and reports their Block Public Access (BPA) settings.
Identifies buckets with public policies. Generates text, CSV, JSON, and interactive HTML reports.

**Install:**
```bash
pip install boto3 tabulate
```

**Run:**
```bash
python3 s3_public_access_audit.py
python3 s3_public_access_audit.py --profile my-profile --format html
```

| Flag | Description | Default |
|------|-------------|---------|
| `--profile` | AWS profile name | default |
| `--format` | text / csv / json / html / all | all |
| `--sort` | risk / category / bucket / public | risk |
| `--workers` | Parallel threads | 20 |
| `--output` | Output filename (no extension) | s3_bpa_audit |

---

## s3_sig_report.py
Generates presigned URLs for all objects in a bucket and detects whether they use SigV2 or SigV4.

**Install:** `pip install boto3`

**Run:**
```bash
python3 s3_sig_report.py
```
> Prompts for: bucket name, region.
> Output: `signed_url_report_BUCKET_DATE.csv`

---

## s3_map_buckets_without_replication.py
Lists all S3 buckets that do **not** have an active replication rule.

**Run:**
```bash
python3 s3_map_buckets_without_replication.py
```
> Output: `s3_buckets_without_replication.csv` + `.txt`

---

## delete_wrong_dr_buckets.py
Deletes S3 buckets ending with a specific suffix. Used to clean up wrongly created DR buckets.
Empties all objects and delete markers before deleting.

> ⚠️ Destructive. Runs in **dry-run mode by default**.

**Configure at the top of the script:**
```python
SUFFIX_TO_DELETE = "-524574648815"   # Change to your suffix
DRY_RUN = True                        # Change to False to actually delete
```

**Run:**
```bash
python3 delete_wrong_dr_buckets.py
```
