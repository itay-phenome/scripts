#!/bin/bash

# Define the DB instance identifier
DB_INSTANCE_ID="production"

# Define the base directory for saving logs
BASE_SAVE_DIR="/tmp/aws-logs"

# Create the base directory if it doesn't exist
mkdir -p "$BASE_SAVE_DIR"

# Get the list of all log files and filter out slowquery logs by searching for 'slowquery' in the log name
log_files=$(aws rds describe-db-log-files --db-instance-identifier $DB_INSTANCE_ID --output text --query "DescribeDBLogFiles[].LogFileName" | grep 'slowquery')

# Loop through each log file and download it
for log_file in $log_files; do
  echo "Downloading log: $log_file"

  # Create the necessary directories in /tmp/aws-logs if they don't exist
  log_file_path="$BASE_SAVE_DIR/$log_file"
  log_dir=$(dirname "$log_file_path")

  # Make sure the directory exists before downloading the log
  mkdir -p "$log_dir"

  # Download the log file
  log_data=$(aws rds download-db-log-file-portion \
    --db-instance-identifier $DB_INSTANCE_ID \
    --log-file-name $log_file \
    --starting-token 0 \
    --output text --query "LogFileData")

  # Save the log to the correct directory
  echo "$log_data" > "$log_file_path"
  echo "Log $log_file downloaded successfully to $log_file_path."
done

echo "All logs have been downloaded to $BASE_SAVE_DIR."