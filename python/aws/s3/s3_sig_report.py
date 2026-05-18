import boto3
import csv
import urllib.parse
from datetime import datetime

def detect_signature_type(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    if 'X-Amz-Signature' in query:
        return 'SigV4'
    elif 'Signature' in query:
        return 'SigV2'
    return 'Unknown'

def analyze_bucket(bucket_name: str, region: str):
    session = boto3.Session(region_name=region)
    s3 = session.client('s3')

    paginator = s3.get_paginator('list_objects_v2')
    page_iterator = paginator.paginate(Bucket=bucket_name)

    results = []
    counters = {'SigV4': 0, 'SigV2': 0, 'Unknown': 0, 'Total': 0}
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    csv_file = f"signed_url_report_{bucket_name}_{timestamp}.csv"

    print(f"\n🔍 Analyzing bucket: {bucket_name} in region: {region}...\n")

    for page in page_iterator:
        for obj in page.get('Contents', []):
            key = obj['Key']
            try:
                url = s3.generate_presigned_url(
                    ClientMethod='get_object',
                    Params={'Bucket': bucket_name, 'Key': key},
                    ExpiresIn=3600
                )
                sig_type = detect_signature_type(url)
                counters[sig_type] += 1
                counters['Total'] += 1
                results.append((key, sig_type, url))
            except Exception as e:
                results.append((key, 'Error', str(e)))

    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Object Key', 'Signature Type', 'Presigned URL'])
        writer.writerows(results)

        writer.writerow([])
        writer.writerow(['--- Summary ---'])
        for k, v in counters.items():
            writer.writerow([k, v])

    print(f"\n✅ Done. Report saved to: {csv_file}")
    print(f"🧾 Summary: Total={counters['Total']} | SigV4={counters['SigV4']} | SigV2={counters['SigV2']} | Unknown={counters['Unknown']}")

if __name__ == "__main__":
    print("📥 S3 Bucket Signature Scanner")
    bucket = input("Enter your S3 bucket name: ").strip()
    region = input("Enter your S3 bucket region (e.g. us-east-1): ").strip()

    if not bucket or not region:
        print("❌ Error: Bucket name and region are required.")
    else:
        analyze_bucket(bucket, region)
