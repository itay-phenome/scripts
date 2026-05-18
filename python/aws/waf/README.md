# 📁 python/aws/waf

Scripts for managing AWS WAF rules and blocking hostile IPs.

---

## IP-Check-Script.py
Checks a list of IP addresses against the **AbuseIPDB** API.
Classifies each IP as Hostile (score ≥ 80) or Legitimate.
Generates a Word document report.

**Install:**
```bash
pip install requests python-docx
```

**Run:**
```bash
python3 IP-Check-Script.py
```
> Prompts for: AbuseIPDB API key, IP list (from file or manual entry).
> Output: `IP_Address_Analysis.docx`

---

## HOSTILE-IPS-BLOCK.py
Checks IPs against AbuseIPDB and **automatically adds hostile IPs** (score ≥ 80) to an AWS WAF IP Set.
Generates a Word document report.

**Install:**
```bash
pip install boto3 requests python-docx
```

**Run:**
```bash
python3 HOSTILE-IPS-BLOCK.py
```
> Prompts for: AbuseIPDB API key, WAF WebACL ARN, WAF IP Set ARN, AWS region, IP list.
> Requires AWS credentials configured (`aws configure` or IAM role).

---

## clone_waf_acl.py
Clones an AWS WAF WebACL from one region or account to another.
Also copies all associated resources: IP Sets, RegexPatternSets, and RuleGroups.

**Configure at the top of the script:**
```python
SOURCE_PROFILE  = "default"
TARGET_PROFILE  = "target-profile"
SOURCE_REGION   = "ap-south-1"
DEST_REGION     = "us-east-1"
SRC_WEBACL_NAME = "my-webacl"
SRC_WEBACL_ID   = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
DST_WEBACL_NAME = "my-webacl-clone"
```

**Run:**
```bash
python3 clone_waf_acl.py
```
> ⚠️ AWS Managed Rule Groups are **not** cloned — re-add them manually in the destination.
