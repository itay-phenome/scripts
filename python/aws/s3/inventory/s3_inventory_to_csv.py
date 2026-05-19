import boto3
import csv
import pytz
from datetime import datetime

ACCOUNT_ID = "524574648815"
IL_TZ = pytz.timezone("Asia/Jerusalem")
OUTPUT_FILE = f"s3_bucket_summary_IL_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

def get_bucket_region(bucket_name):
    s3 = boto3.client('s3')
    try:
        resp = s3.get_bucket_location(Bucket=bucket_name)
        loc = resp.get('LocationConstraint')
        return loc if loc else 'us-east-1'
    except Exception as e:
        print(f"[WARN] Failed to get region for {bucket_name}: {e}")
        return "unknown"

def get_last_object_time(bucket_name, region):
    s3 = boto3.client('s3', region_name=region)
    try:
        response = s3.list_objects_v2(Bucket=bucket_name, MaxKeys=1, StartAfter='~')
        contents = response.get('Contents')
        if contents:
            lastmod = contents[0]['LastModified']
            return lastmod.astimezone(IL_TZ).strftime('%Y-%m-%d %H:%M:%S')
        else:
            return "No objects"
    except Exception as e:
        return f"Error: {e}"

def main():
    s3 = boto3.client('s3')
    buckets = s3.list_buckets().get('Buckets', [])

    with open(OUTPUT_FILE, mode='w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['AccountID', 'BucketName', 'Region', 'BucketCreation_IL', 'LastUsed_IL'])

        for b in buckets:
            name = b['Name']
            creation_utc = b['CreationDate']
            creation_il = creation_utc.astimezone(IL_TZ).strftime('%Y-%m-%d %H:%M:%S')
            region = get_bucket_region(name)
            last_used = get_last_object_time(name, region)

            print(f"✓ {name} | Created: {creation_il} | LastUsed: {last_used}")
            writer.writerow([ACCOUNT_ID, name, region, creation_il, last_used])

    print(f"\n✅ Done: {OUTPUT_FILE}")

if __name__ == '__main__':
    main()

