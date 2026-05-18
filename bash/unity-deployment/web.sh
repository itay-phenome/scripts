#!/bin/bash

# ════════════════════════════════════════════════════════════════
# web.sh — Full Unity Web Server Installation Script
# ════════════════════════════════════════════════════════════════

echo "================================================"
echo "  Unity Web Server - Full Installation"
echo "================================================"
echo ""
echo "Please provide the following configuration values:"
echo ""

read -p "Enter Unity revision number: "            REVISION
read -p "Enter MySQL/RDS host: "                   MYSQL_HOST
read -p "Enter MySQL user [phenome]: "             MYSQL_USER
MYSQL_USER=${MYSQL_USER:-phenome}
read -s -p "Enter MySQL password: "               MYSQL_PASS
echo
read -p "Enter AWS region (e.g. ap-south-1): "    BUCKET_REGION
read -p "Enter S3 bucket - uploads: "             BUCKET_UPLOADS
read -p "Enter S3 bucket - images: "              BUCKET_IMAGES
read -p "Enter S3 bucket - analyses: "            BUCKET_ANALYSES
read -p "Enter S3 bucket - reports: "             BUCKET_REPORTS
read -p "Enter S3 bucket - documents: "           BUCKET_DOCUMENTS
read -p "Enter SQS queue ARN: "                   SQS
read -p "Enter S3 dist bucket [phn-p2g-dist]: "   S3_DIST_BUCKET
S3_DIST_BUCKET=${S3_DIST_BUCKET:-phn-p2g-dist}

echo ""
echo "Starting installation for revision R${REVISION}..."

# ─────────────────────────────────────────────
# Global system packages
# ─────────────────────────────────────────────
glob_package(){
    apt update
    for i in mc git unzip gcc mysql-client libcpanplus-perl libcatalyst-devel-perl \
        libtext-csv-perl libdbix-class-perl liblog-log4perl-perl perlmagick \
        libgraphics-magick-perl libdatetime-format-mysql-perl libmail-sendmail-perl \
        libemail-sender-perl libemail-mime-perl sendmail nfs-common libswitch-perl \
        apache2 apache2-utils libapache2-mod-fcgid libapache2-mod-gnutls \
        libcatalyst-plugin-scheduler-perl libcatalyst-plugin-smarturi-perl \
        libcatalystx-simplelogin-perl libfcgi-perl libfcgi-procmanager-perl \
        libarchive-zip-perl libdbd-mysql-perl; do
        echo "Installing: $i"
        apt-get install -y $i || exit 1
    done
    echo "apt-get stage finished successfully"
}

# ─────────────────────────────────────────────
# Perl CPAN modules
# ─────────────────────────────────────────────
perl_lib() {
    for i in Catalyst::Runtime Catalyst::Plugin::ConfigLoader \
        Catalyst::Plugin::Session Catalyst::Plugin::Static::Simple \
        Catalyst::SaltedHash Catalyst::JWT Excel::Writer::XLSX \
        PDF::API2 PDF::Table Data::UUID Catalyst::Plugin::Email \
        Email::Stuffer Image::Thumbnail Barcode::Code128 \
        Catalyst::Plugin::Session::Store::DBIC \
        Catalyst::Authentication::Store::DBIx::Class \
        Crypt::SaltedHash DBD::mysql Amazon::SQS::Simple \
        Net::Amazon::S3 Crypt::JWT; do
        echo "Installing Perl module: $i"
        PERL_MM_USE_DEFAULT=1 perl -MCPAN -e "install ${i}" || exit 1
    done
    echo "Perl lib stage finished successfully"
}

# ─────────────────────────────────────────────
# Perl directory permissions
# ─────────────────────────────────────────────
chmod_conf() {
    for str in "/usr/local/share/perl" "/etc/perl" "/usr/lib/perl*" "/usr/share/perl*"; do
        chmod -R 775 $str
    done
}

# ─────────────────────────────────────────────
# PHP packages
# ─────────────────────────────────────────────
php_package(){
    apt update
    for i in php7.4 php7.4-cli php7.4-common php7.4-json php7.4-opcache \
        php7.4-mysql php7.4-mbstring php7.4-zip php7.4-fpm \
        php7.4-intl php7.4-simplexml; do
        apt-get install -y $i || exit 1
    done
}

# ─────────────────────────────────────────────
# Download Unity tarball from S3
# ─────────────────────────────────────────────
download_api(){
    mkdir -p /home/ubuntu/unity-tarballs /srv/vhosts/unity/script \
             /home/ubuntu/files /opt/phn

    aws s3 cp s3://${S3_DIST_BUCKET}/unity.R${REVISION}.tar.gz \
        /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz --region ${BUCKET_REGION}
    aws s3 cp s3://${S3_DIST_BUCKET}/unity.R${REVISION}.tar.gz.md5 \
        /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz.md5 --region ${BUCKET_REGION}

    chown 0:0 /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz
    chown 0:0 /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz.md5
    chmod 755 /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz
    chmod 755 /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz.md5
}

# ─────────────────────────────────────────────
# Create webapp.conf (uses prompted variables)
# ─────────────────────────────────────────────
create_config(){
    rm -rf /srv/vhosts/unity/webapp.conf
    cat <<EOF > /srv/vhosts/unity/webapp.conf
name WebApp
environment prod
reset_password_valid_hours 5
work_dir /tmp/web_server
storage_handler S3
queue_handler SQS
cookie_Secure true
cookie_SameSite Lax
revision ${REVISION}
email_sender support@phenome-networks.com
region ${BUCKET_REGION}

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
    bucket_name ${BUCKET_UPLOADS}
    ws_root https://s3.${BUCKET_REGION}.amazonaws.com
    work_dir /tmp/web_server/uploads
    region ${BUCKET_REGION}
</Storage>

<Storage images>
    bucket_name ${BUCKET_IMAGES}
    ws_root https://s3.${BUCKET_REGION}.amazonaws.com
    work_dir /tmp/web_server/images
    region ${BUCKET_REGION}
</Storage>

<Storage analyses>
    bucket_name ${BUCKET_ANALYSES}
    ws_root https://s3.${BUCKET_REGION}.amazonaws.com
    work_dir /tmp/web_server/analyses
    region ${BUCKET_REGION}
</Storage>

<Storage reports>
    bucket_name ${BUCKET_REPORTS}
    ws_root https://s3.${BUCKET_REGION}.amazonaws.com
    work_dir /tmp/web_server/reports
    region ${BUCKET_REGION}
</Storage>

<Storage documents>
    bucket_name ${BUCKET_DOCUMENTS}
    ws_root https://s3.${BUCKET_REGION}.amazonaws.com
    work_dir /tmp/web_server/documents
    region ${BUCKET_REGION}
</Storage>

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
    cat <<EOF > /srv/vhosts/unity/webapp_log.conf
log4perl.logger = DEBUG, Logfile
log4perl.appender.Logfile = Log::Log4perl::Appender::File
log4perl.appender.Logfile.filename = /var/log/webapp.log
log4perl.appender.Logfile.layout = Log::Log4perl::Layout::PatternLayout
log4perl.appender.Logfile.layout.ConversionPattern = %d %p %C::%M-%L , %m%n
EOF

    rm -rf /etc/apache2/sites-enabled/unity.conf
    cat <<EOF > /etc/apache2/sites-enabled/unity.conf
<VirtualHost *:80>
    SetEnv HTTPS on
    ServerAdmin webmaster@phenome-networks.com
    ServerAlias *
    ErrorLog \${APACHE_LOG_DIR}/unity-error.log
    CustomLog \${APACHE_LOG_DIR}/unity-access.log combined
    DocumentRoot /srv/vhosts/unity
    Alias /static /srv/vhosts/unity/root/static
    Alias / /srv/vhosts/unity/script/webapp_fastcgi.fcgi/
    <Directory /srv/vhosts/unity/script/>
        Options ExecCGI
        Require all granted
    </Directory>
    <Directory /srv/vhosts/unity/root/static/>
        Require all granted
        Header always set Cache-Control "public, max-age=7884000"
    </Directory>
</VirtualHost>
EOF
}

# ─────────────────────────────────────────────
# Install Unity tarball
# ─────────────────────────────────────────────
install_api(){
    /etc/init.d/apache2 stop

    cd /home/ubuntu/unity-tarballs/
    md5sum -c unity.R${REVISION}.tar.gz.md5 || exit 2

    if [ -d /opt/phn/unity.R${REVISION} ]; then
        rm -rf /opt/phn/unity.R${REVISION}
    fi

    mkdir /opt/phn/unity.R${REVISION}
    tar xzf unity.R${REVISION}.tar.gz -C /opt/phn/unity.R${REVISION} || exit 2

    [ -L /opt/phn/unity ] && unlink /opt/phn/unity
    cd /opt/phn && ln -s unity.R${REVISION} unity

    [ -L /srv/vhosts/unity/lib ]  && unlink /srv/vhosts/unity/lib
    [ -L /srv/vhosts/unity/root ] && unlink /srv/vhosts/unity/root

    ln -s /opt/phn/unity/WebApp/lib  /srv/vhosts/unity/lib
    ln -s /opt/phn/unity/WebApp/root /srv/vhosts/unity/root

    cp -rf /opt/phn/unity/WebApp/script/* /srv/vhosts/unity/script/
    chmod +x /srv/vhosts/unity/script/*.pl
    chmod +x /srv/vhosts/unity/script/*.fcgi

    cp -f /opt/phn/unity/WebApp/Makefile.PL /srv/vhosts/unity/
    perl -pi -e "s/revision \d+/revision ${REVISION}/g" /srv/vhosts/unity/webapp.conf
    cp /srv/vhosts/unity/webapp* /home/ubuntu/files
    cp /srv/vhosts/unity/webapp* /opt/phn/unity/WebApp || exit 301

    /etc/init.d/apache2 start
}

# ─────────────────────────────────────────────
# MySQL .my.cnf (uses prompted credentials)
# ─────────────────────────────────────────────
config_my_cnf() {
    cat <<EOF > /root/.my.cnf
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

# ─────────────────────────────────────────────
# FCGI config
# ─────────────────────────────────────────────
config_fcgi() {
    cat <<EOF > /etc/apache2/mods-available/fcgid.conf
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
  AddHandler fcgid-script .fcgi
</IfModule>
EOF
}

# ─────────────────────────────────────────────
# Flask / Waitress install
# ─────────────────────────────────────────────
install_flask(){
    apt install -y python3-pip
    pip3 install waitress Flask
    cd /opt/phn/unity/WebApp/lib/PHN/Python
    pip3 install -r requirements.txt
    python3 waitress_server.py &
}

# ─────────────────────────────────────────────
# Apache service fix
# ─────────────────────────────────────────────
config_apache_service() {
    sleep 10
    sed -i 's/PrivateTmp=true/PrivateTmp=false/g' /lib/systemd/system/apache2.service
    systemctl daemon-reload
    systemctl restart apache2
}

# ─────────────────────────────────────────────
# Install AWS CLI v2
# ─────────────────────────────────────────────
cd /home/ubuntu
apt update
apt install curl unzip -y
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "/tmp/awscliv2.zip"
unzip /tmp/awscliv2.zip -d /tmp
/tmp/aws/install
ln -sf /usr/local/bin/aws /bin/aws

# ─────────────────────────────────────────────
# Run all stages
# ─────────────────────────────────────────────
glob_package
perl_lib
chmod_conf
php_package

a2dismod gnutls
a2enmod headers ssl rewrite
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

echo ""
echo "✅ Web Server installation complete! Revision R${REVISION} is live."
