#!/bin/bash

################################### for docker ################################
# TZ="Europe/Kiev"                                                           ##
# ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone ##

# ln -s /opt/phn/unity.R13026 /opt/phn/unity
# ln -s /opt/phn/unity/WebApp/lib /srv/vhosts/unity/lib
# ln -s /opt/phn/unity/WebApp/root /srv/vhosts/unity/root

###############################################################################


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
    for i in  mc git unzip gcc mysql-client libcpanplus-perl libcatalyst-devel-perl libtext-csv-perl libdbix-class-perl liblog-log4perl-perl  perlmagick libgraphics-magick-perl libdatetime-format-mysql-perl libmail-sendmail-perl libemail-sender-perl libemail-mime-perl sendmail nfs-common libswitch-perl apache2 apache2-utils libapache2-mod-fcgid libapache2-mod-gnutls libcatalyst-plugin-scheduler-perl libcatalyst-plugin-smarturi-perl libcatalystx-simplelogin-perl libcatalystx-simplelogin-perl libfcgi-perl libfcgi-procmanager-perl libarchive-zip-perl libdbd-mysql-perl ;do 
        echo "install package $i"
        apt-get install -y $i || exit 1
    done

    echo "======================================================="
    echo "======================================================="
    echo "apt-get stage finished succesfully"
    echo "======================================================="
    echo "======================================================="

}

perl_lib() {
    for i in Catalyst::Runtime Catalyst::Plugin::ConfigLoader Catalyst::Plugin::Session Catalyst::Plugin::Static::Simple Catalyst::SaltedHash Catalyst::JWT Excel::Writer::XLSX PDF::API2 PDF::Table Data::UUID Catalyst::Plugin::Email Email::Stuffer Image::Thumbnail Excel::Writer::XLSX Barcode::Code128 Catalyst::Plugin::Session::Store::DBIC Catalyst::Authentication::Store::DBIx::Class Crypt::SaltedHash DBD::mysql Amazon::SQS::Simple Net::Amazon::S3 PDF::Table Crypt::JWT ;do
        echo "install perl lib $i"
        PERL_MM_USE_DEFAULT=1 perl -MCPAN -e "install ${i}" || exit 1
    done
    echo "======================================================="
    echo "======================================================="
    echo "perl lib stage finished succesfully"
    echo "======================================================="
    echo "======================================================="
}

chmod_conf() {

    declare -a arr_path=("/usr/local/share/perl" 
            "/etc/perl"
            "/usr/lib/perl*"
            "/usr/share/perl*"
            )
    
    for str in ${arr_path[@]}; do
        chmod -R 775 $str
    done
    echo "======================================================="
    echo "======================================================="
    echo "chmod conf stage finished succesfully"
    echo "======================================================="
    echo "======================================================="
}

php_package(){

    apt update
    for i in  php7.4 php7.4-cli php7.4-common php7.4-json php7.4-opcache  php7.4-mysql php7.4-mbstring  php7.4-zip php7.4-fpm php7.4-intl php7.4-simplexml  ;do 
        echo "install package $i"
        apt-get install -y $i || exit 1
    done

    echo "======================================================="
    echo "======================================================="
    echo "apt-get stage finished succesfully"
    echo "======================================================="
    echo "======================================================="

}

download_api(){

   mkdir -p /home/ubuntu/unity-tarballs
   mkdir -p /srv/vhosts/unity/script
   mkdir -p /home/ubuntu/files
   mkdir -p /opt/phn

    if [ "$CUSTOMERACCOUNTID" == "$DEVOPSACCOUNTID" ]; then
        aws s3 cp s3://phn-p2g-dist/unity.R${REVISION}.tar.gz /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz --region eu-west-1
        aws s3 cp s3://phn-p2g-dist/unity.R${REVISION}.tar.gz.md5 /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz.md5 --region eu-west-1
    else
        aws s3 cp s3://phn-p2g-dist/unity.R${REVISION}.tar.gz /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz --region eu-west-1 --profile ${ENVIRONMENT}
        aws s3 cp s3://phn-p2g-dist/unity.R${REVISION}.tar.gz.md5 /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz.md5 --region eu-west-1 --profile ${ENVIRONMENT}
    fi

   chown 0:0 /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz
   chown 0:0 /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz.md5

   chmod 755 /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz
   chmod 755 /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz.md5

}

create_config(){
    rm -rf /srv/vhosts/unity/webapp.conf
    cat <<EOF | tee -a /srv/vhosts/unity/webapp.conf >/dev/null
name WebApp
environment prod
reset_password_valid_hours 5
work_dir /tmp/web_server
storage_handler NFS
queue_handler DB
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
        mysql_local_infile 1
    </connect_info>
</Model::PHN2>

<Storage uploads>
    path ${LOCAL_STORAGE}
    ws_root ${WS_ROOT}
    work_dir /tmp/web_server/uploads
</Storage>

<Storage analyses>
    path ${LOCAL_STORAGE}
    ws_root ${WS_ROOT}
    work_dir /tmp/web_server/analyses
</Storage>

<Storage images>
    path ${LOCAL_STORAGE}
    ws_root ${WS_ROOT}
    work_dir /tmp/web_server/images
</Storage>

<Storage reports>
    path ${LOCAL_STORAGE}
    ws_root ${WS_ROOT}
    work_dir /tmp/web_server/reports
</Storage>

<DB>
</DB>

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

    rm -rf /srv/vhosts/unity/webapp_log.conf
    cat <<EOF | tee -a /srv/vhosts/unity/webapp_log.conf >/dev/null
log4perl.logger = DEBUG, Logfile

log4perl.appender.Screen = Log::Log4perl::Appender::Screen
log4perl.appender.Screen.layout = Log::Log4perl::Layout::PatternLayout
log4perl.appender.Screen.layout.ConversionPattern = %p %P %C::%M-%L %d - %m%n

log4perl.appender.Logfile = Log::Log4perl::Appender::File
log4perl.appender.Logfile.filename = /var/log/webapp.log
log4perl.appender.Logfile.layout = Log::Log4perl::Layout::PatternLayout
log4perl.appender.Logfile.layout.ConversionPattern = %d %p %C::%M-%L , %m%n
EOF

    rm -rf /etc/apache2/sites-enabled/unity.conf
    cat <<EOF | tee -a /etc/apache2/sites-enabled/unity.conf >/dev/null
<VirtualHost *:80>
    # To make it work behind HTTPS balancer this option is needed
    SetEnv HTTPS on

    ServerAdmin webmaster@phenome-networks.com
    ServerAlias *

    # if not specified, the global error log is used
    ErrorLog \${APACHE_LOG_DIR}/unity-error.log
    CustomLog \${APACHE_LOG_DIR}/unity-access.log combined

    # don't loose time with IP address lookups
    HostnameLookups Off

    # needed for named virtual hosts
    UseCanonicalName Off

    # configures the footer on server-generated documents
    ServerSignature On

    DocumentRoot /srv/vhosts/unity
    Alias /static /srv/vhosts/unity/root/static
    Alias /test /var/www/test.html
    Alias / /srv/vhosts/unity/script/webapp_fastcgi.fcgi/

    <Directory /srv/vhosts/unity/>
        Options FollowSymLinks
    </Directory>

    <Directory /srv/vhosts/unity/script/>
        Options ExecCGI
        Require all granted
    </Directory>

    <Directory /srv/vhosts/unity/root/static/>
        Require all granted
	Header  always set Cache-Control: "public, max-age=7884000"
    </Directory>

</VirtualHost>
EOF
}

install_api(){

    echo "##############################################################################################"
    echo "Hi, starting the script update-web-server-application.sh"
    echo "REVISION=${REVISION}"
    echo "##############################################################################################"

    # Stop web server
    /etc/init.d/apache2 stop

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

    if [ -L  /srv/vhosts/unity/lib ]
    then
        echo "Directory  /srv/vhosts/unity/lib exists and will be removed."
        unlink /srv/vhosts/unity/lib
    fi
    echo "Copying /opt/phn/unity/WebApp/lib directory..."
    ln -s /opt/phn/unity/WebApp/lib /srv/vhosts/unity/lib
    if [ -L  /srv/vhosts/unity/root ]
    then
        echo "Directory  /srv/vhosts/unity/root exists and will be removed."
       unlink /srv/vhosts/unity/root
    fi
    echo "Copying /opt/phn/unity/WebApp/root directory..."
    ln -s /opt/phn/unity/WebApp/root /srv/vhosts/unity/root

    echo "Will copy scripts to /srv/vhosts/unity.R${REVISION}/script/ directory..."
    cp -rf /opt/phn/unity/WebApp/script/* /srv/vhosts/unity/script/
    chmod +x /srv/vhosts/unity/script/*.pl
    chmod +x /srv/vhosts/unity/script/*.fcgi

    echo "Will copy /opt/phn/unity/WebApp/Makefile.PL to /srv/vhosts/unity.R${REVISION}/ directory..."
    cp -f /opt/phn/unity/WebApp/Makefile.PL /srv/vhosts/unity/

    # Update revision in webapp.conf
    perl -pi -e "s/revision \d+/revision ${REVISION}/g" /srv/vhosts/unity/webapp.conf

    # Copy to /home/ubuntu/files
    cp /srv/vhosts/unity/webapp* /home/ubuntu/files

    # Copy to /opt/phn/unity/WebApp
    cp /srv/vhosts/unity/webapp* /opt/phn/unity/WebApp || exit 301

    create_pheno20_clean_tmp

    # Configure cron-job
    rm -rf /var/spool/cron/root
    cat <<EOF | tee /var/spool/cron/root >/dev/null
0 1 * * * /home/ubuntu/scripts/pheno20_clean_tmp.sh
0 * * * * perl /opt/phn/unity/WebApp/script/webapp_users_actions_log.pl >> /var/log/users_actions.log 2>&1
EOF
    # crontab /etc/cron.d/web-server
    /usr/bin/crontab /var/spool/cron/root

    touch /var/www/test.html

    /etc/init.d/apache2 start

    echo "update-web-server-application.sh script finished successfully!!!"

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

config_fcgi() {
    rm -rf /etc/apache2/mods-available/fcgid.conf
    cat  <<EOF | tee -a /etc/apache2/mods-available/fcgid.conf >/dev/null
<IfModule mod_fcgid.c>
  FcgidConnectTimeout 20
  FcgidBusyTimeout 1000
  FcgidIOTimeout 1000

  FcgidIdleScanInterval 120
  FcgidIdleTimeout 300
  FcgidProcessLifeTime 3600

  FcgidMaxProcessesPerClass 10
  FcgidMinProcessesPerClass 4

  FcgidMaxRequestLen 134217728

  AddHandler    fcgid-script .fcgi

</IfModule>  
EOF
}

config_my_cnf() {
    rm -rf /root/.my.cnf
    rm -rf /home/ubuntu/.my.cnf
    cat  <<EOF | tee -a /root/.my.cnf >/dev/null
[client]
user = ${MYSQL_USER}
password = ${MYSQL_PASS}
host = ${MYSQL_HOST}
port = 3306
database = pheno20
EOF
    cp /root/.my.cnf /home/ubuntu/.my.cnf
    chmod 600 /root/.my.cnf /home/ubuntu/.my.cnf
    chown ubuntu:ubuntu /home/ubuntu/.my.cnf
    chown root:root /root/.my.cnf
}

config_apache_service() {
    sleep 10
    sed -i 's/PrivateTmp=true/PrivateTmp=false/g' /lib/systemd/system/apache2.service
    systemctl daemon-reload
    sed -i 's/LogFormat "%v:%p %h %l %u %t \\"%r\\" %>s %O \\"%{Referer}i\\" \\"%{User-Agent}i\\""/LogFormat "%h %l %u %t \\"%r\\" %>s %O \\"%{Referer}i\\" \\"%{User-Agent}i\\" \\"%{ms}T %p %{Host}i\\""/' /etc/apache2/apache2.conf
    sed -i 's/LogFormat "%h %l %u %t \\"%r\\" %>s %O \\"%{Referer}i\\" \\"%{User-Agent}i\\""/LogFormat "%h %l %u %t \\"%r\\" %>s %O \\"%{Referer}i\\" \\"%{User-Agent}i\\" \\"%{ms}T %p %{Host}i\\""/' /etc/apache2/apache2.conf
    systemctl restart apache2
}

install_flask(){
    echo "Install Flask and python requirements"
    apt install -y python3-pip
    pip3 install waitress 
    pip3 install Flask

    cd /opt/phn/unity/WebApp/lib/PHN/Python

    pip3 install -r requirements.txt

    echo "start Flask App"
    python3 waitress_server.py &

}

install_elastic_agent(){

    # Capture the static hostname into a variable
    statichostname=$(hostnamectl --static)

    number=$(aws ec2 describe-tags --filters "Name=resource-id,Values=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)" --query 'Tags[?Key==`Name`].Value' --output text | tr -dc '0-9')
    if [ -z "$number" ]; then
        echo "The string is empty or null."
        hostnamectl set-hostname "$ENVIRONMENT-web-$statichostname"
    else
        hostnamectl set-hostname "$ENVIRONMENT-web$number-$statichostname"
    fi
    
    curl -L -O https://artifacts.elastic.co/downloads/beats/elastic-agent/elastic-agent-8.9.2-linux-x86_64.tar.gz
    tar xzvf elastic-agent-8.9.2-linux-x86_64.tar.gz
    cd elastic-agent-8.9.2-linux-x86_64
    ./elastic-agent install --non-interactive --url=https://eb7afb93d5084ef79484bb19b9a20ea2.fleet.eu-west-1.aws.found.io:443 --enrollment-token=V0tvaWlvb0JjTVRMc19vMkRvU3U6RVNFYzRNWVRUMldPanctM29SbDFPZw==

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
export AWS_SECRET_ACCESS_KEY="C2HQLsihay3Y8DiqPfN644GDhu8IwqNiJzaHfnO1"

export REVISION="20873"
export MYSQL_HOST="10.200.32.21"
export MYSQL_USER="phenome"
export MYSQL_PASS="YzG!DaWBm$F9J9XhnY"
export LOCAL_STORAGE="/data/public/"
export WS_ROOT="https://phenome.gdmseeds.com/ /public"
export SQS="aws-on-prem"


glob_package
perl_lib
chmod_conf
php_package

a2dismod gnutls
a2enmod headers
a2enmod ssl
a2enmod rewrite
touch /var/log/webapp.log
chmod 777 /var/log/webapp.log
config_fcgi
service apache2 start
config_apache_service
download_api
create_config
install_api
config_my_cnf
install_flask
install_elastic_agent


echo "Init Web Server done! Have a nice day!"