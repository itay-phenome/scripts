import boto3
import csv
import sys

FILENAME_TO_FIND = sys.argv[1]  # or hardcode a string like 'config.json'
BUCKET_LIST_CSV = "s3_bucket_summary_IL_20250708_130100.csv"  # your bucket CSV file
CASE_INSENSITIVE = True

def search_file_in_bucket(bucket_name, region, filename):
    s3 = boto3.client('s3', region_name=region)
    paginator = s3.get_paginator('list_objects_v2')

    try:
        for page in paginator.paginate(Bucket=bucket_name):
            for obj in page.get('Contents', []):
                key = obj['Key']
                if CASE_INSENSITIVE:
                    if filename.lower() in key.lower():
                        return key
                else:
                    if filename in key:
                        return key
    except s3.exceptions.NoSuchBucket:
        return None
    except Exception as e:
        print(f"[WARN] Error scanning {bucket_name}: {e}")
    return None

def main():
    matches = []

    with open(BUCKET_LIST_CSV, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            bucket = row['BucketName']
            region = row['Region'] if row['Region'] != 'EU' else 'eu-west-1'  # AWS quirk
            print(f"🔍 Scanning: {bucket} in {region}...")
            key = search_file_in_bucket(bucket, region, FILENAME_TO_FIND)
            if key:
                print(f"✅ Found in {bucket}: {key}")
                matches.append((bucket, region, key))

    if not matches:
        print(f"❌ No match found for '{FILENAME_TO_FIND}'")
    else:
        print("\n🎯 Matched Buckets:")
        for bucket, region, key in matches:
            print(f" - {bucket} ({region}) ➤ {key}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3.12 s3_search_file_across_buckets.py <filename>")
        sys.exit(1)
    main()

