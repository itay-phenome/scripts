# 📁 python/aws/cloudtrail

Scripts for investigating IAM user activity via CloudTrail.

---

## iam_user_investigator.py
Searches CloudTrail events across **all AWS regions** for a specific IAM user (or all users).
Generates reports in JSON, TXT, and CSV formats.
Timestamps shown in both UTC and Israel time (IDT).

**Install:**
```bash
pip install boto3 python-dateutil
```

**Run:**
```bash
python3 iam_user_investigator.py
```

**Prompts:**
1. IAM username to investigate (or type `all` for all users)
2. Date range:
   - `1` — Today
   - `2` — Last 24 hours
   - `3` — Custom range (format: `DD-MM-YYYY`)

> Output folder: `report_USERNAME_YYYYMMDD_HHMMSS/`
> Contains: `.json`, `.txt`, `.csv`

**Required AWS permissions:** `cloudtrail:LookupEvents`, `ec2:DescribeRegions`

> ⚠️ CloudTrail lookup is limited to the **last 90 days**. For longer investigations, use Athena.
