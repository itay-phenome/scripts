#! /bin/bash

REVISION=$1

echo "##############################################################################################"
echo "Hi, starting the script update-web-server-application.sh"
echo "REVISION=${REVISION}"
echo "##############################################################################################"

# Stop web server
/etc/init.d/apache2 stop

echo "Will stop Waitress Server if running..."
ps aux | grep -v grep | grep "python3"
if [ $? -eq 0 ]
then
    kill -9 `ps aux | grep -v grep | grep "python3"`
    if [ $? != 0 ]
    then
        echo "Error: Failed Stopping Waitress Server"
    fi
fi

echo "Will calculate MD5 of the tarball and check it..."
cd /home/ubuntu/unity-tarballs/
md5sum -c /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz.md5
if [ $? != 0 ]
then
    echo "Error: tarball unity.R${REVISION}.tar.gz is corrupted, MD5 values differ"
    "Script will exit..."
    exit 2
fi

echo "Extracting unity.R${REVISION}.tar.gz to /opt/phn/unity.R${REVISION}"
if [ -d /opt/phn/unity.R${REVISION} ]
then
    echo "Directory /opt/phn/unity.R${REVISION} exists and will be removed."
    rm -rf /opt/phn/unity.R${REVISION}
fi

mkdir /opt/phn/unity.R${REVISION}
tar xvzf /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz -C /opt/phn/unity.R${REVISION}
if [ $? != 0 ]
then
    echo "Error: There was a problem extracting the tarball unity.R${REVISION}.tar.gz."
    "Script will exit..."
    exit 2
fi

if [ -L /opt/phn/unity ]
then
    unlink /opt/phn/unity
fi
cd /opt/phn/
ln -s unity.R${REVISION} unity

echo "Will copy scripts to /srv/vhosts/unity.R${REVISION}/script/ directory..."
cp -rf /opt/phn/unity/WebApp/script/* /srv/vhosts/unity/script/
chmod +x /srv/vhosts/unity/script/*.pl
chmod +x /srv/vhosts/unity/script/*.fcgi

echo "Will copy /opt/phn/unity/WebApp/Makefile.PL to /srv/vhosts/unity.R${REVISION}/ directory..."
cp -f /opt/phn/unity/WebApp/Makefile.PL /srv/vhosts/unity/

if [ -e /usr/bin/python3.12 ]
then
    echo "Set up Python 3.12 environment"
    cd /opt/phn/unity/WebApp/lib/PHN/Python/
    /usr/bin/python3.12 -m venv .venv
    source .venv/bin/activate
    sudo apt install python3.12-dev
    pip install -r requirements.txt
    pip install waitress
    python3.12 waitress_server.py &
else
    echo "Python 3.12 not installed"
fi

# Update revision in webapp.conf
perl -pi -e "s/revision \d+/revision ${REVISION}/g" /srv/vhosts/unity/webapp.conf

# Copy to /home/ubuntu/files
cp /srv/vhosts/unity/webapp* /home/ubuntu/files

# Copy to /opt/phn/unity/WebApp
cp /srv/vhosts/unity/webapp* /opt/phn/unity/WebApp || exit 301

/etc/init.d/apache2 start

echo "update-web-server-application.sh script finished successfully!!!"
