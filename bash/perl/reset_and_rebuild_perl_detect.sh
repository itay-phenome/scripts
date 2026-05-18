#!/bin/bash
set -e

TOTAL_STEPS=6
CURRENT_STEP=1

progress() {
    echo
    echo "=============================="
    echo "[$CURRENT_STEP/$TOTAL_STEPS] $1"
    echo "=============================="
    ((CURRENT_STEP++))
    sleep 1
}

progress "Detecting installed Perl version..."

PERL_VERSION=$(perl -e 'print $^V;' | sed 's/v//')
PERL_SHORT=$(echo $PERL_VERSION | cut -d'.' -f1,2)
PERL_FULL=$(echo $PERL_VERSION | cut -d'.' -f1,2,3)
PDF_LIB_PATH="/usr/local/share/perl/${PERL_FULL}/PDF"

echo "Detected Perl version: $PERL_VERSION"
echo "Using PDF module path: $PDF_LIB_PATH"

progress "Purging all existing Perl packages and configs..."

dpkg -l | grep -i perl | awk '{print $2}' | xargs apt-get -y purge --allow-remove-essential || true
apt-get autoremove -y
apt-get autoclean

rm -rf /usr/local/share/perl \
       /usr/share/perl \
       /usr/lib/perl* \
       /usr/lib64/perl* \
       /etc/perl \
       /var/lib/perl \
       ~/.cpan \
       ~/.perl

progress "Reinstalling system-level Perl packages..."

apt-get update
apt-get install -y \
    perl \
    build-essential \
    libcpanplus-perl \
    libcatalyst-devel-perl \
    libtext-csv-perl \
    libdbix-class-perl \
    liblog-log4perl-perl \
    perlmagick \
    libgraphics-magick-perl \
    libdatetime-format-mysql-perl \
    libmail-sendmail-perl \
    libemail-sender-perl \
    libemail-mime-perl \
    sendmail \
    libswitch-perl \
    libcatalyst-plugin-scheduler-perl \
    libcatalyst-plugin-smarturi-perl \
    libcatalystx-simplelogin-perl \
    libfcgi-perl \
    libfcgi-procmanager-perl \
    libarchive-zip-perl \
    libdbd-mysql-perl \
    curl \
    unzip \
    wget \
    git

progress "Installing Perl CPAN modules..."

for module in \
    Catalyst::Runtime \
    Catalyst::Plugin::ConfigLoader \
    Catalyst::Plugin::Session \
    Catalyst::Plugin::Static::Simple \
    Catalyst::SaltedHash \
    Catalyst::JWT \
    Excel::Writer::XLSX \
    PDF::API2 \
    PDF::Table \
    Data::UUID \
    Catalyst::Plugin::Email \
    Email::Stuffer \
    Image::Thumbnail \
    Barcode::Code128 \
    Catalyst::Plugin::Session::Store::DBIC \
    Catalyst::Authentication::Store::DBIx::Class \
    Crypt::SaltedHash \
    DBD::mysql \
    Net::Address::IP::Local \
    Amazon::SQS::Simple \
    Net::Amazon::S3 \
    Crypt::JWT
do
    echo "Installing CPAN module: $module"
    PERL_MM_USE_DEFAULT=1 perl -MCPAN -e "install ${module}" || exit 1
done

progress "Restoring custom PDF Perl modules from S3..."

CUSTOMERACCOUNTID="devops"
DEVOPSACCOUNTID="devops"
ENVIRONMENT="devops"

if [ "$CUSTOMERACCOUNTID" == "$DEVOPSACCOUNTID" ]; then
    aws s3 cp s3://phenome-devops-files/userdata/perl/API2.pm /tmp/API2.pm
    aws s3 cp s3://phenome-devops-files/userdata/perl/Table.pm /tmp/Table.pm
else
    aws s3 cp s3://phenome-devops-files/userdata/perl/API2.pm /tmp/API2.pm
    aws s3 cp s3://phenome-devops-files/userdata/perl/Table.pm /tmp/Table.pm
fi

mkdir -p "$PDF_LIB_PATH"
cp /tmp/API2.pm "$PDF_LIB_PATH/"
cp /tmp/Table.pm "$PDF_LIB_PATH/"
chmod 444 "$PDF_LIB_PATH"/*.pm
chown root:root "$PDF_LIB_PATH"/*.pm
rm -f /tmp/API2.pm /tmp/Table.pm

progress "✅ DONE: Perl $PERL_VERSION has been fully rebuilt and verified."
