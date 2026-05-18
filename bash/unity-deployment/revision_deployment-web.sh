#!/bin/bash

# Prompt the user to enter the XXXXX value
read -p "Enter the value for XXXXX: " XXXXX

# Change the working directory to /home/ubuntu/unity-tarballs/
cd /home/ubuntu/unity-tarballs/

# Optional: Display the current directory after changing
echo "Current directory: $(pwd)"

# Download the .md5 file from S3 using the provided profile
/usr/local/bin/aws s3 cp s3://phn-p2g-dist/unity.R${XXXXX}.tar.gz.md5 . --profile phn

# Download the .tar.gz file from S3 using the provided profile
/usr/local/bin/aws s3 cp s3://phn-p2g-dist/unity.R${XXXXX}.tar.gz . --profile phn

# Change the ownership of the downloaded files to root (0:0)
chown 0:0 unity.R${XXXXX}.*

# Set the permissions of the downloaded files to 755 (-rwxr-xr-x)
chmod 755 unity.R${XXXXX}.*

# Change the directory to /home/ubuntu
cd /home/ubuntu

# Run the update-web-server-application.sh script with the provided XXXXX value
./update-web-server-application.sh ${XXXXX}

# Execute the Perl script to convert webapp config to JSON
if ! perl /opt/phn/unity/WebApp/script/convert_webapp_conf_to_json.pl; then
  echo "Failed to run convert_webapp_conf_to_json.pl"
  exit 1
fi
