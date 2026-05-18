import boto3
import botocore
import csv
from datetime import datetime

CSV_FILE = "s3_buckets_without_replication.csv"
TXT_FILE = "s3_buckets_without_replication.txt"

def get_bucket_region(s3, bucket):
    try:
        resp = s3.get_bucket_location(Bucket=bucket)
        return resp.get("LocationConstraint") or "us-east-1"
    except botocore.exceptions.ClientError:
        return "UNKNOWN"

def has_enabled_replication(s3, bucket):
    try:
        resp = s3.get_bucket_replication(Bucket=bucket)
        rules = resp.get("ReplicationConfiguration", {}).get("Rules", [])
        return any(rule.get("Status") == "Enabled" for rule in rules)
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] in (
            "ReplicationConfigurationNotFoundError",
            "NoSuchReplicationConfiguration",
        ):
            return False
        return False  # treat access issues as non-replicated

def main():
    s3 = boto3.client("s3")
    buckets = s3.list_buckets()["Buckets"]

    non_replicated = []

    print(f"\nMapping S3 buckets without replication — {datetime.utcnow().isoformat()} UTC\n")

    for b in buckets:
        bucket = b["Name"]
        region = get_bucket_region(s3, bucket)

        if not has_enabled_replication(s3, bucket):
            non_replicated.append({
                "bucket": bucket,
                "region": region
            })
            print(f"{bucket:50} {region}")

    # CSV output (bucket + region)
    with open(CSV_FILE, "w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=["bucket", "region"])
        writer.writeheader()
        for row in non_replicated:
            writer.writerow(row)

    # TXT output (bucket names only)
    with open(TXT_FILE, "w") as txtfile:
        for row in non_replicated:
            txtfile.write(row["bucket"] + "\n")

    print("\nSummary")
    print("-------")
    print(f"Buckets without replication: {len(non_replicated)}")
    print(f"CSV output: {CSV_FILE}")
    print(f"TXT output: {TXT_FILE}\n")

if __name__ == "__main__":
    main()
