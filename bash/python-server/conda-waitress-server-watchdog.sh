#!/bin/bash -x

LOG_FILE="/var/log/conda-waitress-server-watchdog.log"
NOW=$(date '+%d-%m-%Y-%H-%M-%S')
echo "$NOW Will Check if Waitress-Server is running..." >> "$LOG_FILE"

pgrep -f waitress_server.py > /dev/null
if [ $? != 0 ]; then
    echo "$NOW Waitress-Server is not running, will start it..." >> "$LOG_FILE"

    cd /opt/phn/unity/WebApp/lib/PHN/Python || exit 1

    # Set Conda path explicitly
    export PATH="/opt/miniconda3/bin:$PATH"
    source /opt/miniconda3/etc/profile.d/conda.sh
    conda activate ./conda_env

    # Use the python inside the Conda env (DO NOT use system-wide python3.12)
/opt/phn/unity/WebApp/lib/PHN/Python/conda_env/bin/python waitress_server.py >/dev/null 2>&1 &

    if [ $? != 0 ]; then
        echo "$(date '+%d-%m-%Y-%H-%M-%S') Error: failed starting Waitress-Server" >> "$LOG_FILE"
        exit 25
    fi
else
    echo "$NOW Waitress-Server is Running..." >> "$LOG_FILE"
fi
