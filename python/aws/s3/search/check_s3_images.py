
import boto3
import pandas as pd
import os

# AWS S3 bucket and prefix
bucket_name = "phenome-topseeds-files-image"
prefix = "images/"

# Load the CSV with filenames
df = pd.read_csv("image_filenames_to_check.csv")
filenames = set(df["Filename"].dropna().unique())

# Set up S3 client (ensure credentials are configured via AWS CLI or env)
s3 = boto3.client("s3")

# List all objects under the prefix
paginator = s3.get_paginator("list_objects_v2")
pages = paginator.paginate(Bucket=bucket_name, Prefix=prefix)

# Check which files exist
existing_files = []
not_found_files = []

for page in pages:
    for obj in page.get("Contents", []):
        key = obj["Key"]
        basename = os.path.basename(key)
        if basename in filenames:
            existing_files.append({"Filename": basename, "S3 Path": key})
            filenames.remove(basename)

# Add any that were not found
not_found_files = [{"Filename": fname, "S3 Path": ""} for fname in filenames]

# Combine results
final_df = pd.DataFrame(existing_files + not_found_files)

# Save to CSV
final_df.to_csv("s3_file_check_result.csv", index=False)
print("Done. Output written to s3_file_check_result.csv")
