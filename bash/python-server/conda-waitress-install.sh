#!/bin/bash -x

# Navigate to project dir
cd /opt/phn/unity/WebApp/lib/PHN/Python || exit 1

# Remove old .venv if it exists
if [ -d ".venv" ]; then
    echo "Removing old virtualenv (.venv)..."
    rm -rf .venv
fi

# Ensure conda is accessible
export PATH="/opt/miniconda3/bin:$PATH"
source /opt/miniconda3/etc/profile.d/conda.sh

# Remove and recreate conda env
if [ -d "conda_env" ]; then
    echo "Removing old Conda environment..."
    rm -rf conda_env
fi

#conda create -y -p ./conda_env python=3.12
	conda env create -p ./conda_env -f environment.yml

# Activate env
conda activate ./conda_env/

# Install dependencies
#pip install -r requirements.txt
pip install waitress

# Run Perl-based config conversion
perl /opt/phn/unity/WebApp/script/convert_webapp_conf_to_json.pl

# Start watchdog script (must be updated to match Conda)
bash /opt/phn/unity/UtilityScripts/conda-waitress-server-watchdog.sh

sudo -i
vi /home/ubuntu/files/webapp.conf
<Storage tiledb>
    bucket_name unity-qa-tiledb-bucket
    ws_root https://s3-eu-west-1.amazonaws.com
    work_dir /tmp/web_server/genomics
    region  eu-west-1
</Storage>

sudo -i
cd /opt/phn/unity/WebApp/lib/PHN/Python
export PATH="/opt/miniconda3/bin:$PATH"
source /opt/miniconda3/etc/profile.d/conda.sh
#rm -rf conda_env
#conda env create -p ./conda_env -f environment.yml
conda activate conda_env/
pip install waitress
conda deactivate
perl /opt/phn/unity/WebApp/script/convert_webapp_conf_to_json.pl
kill -9 `ps aux | grep conda` 
ps aux |grep conda
/bin/bash /opt/phn/unity/UtilityScripts/conda-waitress-server-watchdog.sh
ps aux |grep conda
kill -9 `ps aux | grep job` 
ps aux | grep job | grep -v grep
/usr/bin/perl /opt/phn/unity/JobServer/bin/job_server.pl &