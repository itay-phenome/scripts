# 📁 bash/aws/s3

Scripts for copying and auditing S3 bucket contents.

---

## scan_s3_policies.sh
Scans all S3 buckets and reports which ones have CORS and Bucket Policy configured.

**Run:**
```bash
bash scan_s3_policies.sh
```
> Output: `s3_bucket_policies.csv`

---

## copy_s3_images.sh
Copies image files between two S3 buckets.

**Configure inside the script:** source and destination bucket names.

**Run:**
```bash
bash copy_s3_images.sh
```

---

## s3_copy_commands.sh / s3_copy_exact_files.sh / s3_copy_from_B_to_C.sh / s3_copy_valid_uris.sh
Variants of S3 copy operations for different scenarios:
- `s3_copy_commands.sh` — generates a list of copy commands
- `s3_copy_exact_files.sh` — copies a specific list of files
- `s3_copy_from_B_to_C.sh` — direct bucket-to-bucket copy
- `s3_copy_valid_uris.sh` — copies only objects with valid URIs

**Configure inside each script:** source bucket, destination bucket, file list or prefix.

**Run:**
```bash
bash s3_copy_commands.sh
bash s3_copy_exact_files.sh
bash s3_copy_from_B_to_C.sh
bash s3_copy_valid_uris.sh
```
