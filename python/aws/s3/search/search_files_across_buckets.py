import boto3
import pandas as pd
from botocore.exceptions import ClientError
import os

# === Configuration ===
FILES_XLSX = "kaiima_images.xlsx"
BUCKET_CSV = "s3_bucket_summary_IL_20250708_130100.csv"
OUTPUT_CSV = "s3_file_search_results.csv"
CASE_INSENSITIVE = True  # Set to False for case-sensitive match

# === Load the list of filenames from Excel ===
try:
    file_df = pd.read_excel(FILES_XLSX)
    file_list = file_df.iloc[:, 0].dropna().astype(str).tolist()
except Exception as e:
    print(f"[ERROR] Failed to load {FILES_XLSX}: {e}")
    exit(1)

# === Load the list of buckets and regions from CSV ===
try:
    bucket_df = pd.read_csv(BUCKET_CSV)
    bucket_list = bucket_df[['BucketName', 'Region']].dropna()
except Exception as e:
    print(f"[ERROR] Failed to load {BUCKET_CSV}: {e}")
    exit(1)

# === Function to find exact file match in a bucket ===
def search_exact_file(s3_client, bucket_name, filename):
    paginator = s3_client.get_paginator('list_objects_v2')
    try:
        for page in paginator.paginate(Bucket=bucket_name):
            for obj in page.get('Contents', []):
                s3_key = obj['Key']
                s3_filename = os.path.basename(s3_key)

                if CASE_INSENSITIVE:
                    if s3_filename.lower() == filename.lower():
                        return s3_key
                else:
                    if s3_filename == filename:
                        return s3_key
    except ClientError as e:
        print(f"[ERROR] Failed to scan bucket {bucket_name}: {e}")
    return None

# === Search and collect matches ===
results = []

for filename in file_list:
    print(f"\n🔍 Searching for file: {filename}")
    found = False

    for _, row in bucket_list.iterrows():
        bucket_name = row['BucketName']
        region = row['Region'] if row['Region'] != 'EU' else 'eu-west-1'
        s3 = boto3.client('s3', region_name=region)

        print(f"  → Checking in bucket: {bucket_name} ({region})")
        full_key = search_exact_file(s3, bucket_name, filename)

        if full_key:
            print(f"    ✅ Found: {full_key}")
            results.append({
                'FileName': filename,
                'BucketName': bucket_name,
                'Region': region,
                'FullKey': full_key
            })
            found = True
            break  # Stop at first match

    if not found:
        print(f"    ❌ Not found in any bucket")

# === Save matched results to CSV ===
if results:
    try:
        output_df = pd.DataFrame(results)
        output_df.to_csv(OUTPUT_CSV, index=False)
        print(f"\n✅ Search complete. {len(results)} files matched. Output saved to: {OUTPUT_CSV}")
    except Exception as e:
        print(f"[ERROR] Failed to write {OUTPUT_CSV}: {e}")
else:
    print("\n❌ No files matched in any bucket.")
