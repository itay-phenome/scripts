#! /bin/bash

REVISION=$1

echo "##############################################################################################"
echo "Hi, starting the script update-job-server-application.sh"
echo "REVISION=${REVISION}"
echo "##############################################################################################"

# Stop Cron service
/etc/init.d/cron stop || exit 300

echo "Will stop Job-Server if running..."
ps aux | grep -v grep | grep "/opt/phn/unity/JobServer/bin/job_server.pl"
if [ $? -eq 0 ]
then
    kill -9 `ps aux | grep -v grep | grep "/opt/phn/unity/JobServer/bin/job_server.pl"`
    if [ $? != 0 ]
    then
        echo "Error: Failed Stoping Job-Server"
        echo "Script will exit..."
        exit 70
    fi
fi

set -e

echo "Will calculate MD5 of the tarball and check it..."
cd /home/ubuntu/unity-tarballs/
md5sum -c /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz.md5
if [ $? != 0 ]
then
   echo "Error: tarball unity.R${REVISION}.tar.gz is corrupted, MD5 values differ"
   echo "Script will exit..."
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
   echo "Script will exit..."
   exit 2
fi

if [ -L /opt/phn/unity ]
then
    unlink /opt/phn/unity
fi
cd /opt/phn/
ln -s unity.R${REVISION} unity

echo "Will install Phenome R package...."
cd /opt/phn/unity/R
R CMD INSTALL phenome

if [ $? != 0 ]
then
    echo "Error: There was a problem installing Phenome R package"
    echo "Script will exit..."
    exit 6
fi

echo "Will make R scripts executable...."
chmod +x /opt/phn/unity/R/*.r

if [ $? != 0 ]
then
    echo "Error: There was a problem making R scripts executable"
    echo "Script will exit..."
    exit 98
fi

# Rebuild CSO Release directory
cd /opt/phn/unity/CSO
make

# Update revision in job_server.conf
perl -pi -e "s/revision \d+/revision ${REVISION}/g" /home/ubuntu/files/job_server.conf

# Copy to /opt/phn/unity/JobServer
cp /home/ubuntu/files/job_server* /opt/phn/unity/JobServer || exit 301

# Update revision in webapp.conf
perl -pi -e "s/revision \d+/revision ${REVISION}/g" /home/ubuntu/files/webapp.conf

# Copy to /opt/phn/unity/WebApp
cp /home/ubuntu/files/webapp* /opt/phn/unity/WebApp || exit 302

# Restart Cron service
/etc/init.d/cron restart || exit 303

echo "update-job-server-application.sh script finished successfully!!!"

