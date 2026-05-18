#!/usr/bin/env python3
"""
S3 Public Access Block Audit Tool
Audits all S3 buckets and reports on their Block Public Access settings.

Usage:
    python3 s3_public_access_audit.py [--profile PROFILE] [--output OUTPUT] [--format FORMAT]

Requirements:
    pip install boto3 tabulate

Output formats: text (default), csv, json, html
"""

import boto3
import json
import csv
import sys
import argparse
import datetime
from pathlib import Path

# Default output directory = same folder as this script
SCRIPT_DIR = Path(__file__).parent.resolve()
from concurrent.futures import ThreadPoolExecutor, as_completed
from tabulate import tabulate
from botocore.exceptions import ClientError, NoCredentialsError


# The 4 BPA settings keys (as returned by boto3)
BPA_KEYS = [
    "BlockPublicAcls",
    "IgnorePublicAcls",
    "BlockPublicPolicy",
    "RestrictPublicBuckets",
]

BPA_LABELS = {
    "BlockPublicAcls":        "Block new ACLs",
    "IgnorePublicAcls":       "Ignore all ACLs",
    "BlockPublicPolicy":      "Block new bucket policies",
    "RestrictPublicBuckets":  "Restrict public/cross-account access",
}


def has_public_policy(s3_client, bucket_name):
    """Check if bucket has a policy with Principal '*'. Returns True/False/None(error)."""
    try:
        resp = s3_client.get_bucket_policy(Bucket=bucket_name)
        policy = json.loads(resp["Policy"])
        for stmt in policy.get("Statement", []):
            if stmt.get("Effect") != "Allow":
                continue
            principal = stmt.get("Principal", {})
            # Principal can be "*" or {"AWS": "*"} or {"AWS": ["*", ...]}
            if principal == "*":
                return True
            if isinstance(principal, dict):
                aws = principal.get("AWS", [])
                if aws == "*" or (isinstance(aws, list) and "*" in aws):
                    return True
        return False
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "NoSuchBucketPolicy":
            return False
        return None  # Access denied or other error


def get_bpa_settings(s3_client, bucket_name):
    """Fetch BPA settings for a single bucket. Returns dict with results."""
    try:
        resp = s3_client.get_public_access_block(Bucket=bucket_name)
        cfg = resp.get("PublicAccessBlockConfiguration", {})
        return {
            "bucket": bucket_name,
            "error": None,
            "BlockPublicAcls":       cfg.get("BlockPublicAcls", False),
            "IgnorePublicAcls":      cfg.get("IgnorePublicAcls", False),
            "BlockPublicPolicy":     cfg.get("BlockPublicPolicy", False),
            "RestrictPublicBuckets": cfg.get("RestrictPublicBuckets", False),
            "PublicPolicy":          has_public_policy(s3_client, bucket_name),
        }
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "NoSuchPublicAccessBlockConfiguration":
            return {
                "bucket": bucket_name,
                "error": None,
                "BlockPublicAcls":       False,
                "IgnorePublicAcls":      False,
                "BlockPublicPolicy":     False,
                "RestrictPublicBuckets": False,
                "PublicPolicy":          has_public_policy(s3_client, bucket_name),
            }
        return {
            "bucket": bucket_name,
            "error": code,
            "BlockPublicAcls":       None,
            "IgnorePublicAcls":      None,
            "BlockPublicPolicy":     None,
            "RestrictPublicBuckets": None,
            "PublicPolicy":          None,
        }


def categorize(row):
    """Return a human-readable category for the BPA configuration."""
    if row["error"]:
        return "⚠️  Error / No Access"
    values = [row[k] for k in BPA_KEYS]
    enabled = sum(1 for v in values if v is True)
    if enabled == 0:
        return "🔴 None enabled"
    elif enabled == len(BPA_KEYS):
        return "🟢 All 4 enabled (fully blocked)"
    else:
        # Check if first 3 are enabled
        first_three = [row[k] for k in BPA_KEYS[:3]]
        if all(first_three) and not row["RestrictPublicBuckets"]:
            return "🟡 First 3 enabled (missing RestrictPublicBuckets)"
        return f"🟠 Partial ({enabled}/4 enabled)"


def audit_all_buckets(profile=None, max_workers=20):
    """List all buckets and fetch BPA settings concurrently."""
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    s3 = session.client("s3")

    print("📋 Listing all buckets...", flush=True)
    buckets = [b["Name"] for b in s3.list_buckets().get("Buckets", [])]
    total = len(buckets)
    print(f"   Found {total} buckets. Fetching BPA settings ({max_workers} threads)...\n", flush=True)

    results = []
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(get_bpa_settings, s3, name): name for name in buckets}
        for future in as_completed(futures):
            row = future.result()
            row["category"] = categorize(row)
            results.append(row)
            done += 1
            if done % 50 == 0 or done == total:
                print(f"   Progress: {done}/{total}", flush=True)

    return results


SORT_OPTIONS = {
    "category": lambda r: (r["category"], r["bucket"]),
    "bucket":   lambda r: r["bucket"],
    "public":   lambda r: (r["PublicPolicy"] is not True, r["bucket"]),
    "risk":     lambda r: (
        0 if r["PublicPolicy"] is True else
        1 if r["category"] == "🔴 None enabled" else
        2 if "🟠" in r["category"] else
        3 if "🟡" in r["category"] else
        4 if "🟢" in r["category"] else 5,
        r["bucket"]
    ),
}


def sort_results(results, sort_by="risk"):
    key = SORT_OPTIONS.get(sort_by, SORT_OPTIONS["risk"])
    return sorted(results, key=key)


def print_summary(results):
    """Print a grouped summary to stdout."""
    from collections import defaultdict
    groups = defaultdict(list)
    for r in results:
        groups[r["category"]].append(r["bucket"])

    print("\n" + "=" * 70)
    print("  S3 PUBLIC ACCESS BLOCK — AUDIT REPORT")
    print(f"  Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Total buckets audited: {len(results)}")
    print("=" * 70)

    order = [
        "🟢 All 4 enabled (fully blocked)",
        "🟡 First 3 enabled (missing RestrictPublicBuckets)",
        "🟠 Partial ({enabled}/4 enabled)",
        "🔴 None enabled",
        "⚠️  Error / No Access",
    ]
    # Sort groups by category
    for cat in sorted(groups.keys(), key=lambda c: (
        0 if "🟢" in c else 1 if "🟡" in c else 2 if "🟠" in c else 3 if "🔴" in c else 4
    )):
        blist = sorted(groups[cat])
        print(f"\n{cat}  ({len(blist)} buckets)")
        print("-" * 60)
        for b in blist:
            print(f"  • {b}")

    print("\n" + "=" * 70)
    print("SUMMARY TABLE")
    print("=" * 70)
    summary = [(cat, len(blist)) for cat, blist in groups.items()]
    summary.sort(key=lambda x: x[1], reverse=True)
    print(tabulate(summary, headers=["Category", "Count"], tablefmt="rounded_outline"))
    print()


def export_csv(results, path):
    """Export full results to CSV."""
    fields = ["bucket", "category", "PublicPolicy", "error"] + BPA_KEYS
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)
    print(f"✅ CSV saved: {path}")


def export_json(results, path):
    """Export full results to JSON."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"✅ JSON saved: {path}")


def export_html(results, path):
    """Export a self-contained HTML report with clickable column sorting."""
    rows_html = ""
    for r in results:
        def td(v):
            if v is True:
                return '<td style="color:green;text-align:center">✔</td>'
            elif v is False:
                return '<td style="color:red;text-align:center">✘</td>'
            elif v is None:
                return '<td style="text-align:center">—</td>'
            return f"<td>{v}</td>"

        def td_policy(v):
            if v is True:
                return '<td style="color:red;text-align:center;font-weight:bold">⚠️ Yes</td>'
            elif v is False:
                return '<td style="color:green;text-align:center">No</td>'
            return '<td style="text-align:center">—</td>'

        cat = r["category"]
        color = (
            "#d4edda" if "🟢" in cat else
            "#fff3cd" if "🟡" in cat else
            "#ffe5b4" if "🟠" in cat else
            "#f8d7da" if "🔴" in cat else
            "#e2e3e5"
        )
        rows_html += (
            f'<tr style="background:{color}" '
            f'data-bucket="{r["bucket"]}" '
            f'data-category="{cat}" '
            f'data-public="{str(r["PublicPolicy"]).lower()}" '
            f'data-acls="{str(r["BlockPublicAcls"]).lower()}" '
            f'data-ignore="{str(r["IgnorePublicAcls"]).lower()}" '
            f'data-policy="{str(r["BlockPublicPolicy"]).lower()}" '
            f'data-restrict="{str(r["RestrictPublicBuckets"]).lower()}" '
            f'data-error="{r["error"] or ""}">'
            f'<td>{r["bucket"]}</td>'
            f'<td>{cat}</td>'
            f'{td_policy(r["PublicPolicy"])}'
            f'{td(r["BlockPublicAcls"])}'
            f'{td(r["IgnorePublicAcls"])}'
            f'{td(r["BlockPublicPolicy"])}'
            f'{td(r["RestrictPublicBuckets"])}'
            f'<td>{r["error"] or ""}</td>'
            f'</tr>\n'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>S3 BPA Audit Report</title>
<style>
  body {{ font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5; }}
  h1 {{ color: #232f3e; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  th {{
    background: #232f3e; color: white; padding: 10px 8px;
    text-align: left; position: sticky; top: 0; cursor: pointer;
    user-select: none; white-space: nowrap;
  }}
  th:hover {{ background: #374151; }}
  th.sorted-asc::after  {{ content: " ▲"; font-size: 10px; }}
  th.sorted-desc::after {{ content: " ▼"; font-size: 10px; }}
  td {{ padding: 6px 8px; border-bottom: 1px solid #ddd; }}
  tr:hover {{ filter: brightness(95%); }}
  .toolbar {{ display: flex; gap: 12px; align-items: center; margin-bottom: 14px; flex-wrap: wrap; }}
  input[type=text] {{ padding: 7px 10px; width: 280px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; }}
  .count {{ color: #666; font-size: 13px; }}
</style>
</head>
<body>
<h1>🪣 S3 Public Access Block Audit</h1>
<p>Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} &nbsp;|&nbsp; Total buckets: {len(results)}</p>
<div class="toolbar">
  <input type="text" id="search" placeholder="🔍 Filter buckets..." oninput="filterTable()">
  <span class="count" id="count"></span>
</div>
<table id="tbl">
<thead>
<tr>
  <th data-col="bucket">Bucket</th>
  <th data-col="category">Category</th>
  <th data-col="public">Public Policy</th>
  <th data-col="acls">Block new ACLs</th>
  <th data-col="ignore">Ignore all ACLs</th>
  <th data-col="policy">Block new policies</th>
  <th data-col="restrict">Restrict public/cross-account</th>
  <th data-col="error">Error</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>

<script>
// Sort state
let sortCol = null, sortAsc = true;

// Boolean rank: true=0, false=1, none=2
function boolRank(v) {{
  if (v === 'true')  return 0;
  if (v === 'false') return 1;
  return 2;
}}

// Risk rank for category
function riskRank(cat) {{
  if (cat.includes('🔴')) return 0;
  if (cat.includes('🟠')) return 1;
  if (cat.includes('🟡')) return 2;
  if (cat.includes('🟢')) return 3;
  return 4;
}}

function getCellValue(tr, col) {{
  return tr.dataset[col] || '';
}}

function compareRows(a, b, col) {{
  const va = getCellValue(a, col);
  const vb = getCellValue(b, col);
  if (col === 'category') return riskRank(va) - riskRank(vb);
  if (['public','acls','ignore','policy','restrict'].includes(col)) return boolRank(va) - boolRank(vb);
  return va.localeCompare(vb);
}}

document.querySelectorAll('th[data-col]').forEach(th => {{
  th.addEventListener('click', () => {{
    const col = th.dataset.col;
    if (sortCol === col) {{ sortAsc = !sortAsc; }}
    else {{ sortCol = col; sortAsc = true; }}

    // Update header indicators
    document.querySelectorAll('th').forEach(t => t.classList.remove('sorted-asc','sorted-desc'));
    th.classList.add(sortAsc ? 'sorted-asc' : 'sorted-desc');

    const tbody = document.querySelector('#tbl tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort((a, b) => {{
      const cmp = compareRows(a, b, col);
      return sortAsc ? cmp : -cmp;
    }});
    rows.forEach(r => tbody.appendChild(r));
    updateCount();
  }});
}});

function filterTable() {{
  const q = document.getElementById('search').value.toLowerCase();
  document.querySelectorAll('#tbl tbody tr').forEach(r => {{
    r.style.display = r.innerText.toLowerCase().includes(q) ? '' : 'none';
  }});
  updateCount();
}}

function updateCount() {{
  const visible = Array.from(document.querySelectorAll('#tbl tbody tr')).filter(r => r.style.display !== 'none').length;
  document.getElementById('count').textContent = `Showing ${{visible}} / {len(results)} buckets`;
}}

// Init count
updateCount();
</script>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ HTML saved: {path}")


def main():
    parser = argparse.ArgumentParser(description="Audit S3 Block Public Access settings")
    parser.add_argument("--profile", default=None, help="AWS profile name (~/.aws/credentials)")
    parser.add_argument("--output", default=str(SCRIPT_DIR / "s3_bpa_audit"), help="Output file base name (no extension)")
    parser.add_argument("--format", choices=["text", "csv", "json", "html", "all"], default="all",
                        help="Output format (default: all)")
    parser.add_argument("--workers", type=int, default=20, help="Parallel threads (default: 20)")
    parser.add_argument("--sort", choices=["risk", "category", "bucket", "public"], default="risk",
                        help="Sort order: risk (default) | category | bucket | public")
    args = parser.parse_args()

    try:
        results = audit_all_buckets(profile=args.profile, max_workers=args.workers)
    except NoCredentialsError:
        print("❌ No AWS credentials found. Configure via:\n"
              "   - AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY env vars\n"
              "   - aws configure\n"
              "   - IAM role (EC2/EKS)")
        sys.exit(1)

    fmt = args.format
    base = args.output
    results = sort_results(results, args.sort)

    if fmt in ("text", "all"):
        print_summary(results)

    if fmt in ("csv", "all"):
        export_csv(results, f"{base}.csv")

    if fmt in ("json", "all"):
        export_json(results, f"{base}.json")

    if fmt in ("html", "all"):
        export_html(results, f"{base}.html")


if __name__ == "__main__":
    main()