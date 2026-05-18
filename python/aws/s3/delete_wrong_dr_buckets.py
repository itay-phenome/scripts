#!/usr/bin/env python3

import boto3
import botocore
import sys

# === CONFIG ===
SUFFIX_TO_DELETE = "-524574648815"   # מה למחוק
DRY_RUN = True                      # שנה ל-False כדי לבצע מחיקה אמיתית
# =================

def empty_bucket(s3, bucket):
    paginator = s3.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=bucket):
        objs = []
        for v in page.get("Versions", []):
            objs.append({"Key": v["Key"], "VersionId": v["VersionId"]})
        for d in page.get("DeleteMarkers", []):
            objs.append({"Key": d["Key"], "VersionId": d["VersionId"]})

        if objs:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": objs})

def main():
    s3 = boto3.client("s3")
    buckets = s3.list_buckets()["Buckets"]

    targets = [b["Name"] for b in buckets if b["Name"].endswith(SUFFIX_TO_DELETE)]

    if not targets:
        print("No buckets matched – nothing to do.")
        return

    print("Buckets that WILL be deleted:" if not DRY_RUN else "Buckets that WOULD be deleted:")
    for b in targets:
        print(f"  - {b}")

    if DRY_RUN:
        print("\nDRY-RUN mode enabled. No changes made.")
        return

    confirm = input("\nType DELETE to confirm: ")
    if confirm != "DELETE":
        print("Aborted.")
        sys.exit(1)

    for bucket in targets:
        print(f"\nProcessing {bucket}")
        try:
            empty_bucket(s3, bucket)
            s3.delete_bucket(Bucket=bucket)
            print("  ✔ deleted")
        except botocore.exceptions.ClientError as e:
            print(f"  ✗ {e.response['Error']['Message']}")

    print("\nDone.")

if __name__ == "__main__":
    main()
