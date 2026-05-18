#!/bin/bash

################################### for docker ################################
# TZ="Europe/Kiev"                                                           ##
# ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone ##

# ln -s /opt/phn/unity.R13026 /opt/phn/unity
# ln -s /opt/phn/unity/WebApp/lib /srv/vhosts/unity/lib
# ln -s /opt/phn/unity/WebApp/root /srv/vhosts/unity/root

###############################################################################

R_VERSION="4.1.2"

# The values are provided vie ENV variables
# REVISION=$1

# MYSQL_HOST="ubuntu-rds-master.cpbddswbytl4.eu-west-2.rds.amazonaws.com"
# MYSQL_USER="root"
# MYSQL_PASS="P5asswords"

# BUCKET_UPLOADS="phenome-ubuntu-uploads"
# BUCKET_IMAGES="phenome-ubuntu-images"
# BUCKET_ANALYSES="phenome-ubuntu-analysis"
# BUCKET_REPORTS="phenome-ubuntu-images"
# BUCKET_DOCUMENTS="phenome-ubuntu-documents"
# BUCKET_REGION="eu-west-2"

# SQS="arn:aws:sqs:eu-west-2:524574648815:ubuntu-sqs-queue"


#global package
glob_package(){

    apt update
    for i in  mc wget git unzip gcc mysql-client libcpanplus-perl libcatalyst-devel-perl libtext-csv-perl libdbix-class-perl liblog-log4perl-perl  perlmagick libgraphics-magick-perl libdatetime-format-mysql-perl libmail-sendmail-perl libemail-sender-perl libemail-mime-perl sendmail nfs-common libswitch-perl libcatalyst-plugin-scheduler-perl libcatalyst-plugin-smarturi-perl libcatalystx-simplelogin-perl libcatalystx-simplelogin-perl libfcgi-perl libfcgi-procmanager-perl libarchive-zip-perl libdbd-mysql-perl curl ;do
        echo "install package $i"
        apt-get install -y $i || exit 1
    done

    echo "======================================================="
    echo "======================================================="
    echo "apt-get stage finished succesfully"
    echo "======================================================="
    echo "======================================================="

    for i in build-essential gfortran fort77 libreadline-dev xorg-dev liblzma-dev libblas-dev gcc-multilib libbz2-dev libpcre2-dev libcurl4-openssl-dev default-jdk ;do
        echo "install package $i"
        apt-get install -y $i || exit 1
    done
    echo "======================================================="
    echo "======================================================="
    echo "apt-get additional packege stage finished succesfully"
    echo "======================================================="
    echo "======================================================="
}

perl_lib() {
    for i in Catalyst::Runtime Catalyst::Plugin::ConfigLoader Catalyst::Plugin::Session Catalyst::Plugin::Static::Simple Catalyst::SaltedHash Catalyst::JWT Excel::Writer::XLSX PDF::API2 PDF::Table Data::UUID Catalyst::Plugin::Email Email::Stuffer Image::Thumbnail Excel::Writer::XLSX Barcode::Code128 Catalyst::Plugin::Session::Store::DBIC Catalyst::Authentication::Store::DBIx::Class Crypt::SaltedHash DBD::mysql Net::Address::IP::Local Amazon::SQS::Simple Net::Amazon::S3 PDF::Table Crypt::JWT ;do
        echo "install perl lib $i"
        PERL_MM_USE_DEFAULT=1 perl -MCPAN -e "install ${i}" || exit 1
    done
    echo "======================================================="
    echo "======================================================="
    echo "perl lib stage finished succesfully"
    echo "======================================================="
    echo "======================================================="
}

r_build() {
    if [[ ${R_VERSION} == "missing" ]]; then
        echo "Error - No R version specified"
        usage
    fi
    apt-get install -y gfortran libreadline6-dev libx11-dev libxt-dev \
                               libpng-dev libjpeg-dev libcairo2-dev xvfb \
                               libbz2-dev libzstd-dev liblzma-dev \
                               libcurl4-openssl-dev \
                               texinfo texlive texlive-fonts-extra \
                               cmake unixodbc unixodbc-dev \
                               screen wget libpcre2-dev gdebi-core
    R_MAJOR_VERSION=${R_VERSION:0:1}
    mkdir r_build
    cd r_build
    # wget -q https://cran.r-project.org/src/base/R-${R_MAJOR_VERSION}/R-${R_VERSION}.tar.gz

    # if [[ ${?} -ne 0 ]]; then
    #     echo "Error - Problem downloading R-${R_VERSION} - check output and try again"
    #     exit 1
    # fi

    # tar -zxvf R-${R_VERSION}.tar.gz

    # cd R-${R_VERSION}

    # # ./configure --enable-R-shlib --with-blas --with-lapack

    # # ./configure --enable-R-shlib
    # ./configure -prefix=/opt/R/${R_VERSION} --enable-R-shlib --enable-memory-profiling --with-blas --with-lapack --with-cairo --with-libpng --with-libtiff --with-jpeglib

    # make

    # make install

    curl -O https://cdn.rstudio.com/r/ubuntu-2004/pkgs/r-${R_VERSION}_1_amd64.deb

    gdebi -n r-${R_VERSION}_1_amd64.deb


    ln -s /opt/R/${R_VERSION}/bin/R /usr/local/bin/R
    ln -s /opt/R/${R_VERSION}/bin/Rscript /usr/local/bin/Rscript

    ln -s /opt/R/${R_VERSION}/bin/R /bin/R
    ln -s /opt/R/${R_VERSION}/bin/Rscript /bin/Rscript

    # cd ..
    cd ..
    rm -rf r_build
}

r_lib() {
    mkdir ./r_install
    cd r_install
    curl -O https://cran.r-project.org/src/contrib/Archive/GenABEL/GenABEL_1.8-0.tar.gz
    curl -O https://cran.r-project.org/src/contrib/Archive/GenABEL.data/GenABEL.data_1.0.0.tar.gz
    cat <<EOF | tee ./install.R >/dev/null
#!/usr/bin/env Rscript

local({r <- getOption("repos")
       r["CRAN"] <- "http://cran.r-project.org"
       options(repos=r)})
install.packages("pacman")

mypks <- readRDS("./../last.rds")
install.packages(mypks)

install.packages(c("GenABEL.data_1.0.0.tar.gz", "GenABEL_1.8-0.tar.gz"), repos = NULL)

install.packages("BiocManager")
install.packages("RODBC")
install.packages("lme4")
install.packages("car")

BiocManager::install("Rgraphviz")

EOF
    Rscript install.R
    cd ..
    rm -rf r_install
}

download_api(){

   mkdir -p /home/ubuntu/unity-tarballs
   mkdir -p /home/ubuntu/files
   mkdir -p /opt/phn

   aws s3 cp s3://phn-p2g-dist/unity.R${REVISION}.tar.gz /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz --region eu-west-1
   aws s3 cp s3://phn-p2g-dist/unity.R${REVISION}.tar.gz.md5 /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz.md5 --region eu-west-1

   chown 0:0 /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz
   chown 0:0 /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz.md5

   chmod 755 /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz
   chmod 755 /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz.md5

}

create_config(){
    rm -rf /home/ubuntu/files/job_server.conf
    cat <<EOF | tee /home/ubuntu/files/job_server.conf >/dev/null
max_procs 3
max_time 3600
is_persistent 1
idle_time 300
work_dir /tmp/job_server
storage_handler S3
queue_handler SQS
revision ${REVISION}
changelog 907
email_sender support@phenome-networks.com

<Schema::PHN2>
    <connect_info>
        dsn               dbi:mysql:database=pheno20;host=${MYSQL_HOST};port=3306
        user              ${MYSQL_USER}
        password          ${MYSQL_PASS}
        quote_names       1
        mysql_enable_utf8 1
    </connect_info>
    odbc_id pheno20
</Schema::PHN2>

<S3>
    access_key  YOUR_AWS_ACCESS_KEY_HERE
    secret_key  w5qdQmLgjzLrIx13OXT6IME3t/0aKa2chrUGV0WN
    # auth_method V4
    # region ${BUCKET_REGION}
#    encryption  AES256
</S3>

<Storage uploads>
    bucket_name ${BUCKET_UPLOADS}
    ws_root https://s3.${BUCKET_REGION}.amazonaws.com
    work_dir /tmp/job_server/uploads
</Storage>

<Storage images>
    bucket_name ${BUCKET_IMAGES}
    ws_root https://s3.${BUCKET_REGION}.amazonaws.com
    work_dir /tmp/job_server/images
</Storage>

<Storage analyses>
    bucket_name ${BUCKET_ANALYSES}
    ws_root https://s3.${BUCKET_REGION}.amazonaws.com
    work_dir /tmp/job_server/analyses
</Storage>

<Storage reports>
    bucket_name ${BUCKET_REPORTS}
    ws_root https://s3.${BUCKET_REGION}.amazonaws.com
    work_dir /tmp/job_server/reports
</Storage>

<Storage documents>
    bucket_name ${BUCKET_DOCUMENTS}
    ws_root https://s3.${BUCKET_REGION}.amazonaws.com
    work_dir /tmp/job_server/documents
</Storage>

<SQS>
    access_key YOUR_AWS_ACCESS_KEY_HERE
    secret_key w5qdQmLgjzLrIx13OXT6IME3t/0aKa2chrUGV0WN
</SQS>

<Queue>
    queue_name ${SQS}
</Queue>

EOF
    rm -rf /home/ubuntu/files/job_server_log.conf
    cat <<EOF | tee /home/ubuntu/files/job_server_log.conf >/dev/null
log4perl.logger = DEBUG, Logfile

log4perl.appender.Screen = Log::Log4perl::Appender::Screen
log4perl.appender.Screen.layout = Log::Log4perl::Layout::PatternLayout
log4perl.appender.Screen.layout.ConversionPattern = %p %P %C::%M-%L %d - %m%n

log4perl.appender.Logfile = Log::Log4perl::Appender::File
log4perl.appender.Logfile.filename = /var/log/job_server.log
log4perl.appender.Logfile.layout = Log::Log4perl::Layout::PatternLayout
log4perl.appender.Logfile.layout.ConversionPattern = %d %p %C::%M-%L , %m%n
EOF
    rm -rf /home/ubuntu/files/webapp.conf
    cat <<EOF | tee /home/ubuntu/files/webapp.conf >/dev/null
name WebApp
environment prod
reset_password_valid_hours 5
work_dir /tmp/web_server
storage_handler S3
queue_handler SQS
cookie_Secure true
cookie_SameSite Lax
revision ${REVISION}
changelog 907
email_sender support@phenome-networks.com

<Model::PHN2>
    <connect_info>
        dsn               dbi:mysql:database=pheno20;host=${MYSQL_HOST};port=3306
        user              ${MYSQL_USER}
        password          ${MYSQL_PASS}
        quote_names       1
        mysql_enable_utf8 1
    </connect_info>
</Model::PHN2>

<S3>
    access_key  YOUR_AWS_ACCESS_KEY_HERE
    secret_key  Az1PH89HN/bOeNOTpIqSAsOPZKgjqctrqQ4LSK4C
    # auth_method V4
    # region ${BUCKET_REGION}
</S3>

<Storage uploads>
    bucket_name ${BUCKET_UPLOADS}
    ws_root https://s3.${BUCKET_REGION}.amazonaws.com
    work_dir /tmp/web_server/uploads
</Storage>

<Storage images>
    bucket_name ${BUCKET_IMAGES}
    ws_root https://s3.${BUCKET_REGION}.amazonaws.com
    work_dir /tmp/web_server/images
</Storage>

<Storage analyses>
    bucket_name ${BUCKET_ANALYSES}
    ws_root https://s3.${BUCKET_REGION}.amazonaws.com
    work_dir /tmp/web_server/analyses
</Storage>

<Storage reports>
    bucket_name ${BUCKET_REPORTS}
    ws_root https://s3.${BUCKET_REGION}.amazonaws.com
    work_dir /tmp/web_server/reports
</Storage>

<Storage documents>
    bucket_name ${BUCKET_DOCUMENTS}
    ws_root https://s3.${BUCKET_REGION}.amazonaws.com
    work_dir /tmp/web_server/documents
</Storage>

<SQS>
    access_key YOUR_AWS_ACCESS_KEY_HERE
    secret_key Az1PH89HN/bOeNOTpIqSAsOPZKgjqctrqQ4LSK4C
</SQS>

<Queue other>
    queue_name ${SQS}
</Queue>

<Queue assoc>
    queue_name ${SQS}
</Queue>

<Queue analysis>
    queue_name ${SQS}
</Queue>
EOF
    rm -rf /home/ubuntu/files/webapp_log.conf
    cat <<EOF | tee /home/ubuntu/files/webapp_log.conf >/dev/null
log4perl.logger = DEBUG, Logfile

log4perl.appender.Screen = Log::Log4perl::Appender::Screen
log4perl.appender.Screen.layout = Log::Log4perl::Layout::PatternLayout
log4perl.appender.Screen.layout.ConversionPattern = %p %P %C::%M-%L %d - %m%n

log4perl.appender.Logfile = Log::Log4perl::Appender::File
log4perl.appender.Logfile.filename = /var/log/webapp.log
log4perl.appender.Logfile.layout = Log::Log4perl::Layout::PatternLayout
log4perl.appender.Logfile.layout.ConversionPattern = %d %p %C::%M-%L , %m%n
EOF

}

install_api(){

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

    # Update revision in job_server.conf
    perl -pi -e "s/revision \d+/revision ${REVISION}/g" /home/ubuntu/files/job_server.conf

    # Copy to /opt/phn/unity/JobServer
    cp /home/ubuntu/files/job_server* /opt/phn/unity/JobServer || exit 301

    # Update revision in webapp.conf
    perl -pi -e "s/revision \d+/revision ${REVISION}/g" /home/ubuntu/files/webapp.conf

    # Copy to /opt/phn/unity/WebApp
    cp /home/ubuntu/files/webapp* /opt/phn/unity/WebApp || exit 302

    create_pheno20_clean_tmp

    # Configure cron-job
    rm -rf /var/spool/cron/root
    touch /var/spool/cron/root
    cat <<EOF | tee /var/spool/cron/root >/dev/null
0,30 * * * * /usr/bin/perl /opt/phn/unity/JobServer/bin/job_server.pl
* * * * * /bin/bash /home/ubuntu/git/deploy-ami/ansible/roles/unity_job_server/scripts/start-job-server.sh
0 1 * * * /home/ubuntu/scripts/pheno20_clean_tmp.sh

EOF
    /usr/bin/crontab /var/spool/cron/root
    # Restart Cron service
    /etc/init.d/cron restart || exit 303

    echo "update-job-server-application.sh script finished successfully!!!"
}

create_pheno20_clean_tmp() {
    rm -rf /home/ubuntu/scripts/pheno20_clean_tmp.sh
    mkdir -p /home/ubuntu/scripts/
    cat  <<EOF | tee -a /home/ubuntu/scripts/pheno20_clean_tmp.sh >/dev/null
#! /bin/sh -x
find /tmp/phn -mtime +2 ! -name phn -exec rm {} \;

find /tmp/web_server /tmp/job_server -mtime +7  -type d ! -name analyses ! -name uploads ! -name images ! -name web_server ! -name job_server ! -name analysis ! -name reports -exec rm -rf {} \;
EOF
    chmod +x /home/ubuntu/scripts/pheno20_clean_tmp.sh
}

odbc_install() {
    mkdir -p ./odbc_install
    cd odbc_install
    wget https://downloads.mysql.com/archives/get/p/10/file/mysql-connector-odbc-8.0.17-linux-ubuntu19.04-x86-64bit.tar.gz
    gunzip mysql-connector-odbc-8.0.17-linux-ubuntu19.04-x86-64bit.tar.gz
    tar xvf mysql-connector-odbc-8.0.17-linux-ubuntu19.04-x86-64bit.tar
    cd mysql-connector-odbc-8.0.17-linux-ubuntu19.04-x86-64bit
    cp bin/* /usr/local/bin
    cp lib/* /usr/local/lib
    myodbc-installer -a -d -n "MySQL ODBC 8.0 Driver" -t "Driver=/usr/local/lib/libmyodbc8w.so"
    myodbc-installer -d -l
    cd ../../
    rm -rf odbc_install
    odbc_config

}

odbc_config() {
    rm -rf /etc/odbcinst.ini
    cat <<EOF | tee /etc/odbcinst.ini >/dev/null
[MySQL]
Driver=/usr/local/lib/libmyodbc8w.so
UsageCount=1
EOF
    rm -rf /etc/odbc.ini
    cat <<EOF | tee /etc/odbc.ini >/dev/null
[pheno20]
Driver          = MySQL
Database        = pheno20
Server          = ${MYSQL_HOST}
User            = ${MYSQL_USER}
Password        = ${MYSQL_PASS}
Port            = 3306
Option          = 65536
EOF
    chmod 744 /etc/odbc.ini
    chown root:root /etc/odbc.ini
    chmod 744 /etc/odbcinst.ini
    chown root:root /etc/odbcinst.ini

}

# virtual_display(){
#     rm -rf /etc/xvfb-server.sh
#     cat <<EOF | tee /etc/xvfb-server.sh >/dev/null
# #!/bin/bash
# PID=\$$
# run_xvfb() {
#     Xvfb :\$PID -screen 0 800x600x16 &
#     xvfb_pid=\$!
#     export DISPLAY=:\$PID.0
# }
# run_xvfb

# while true
# do
#     if ps -p \$xvfb_pid > /dev/null
#     then
#         sleep 120
#     else
#         run_xvfb
#         sleep 1000
#     fi
# done
# EOF
#     chmod 775 /etc/xvfb-server.sh
#     rm -rf /etc/cron.d/xvfb-server
#     # Configure cron-job
# #     cat <<EOF | tee /etc/cron.d/xvfb-server >/dev/null
# # @reboot root /bin/bash /etc/xvfb-server.sh
# # EOF
#     crontab xvfb-server
# }

perl_pdf() {

    aws s3 cp s3://phenome-devops-files/userdata/perl/API2.pm /home/ubuntu/API2.pm --region eu-west-1
    aws s3 cp s3://phenome-devops-files/userdata/perl/Table.pm /home/ubuntu/Table.pm --region eu-west-1

    /bin/cp -rf /home/ubuntu/API2.pm  /usr/local/share/perl/5.30.0/PDF/
    /bin/cp -rf /home/ubuntu/Table.pm /usr/local/share/perl/5.30.0/PDF/

    rm -rf /home/ubuntu/Table.pm
    rm -rf /home/ubuntu/API2.pm

    chown root:root /usr/local/share/perl/5.30.0/PDF/Table.pm
    chown root:root  /usr/local/share/perl/5.30.0/PDF/API2.pm

    chmod 444 /usr/local/share/perl/5.30.0/PDF/Table.pm
    chmod 444 /usr/local/share/perl/5.30.0/PDF/API2.pm

    echo "cp custom perl lib - done..."

}
cd /home/ubuntu

apt update
apt install curl unzip -y
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "/tmp/awscliv2.zip"
unzip /tmp/awscliv2.zip -d /tmp
/tmp/aws/install
ln -s /usr/local/bin/aws /bin/aws

#This is key for regual AWS account#
export AWS_ACCESS_KEY_ID="YOUR_AWS_ACCESS_KEY_HERE"
export AWS_SECRET_ACCESS_KEY="4Wv+3SaJP+5quvjpSx8+FmTxwp+5vO2Te0pMY5ZQ"

aws s3 cp s3://phenome-devops-files/userdata/last.rds /home/ubuntu/ --region eu-west-1

#Edit the following parameters: revision,RDS,buckets,sqs#
export REVISION="14689"
export MYSQL_HOST="ews-mum-rds.cf7gghvlnnan.ap-south-1.rds.amazonaws.com"
export MYSQL_USER="phenome"
export MYSQL_PASS="QfVKXqBID6v3Uyqlo1mb!"
export BUCKET_REGION="ap-south-1"
export BUCKET_UPLOADS="phenome-ews-files-upload"
export BUCKET_IMAGES="phenome-ews-files-image"
export BUCKET_ANALYSES="phenome-ews-files-analysis"
export BUCKET_REPORTS="phenome-ews-files-image"
export BUCKET_DOCUMENTS="phenome-ews-files-document"
export SQS="arn:aws:sqs:ap-south-1:059661153102:ews-mum-sqs-queuee"

glob_package
perl_lib
virtual_display
r_build
r_lib
odbc_install
download_api
create_config
perl_pdf
install_api

sleep 10

/usr/bin/perl /opt/phn/unity/JobServer/bin/job_server.pl &

echo "Init Job Server done! Have a nice day!"
