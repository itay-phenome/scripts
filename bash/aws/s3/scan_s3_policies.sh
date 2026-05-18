#!/usr/bin/env bash
set -uo pipefail

# Output CSV file
OUTPUT_FILE="s3_bucket_policies.csv"

# Optional: honor AWS_PROFILE if set in your shell
PROFILE_OPT=""
if [[ -n "${AWS_PROFILE:-}" ]]; then
  PROFILE_OPT="--profile ${AWS_PROFILE}"
fi

# Write CSV header
echo '"bucket_name","cors","bucket_policy"' > "$OUTPUT_FILE"

# List all bucket names and loop over them
aws $PROFILE_OPT s3api list-buckets --query 'Buckets[].Name' --output text \
  | tr '\t' ' ' | tr ' ' '\n' \
  | while read -r bucket; do
      [[ -z "$bucket" ]] && continue

      # Check CORS configuration
      if aws $PROFILE_OPT s3api get-bucket-cors --bucket "$bucket" >/dev/null 2>&1; then
        cors_status="have"
      else
        cors_status="don't have"
      fi

      # Check Bucket Policy
      if aws $PROFILE_OPT s3api get-bucket-policy --bucket "$bucket" >/dev/null 2>&1; then
        policy_status="have"
      else
        policy_status="don't have"
      fi

      # Append row to CSV (properly quoted)
      printf '"%s","%s","%s"\n' "$bucket" "$cors_status" "$policy_status" >> "$OUTPUT_FILE"
    done

echo "Done. Results written to: $OUTPUT_FILE"