#! /bin/sh -x

echo `date '+%d-%m-%Y-%H-%M-%S'` "Will Check if Waitress-Server is running..." >> /var/log/waitress-server-watchdog.log
ps aux | grep -v grep | grep waitress_server
if [ $? != 0 ]
then
    echo `date '+%d-%m-%Y-%H-%M-%S'` "Waitress-Server is not running, will start it..." >> /var/log/waitress-server-watchdog.log
    cd /opt/phn/unity/WebApp/lib/PHN/Python
    source .venv/bin/activate
    python3.12 waitress_server.py >/dev/null &
    if [ $? != 0 ]
    then
        echo `date '+%d-%m-%Y-%H-%M-%S'` "Error: failed starting Waitress-Server" >> /var/log/waitress-server-watchdog.log
        echo `date '+%d-%m-%Y-%H-%M-%S'` "Script will exit..." >> /var/log/waitress-server-watchdog.log
        exit 25
    fi
else
    echo `date '+%d-%m-%Y-%H-%M-%S'` "Waitress-Server is Running..." >> /var/log/waitress-server-watchdog.log
fi
