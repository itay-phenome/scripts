#!/bin/bash

################################### for docker ################################
# TZ="Europe/Kiev"                                                           ##
# ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone ##

# ln -s /opt/phn/unity.R13026 /opt/phn/unity
# ln -s /opt/phn/unity/WebApp/lib /srv/vhosts/unity/lib
# ln -s /opt/phn/unity/WebApp/root /srv/vhosts/unity/root

###############################################################################

# Logging configuration
LOG_DIR="/var/log/job_server_install"
LOG_FILE="${LOG_DIR}/install_$(date +%Y%m%d_%H%M%S).log"
ERROR_LOG="${LOG_DIR}/errors_$(date +%Y%m%d_%H%M%S).log"
FAILED_PACKAGES_LOG="${LOG_DIR}/failed_packages.log"

# Create log directory
mkdir -p ${LOG_DIR}

# Redirect all output to log file
exec > >(tee -a "${LOG_FILE}")
exec 2> >(tee -a "${ERROR_LOG}" >&2)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO $(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR $(date '+%Y-%m-%d %H:%M:%S')]${NC} $1" >&2
}

log_warning() {
    echo -e "${YELLOW}[WARNING $(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

log_package_failure() {
    local package_type=$1
    local package_name=$2
    local error_msg=$3
    echo "$(date '+%Y-%m-%d %H:%M:%S') | ${package_type} | ${package_name} | ${error_msg}" >> "${FAILED_PACKAGES_LOG}"
}

# R_VERSION will be determined automatically (latest from CRAN)

# The values are provided via ENV variables
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
    log_info "Starting APT packages installation..."
    
    apt update || {
        log_error "Failed to run apt update"
        exit 1
    }
    
    local failed_packages=()
    
    # Basic packages
    for i in mc wget git unzip gcc mysql-client libcpanplus-perl libcatalyst-devel-perl libtext-csv-perl libdbix-class-perl liblog-log4perl-perl perlmagick libgraphics-magick-perl libdatetime-format-mysql-perl libmail-sendmail-perl libemail-sender-perl libemail-mime-perl sendmail nfs-common libswitch-perl libcatalyst-plugin-scheduler-perl libcatalyst-plugin-smarturi-perl libcatalystx-simplelogin-perl libcatalystx-simplelogin-perl libfcgi-perl libfcgi-procmanager-perl libarchive-zip-perl libdbd-mysql-perl curl cpanminus ;do 
        log_info "Installing APT package: $i"
        if apt-get install -y $i; then
            log_info "✓ Successfully installed: $i"
        else
            log_error "✗ Failed to install: $i"
            log_package_failure "APT" "$i" "apt-get install failed"
            failed_packages+=("$i")
        fi
    done

    if [ ${#failed_packages[@]} -gt 0 ]; then
        log_error "The following basic APT packages failed: ${failed_packages[*]}"
        exit 1
    fi

    log_info "======================================================="
    log_info "Basic packages installation completed"
    log_info "======================================================="
    
    # Additional build packages
    log_info "Installing additional build packages..."
    failed_packages=()
    
    for i in build-essential gfortran fort77 libreadline-dev xorg-dev liblzma-dev libblas-dev gcc-multilib libbz2-dev libpcre2-dev libcurl4-openssl-dev default-jdk ;do 
        log_info "Installing build package: $i"
        if apt-get install -y $i; then
            log_info "✓ Successfully installed: $i"
        else
            log_error "✗ Failed to install: $i"
            log_package_failure "APT-BUILD" "$i" "apt-get install failed"
            failed_packages+=("$i")
        fi
    done
    
    if [ ${#failed_packages[@]} -gt 0 ]; then
        log_error "The following build packages failed: ${failed_packages[*]}"
        exit 1
    fi
    
    log_info "======================================================="
    log_info "Build packages installation completed"
    log_info "======================================================="
}

perl_lib() {
    log_info "Starting Perl modules installation..."
    
    local failed_modules=()
    local successful_modules=()
    
    # Array of Perl modules to install
    local perl_modules=(
        "Catalyst::Runtime"
        "Catalyst::Plugin::ConfigLoader"
        "Catalyst::Plugin::Session"
        "Catalyst::Plugin::Static::Simple"
        "Catalyst::Plugin::Authentication"
        "Catalyst::Authentication::Store::DBIx::Class"
        "Catalyst::Plugin::Session::Store::DBIC"
        "Crypt::SaltedHash"
        "Excel::Writer::XLSX"
        "PDF::API2"
        "PDF::Table"
        "Data::UUID"
        "Catalyst::Plugin::Email"
        "Email::Stuffer"
        "Image::Thumbnail"
        "Barcode::Code128"
        "DBD::mysql"
        "Net::Address::IP::Local"
        "Amazon::SQS::Simple"
        "Net::Amazon::S3"
        "Crypt::JWT"
        "Moo"
        "Moose"
    )
    
    for module in "${perl_modules[@]}"; do
        log_info "Installing Perl module: $module"
        
        # Create a temporary log for this module
        local module_log="${LOG_DIR}/perl_${module//::/_}_$(date +%s).log"
        
        if cpanm --notest "$module" > "$module_log" 2>&1; then
            log_info "✓ Successfully installed: $module"
            successful_modules+=("$module")
            # Clean up successful module log
            rm -f "$module_log"
        else
            log_error "✗ Failed to install: $module"
            log_error "   Check detailed log: $module_log"
            log_package_failure "PERL" "$module" "cpanm failed - see $module_log"
            failed_modules+=("$module")
            
            # Extract and log the error
            if [ -f "$module_log" ]; then
                log_error "   Last 10 lines of error:"
                tail -10 "$module_log" | while read line; do
                    log_error "   $line"
                done
            fi
        fi
    done
    
    log_info "======================================================="
    log_info "Perl Installation Summary:"
    log_info "  Successful: ${#successful_modules[@]} modules"
    log_info "  Failed: ${#failed_modules[@]} modules"
    
    if [ ${#failed_modules[@]} -gt 0 ]; then
        log_error "The following Perl modules failed to install:"
        for module in "${failed_modules[@]}"; do
            log_error "  - $module"
        done
        
        # Check critical modules
        local critical_modules=("Catalyst::Runtime" "DBD::mysql")
        for critical in "${critical_modules[@]}"; do
            if [[ " ${failed_modules[@]} " =~ " ${critical} " ]]; then
                log_error "Critical module '$critical' failed to install. Aborting."
                exit 1
            fi
        done
        
        log_warning "Non-critical modules failed. Continuing installation..."
    fi
    
    log_info "======================================================="
}

r_build() {
    log_info "Starting R installation..."
    
    # Install R prerequisites
    log_info "Installing R prerequisites and dependencies..."
    local r_deps=(
        "software-properties-common"
        "dirmngr"
        "gfortran"
        "libreadline6-dev"
        "libx11-dev"
        "libxt-dev"
        "libpng-dev"
        "libjpeg-dev"
        "libcairo2-dev"
        "xvfb"
        "libbz2-dev"
        "libzstd-dev"
        "liblzma-dev"
        "libcurl4-openssl-dev"
        "texinfo"
        "texlive"
        "texlive-fonts-extra"
        "cmake"
        "unixodbc"
        "unixodbc-dev"
        "screen"
        "wget"
        "libpcre2-dev"
        "gdebi-core"
        "libxml2-dev"
        "libglpk-dev"
    )
    
    local failed_deps=()
    for dep in "${r_deps[@]}"; do
        if apt-get install -y "$dep"; then
            log_info "✓ Installed R dependency: $dep"
        else
            log_warning "✗ Failed to install R dependency: $dep"
            failed_deps+=("$dep")
        fi
    done
    
    if [ ${#failed_deps[@]} -gt 0 ]; then
        log_warning "Some R dependencies failed, but continuing: ${failed_deps[*]}"
    fi
    
    # Add CRAN repository for latest R
    log_info "Adding CRAN repository..."
    wget -qO- https://cloud.r-project.org/bin/linux/ubuntu/marutter_pubkey.asc | tee -a /etc/apt/trusted.gpg.d/cran_ubuntu_key.asc
    add-apt-repository -y "deb https://cloud.r-project.org/bin/linux/ubuntu $(lsb_release -cs)-cran40/"
    
    apt update || {
        log_error "Failed to update after adding CRAN repository"
        exit 1
    }
    
    # Install R base
    log_info "Installing R base and development tools..."
    if apt-get install -y r-base r-base-dev; then
        log_info "✓ R base installed successfully"
        R_VERSION=$(R --version | grep "R version" | awk '{print $3}')
        log_info "Installed R version: $R_VERSION"
    else
        log_error "Failed to install R base via apt"
        log_package_failure "R" "r-base" "apt-get install r-base failed"
        exit 1
    fi
    
    # Create symlinks
    log_info "Creating R symlinks..."
    ln -sf $(which R) /usr/local/bin/R
    ln -sf $(which Rscript) /usr/local/bin/Rscript
    ln -sf $(which R) /bin/R
    ln -sf $(which Rscript) /bin/Rscript
    
    log_info "======================================================="
    log_info "R installation completed"
    log_info "======================================================="
}

r_lib() {
    log_info "Starting R packages installation..."
    
    mkdir -p ./r_install
    cd r_install
    
    # Download archived packages
    log_info "Downloading archived R packages..."
    curl -O https://cran.r-project.org/src/contrib/Archive/GenABEL/GenABEL_1.8-0.tar.gz || log_warning "Failed to download GenABEL"
    curl -O https://cran.r-project.org/src/contrib/Archive/GenABEL.data/GenABEL.data_1.0.0.tar.gz || log_warning "Failed to download GenABEL.data"
    curl -O https://cran.r-project.org/src/contrib/Archive/estimability/estimability_1.4.1.tar.gz || log_warning "Failed to download estimability"

    cat <<'EOF' | tee ./install.R >/dev/null
#!/usr/bin/env Rscript

local({r <- getOption("repos")
       r["CRAN"] <- "https://cloud.r-project.org"
       options(repos=r)})

# Install pacman for package management
install.packages("pacman")

# Install packages from last.rds if it exists
if (file.exists("./../last.rds")) {
    mypks <- readRDS("./../last.rds")
    install.packages(mypks)
}

# Install BiocManager
install.packages("BiocManager", repos = "https://cloud.r-project.org")

# Install archived packages if they exist
archived_packages <- c("GenABEL.data_1.0.0.tar.gz", "GenABEL_1.8-0.tar.gz", "estimability_1.4.1.tar.gz")
existing_packages <- archived_packages[file.exists(archived_packages)]
if (length(existing_packages) > 0) {
    install.packages(existing_packages, repos = NULL)
}

# Install standard packages
install.packages("RODBC")
install.packages("lme4")
install.packages("car")

# Install Bioconductor packages
BiocManager::install(c("Rgraphviz", "graph"))

# Try to install lsmeans (might be replaced by emmeans in newer versions)
tryCatch({
    BiocManager::install("lsmeans")
}, error = function(e) {
    message("lsmeans not available, installing emmeans instead")
    install.packages("emmeans")
})

EOF

    log_info "Running R packages installation script..."
    local r_install_log="${LOG_DIR}/r_packages_install_$(date +%s).log"
    
    if Rscript install.R > "$r_install_log" 2>&1; then
        log_info "✓ R packages installation completed"
        rm -f "$r_install_log"
    else
        log_error "✗ Some R packages failed to install"
        log_error "   Check detailed log: $r_install_log"
        log_package_failure "R" "r_lib_packages" "Rscript install.R failed - see $r_install_log"
        
        # Show last lines of error
        tail -20 "$r_install_log" | while read line; do
            log_error "   $line"
        done
        
        log_warning "Continuing despite R packages failures..."
    fi
    
    cd ..
    rm -rf r_install
    
    log_info "======================================================="
    log_info "R packages installation finished"
    log_info "======================================================="
}

download_api(){
    log_info "Starting API download..."
    
    mkdir -p /home/ubuntu/unity-tarballs
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
    
    log_info "✓ API download completed"
}

create_config(){
    log_info "Creating configuration files..."
    
    rm -rf /home/ubuntu/files/job_server.conf
    cat <<EOF | tee /home/ubuntu/files/job_server.conf >/dev/null
max_procs 3
max_time 3600
is_persistent 1
idle_time 300
work_dir /tmp/job_server
storage_handler NFS
queue_handler DB
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

<NFS>
</NFS>

<Storage uploads>
    path ${LOCAL_STORAGE}
    ws_root ${WS_ROOT}
    work_dir /tmp/job_server/uploads
</Storage>

<Storage analyses>
    path ${LOCAL_STORAGE}
    ws_root ${WS_ROOT}
    work_dir /tmp/job_server/analyses
</Storage>

<Storage images>
    path ${LOCAL_STORAGE}
    ws_root ${WS_ROOT}
    work_dir /tmp/job_server/images
</Storage>

<Storage reports>
    path ${LOCAL_STORAGE}
    ws_root ${WS_ROOT}
    work_dir /tmp/job_server/reports
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

    log_info "✓ Configuration files created"
}

install_api(){
    log_info "Starting API installation..."
    log_info "REVISION=${REVISION}"

    log_info "Calculating MD5 checksum..."
    cd /home/ubuntu/unity-tarballs/
    md5sum -c /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz.md5
    if [ $? != 0 ]; then
        log_error "Tarball unity.R${REVISION}.tar.gz is corrupted, MD5 values differ"
        exit 2
    fi

    log_info "Extracting unity.R${REVISION}.tar.gz..."
    if [ -d /opt/phn/unity.R${REVISION} ]; then
        log_warning "Directory /opt/phn/unity.R${REVISION} exists, removing..."
        rm -rf /opt/phn/unity.R${REVISION}
    fi

    mkdir /opt/phn/unity.R${REVISION}
    tar xzf /home/ubuntu/unity-tarballs/unity.R${REVISION}.tar.gz -C /opt/phn/unity.R${REVISION}
    if [ $? != 0 ]; then
        log_error "Failed to extract tarball"
        exit 2
    fi

    if [ -L /opt/phn/unity ]; then
        unlink /opt/phn/unity
    fi
    cd /opt/phn/
    ln -s unity.R${REVISION} unity

    log_info "Making R scripts executable..."
    chmod +x /opt/phn/unity/JobServer/bin/R/*.R
    if [ $? != 0 ]; then
        log_error "Failed to make R scripts executable"
        exit 98
    fi

    # Update revisions
    perl -pi -e "s/revision \d+/revision ${REVISION}/g" /home/ubuntu/files/job_server.conf
    perl -pi -e "s/revision \d+/revision ${REVISION}/g" /home/ubuntu/files/webapp.conf

    # Copy configurations
    cp /home/ubuntu/files/job_server* /opt/phn/unity/JobServer || exit 301
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
    /etc/init.d/cron restart || exit 303

    log_info "✓ API installation completed"
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
    log_info "Starting ODBC installation..."
    
    mkdir -p ./odbc_install
    cd odbc_install
    
    log_info "Downloading MySQL ODBC connector (latest version)..."
    # Try to get latest version, fallback to known stable version
    if ! wget https://dev.mysql.com/get/Downloads/Connector-ODBC/8.4/mysql-connector-odbc-8.4.0-linux-glibc2.28-x86-64bit.tar.gz 2>/dev/null; then
        log_warning "Failed to download latest ODBC, trying fallback version..."
        wget https://downloads.mysql.com/archives/get/p/10/file/mysql-connector-odbc-8.0.17-linux-ubuntu19.04-x86-64bit.tar.gz || {
            log_error "Failed to download ODBC connector"
            log_package_failure "ODBC" "mysql-connector" "wget failed"
            cd ..
            rm -rf odbc_install
            return 1
        }
    fi
    
    log_info "Extracting ODBC connector..."
    tar xzf mysql-connector-odbc-*.tar.gz
    cd mysql-connector-odbc-*
    
    cp bin/* /usr/local/bin 2>/dev/null || log_warning "No bin files to copy"
    cp lib/* /usr/local/lib 2>/dev/null || log_warning "No lib files to copy"
    
    if command -v myodbc-installer &> /dev/null; then
        myodbc-installer -a -d -n "MySQL ODBC 8.0 Driver" -t "Driver=/usr/local/lib/libmyodbc8w.so"
        myodbc-installer -d -l
        log_info "✓ ODBC driver registered"
    else
        log_warning "myodbc-installer not found, skipping driver registration"
    fi
    
    cd ../../
    rm -rf odbc_install
    odbc_config
    
    log_info "✓ ODBC installation completed"
}

odbc_config() {
    log_info "Configuring ODBC..."
    
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
    
    log_info "✓ ODBC configuration completed"
}

virtual_display(){
    log_info "Setting up virtual display (Xvfb)..."
    
    # Ensure Xvfb is installed
    if ! command -v Xvfb &> /dev/null; then
        log_warning "Xvfb not found, installing..."
        apt-get install -y xvfb || {
            log_error "Failed to install Xvfb"
            return 1
        }
    fi
    
    rm -rf /etc/xvfb-server.sh
    cat <<'EOF' | tee /etc/xvfb-server.sh >/dev/null
#!/bin/bash
PID=$$
run_xvfb() {
    Xvfb :$PID -screen 0 800x600x16 &
    xvfb_pid=$!
    export DISPLAY=:$PID.0
}
run_xvfb

while true
do
    if ps -p $xvfb_pid > /dev/null
    then
        sleep 120
    else
        run_xvfb
        sleep 1000
    fi
done
EOF
    
    chmod 775 /etc/xvfb-server.sh
    
    log_info "✓ Virtual display configured"
}

perl_pdf() {
    log_info "Installing custom Perl PDF modules..."
    
    # Detect Perl version dynamically
    PERL_VERSION=$(perl -e 'print substr($^V, 1)')
    PERL_LIB_PATH="/usr/local/share/perl/${PERL_VERSION}"
    
    log_info "Detected Perl version: ${PERL_VERSION}"
    log_info "Using library path: ${PERL_LIB_PATH}"
    
    # Create directory if it doesn't exist
    mkdir -p "${PERL_LIB_PATH}/PDF"
    
    if [ "$CUSTOMERACCOUNTID" == "$DEVOPSACCOUNTID" ]; then
        aws s3 cp s3://phenome-devops-files/userdata/perl/API2.pm /home/ubuntu/API2.pm
        aws s3 cp s3://phenome-devops-files/userdata/perl/Table.pm /home/ubuntu/Table.pm
    else
        aws s3 cp s3://phenome-devops-files/userdata/perl/API2.pm /home/ubuntu/API2.pm --profile ${ENVIRONMENT}
        aws s3 cp s3://phenome-devops-files/userdata/perl/Table.pm /home/ubuntu/Table.pm --profile ${ENVIRONMENT}
    fi
    
    if [ -f /home/ubuntu/API2.pm ] && [ -f /home/ubuntu/Table.pm ]; then
        /bin/cp -rf /home/ubuntu/API2.pm "${PERL_LIB_PATH}/PDF/"
        /bin/cp -rf /home/ubuntu/Table.pm "${PERL_LIB_PATH}/PDF/"
        
        chown root:root "${PERL_LIB_PATH}/PDF/Table.pm"
        chown root:root "${PERL_LIB_PATH}/PDF/API2.pm"
        
        chmod 444 "${PERL_LIB_PATH}/PDF/Table.pm"
        chmod 444 "${PERL_LIB_PATH}/PDF/API2.pm"
        
        rm -rf /home/ubuntu/Table.pm /home/ubuntu/API2.pm
        
        log_info "✓ Custom Perl PDF modules installed"
    else
        log_warning "Failed to download custom Perl PDF modules from S3"
        log_package_failure "PERL-CUSTOM" "PDF modules" "S3 download failed"
    fi
}

config_my_cnf() {
    log_info "Configuring MySQL client..."
    
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
    
    log_info "✓ MySQL client configured"
}

install_liquibase() {
    log_info "Installing Liquibase..."
    
    apt update
    if snap install liquibase; then
        ln -sf /snap/liquibase/current /opt/liquibase
        
        rm -rf /home/ubuntu/files/liquibase.properties
        cat <<EOF | tee -a /home/ubuntu/files/liquibase.properties >/dev/null
driver: com.mysql.jdbc.Driver
classpath=connector/mysql-connector-java-5.1.18-bin.jar

url: jdbc:mysql://${MYSQL_HOST}/pheno20
username: ${MYSQL_USER}
password: ${MYSQL_PASS}
EOF
        
        log_info "✓ Liquibase installed"
    else
        log_error "Failed to install Liquibase via snap"
        log_package_failure "LIQUIBASE" "liquibase" "snap install failed"
    fi
}

install_elastic_agent(){
    log_info "Installing Elastic Agent..."
    
    # Capture the static hostname into a variable
    statichostname=$(hostnamectl --static)

    number=$(aws ec2 describe-tags --filters "Name=resource-id,Values=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)" --query 'Tags[?Key==`Name`].Value' --output text | tr -dc '0-9')
    if [ -z "$number" ]; then
        hostnamectl set-hostname "$ENVIRONMENT-job-$statichostname"
    else
        hostnamectl set-hostname "$ENVIRONMENT-job$number-$statichostname"
    fi
    
    cd /tmp
    
    # Try to get latest version dynamically, fallback to known stable version
    log_info "Downloading Elastic Agent..."
    if ! curl -L -O https://artifacts.elastic.co/downloads/beats/elastic-agent/elastic-agent-8.17.0-linux-x86_64.tar.gz; then
        log_warning "Failed to download latest version, trying fallback..."
        curl -L -O https://artifacts.elastic.co/downloads/beats/elastic-agent/elastic-agent-8.9.2-linux-x86_64.tar.gz || {
            log_error "Failed to download Elastic Agent"
            log_package_failure "ELASTIC" "elastic-agent" "Download failed"
            return 1
        }
    fi
    
    tar xzvf elastic-agent-*-linux-x86_64.tar.gz
    cd elastic-agent-*-linux-x86_64
    
    # Install with enrollment token
    ./elastic-agent install --non-interactive --url=https://eb7afb93d5084ef79484bb19b9a20ea2.fleet.eu-west-1.aws.found.io:443 --enrollment-token=YzZyS2tvb0JjTVRMc19vMi11a3Q6RU0tRGtoSlVRcHVUTG1qN1AtSzBqZw==
    
    log_info "✓ Elastic Agent installed"
}


# Main execution starts here
cd /home/ubuntu

log_info "======================================================="
log_info "Starting Job Server Installation"
log_info "Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"
log_info "======================================================="

# Install AWS CLI
log_info "Installing AWS CLI v2..."
apt update
apt install curl unzip -y
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "/tmp/awscliv2.zip"
unzip -q /tmp/awscliv2.zip -d /tmp
/tmp/aws/install
ln -sf /usr/local/bin/aws /bin/aws
log_info "✓ AWS CLI installed"

# Environment variables should be set externally
# Example (DO NOT hardcode credentials in production):
# export AWS_ACCESS_KEY_ID="your-key-here"
# export AWS_SECRET_ACCESS_KEY="your-secret-here"
# export REVISION="20873"
# export MYSQL_HOST="your-db-host"
# export MYSQL_USER="your-db-user"
# export MYSQL_PASS="your-db-password"
# export LOCAL_STORAGE="/data/public/"
# export WS_ROOT="https://phenome.gdmseeds.com/ /public"
# export SQS="aws-on-prem"
# export ENVIRONMENT="production"
# export CUSTOMERACCOUNTID="123456"
# export DEVOPSACCOUNTID="654321"

# Execute installation functions
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
config_my_cnf
install_liquibase
install_elastic_agent

log_info "Waiting 10 seconds before starting job server..."
sleep 10

log_info "Starting job server..."
/usr/bin/perl /opt/phn/unity/JobServer/bin/job_server.pl &

log_info "======================================================="
log_info "======================================================="
log_info "Init Job Server done! Have a nice day!"
log_info "======================================================="
log_info "Installation Summary:"
log_info "  Main log: ${LOG_FILE}"
log_info "  Error log: ${ERROR_LOG}"
log_info "  Failed packages: ${FAILED_PACKAGES_LOG}"
log_info "======================================================="

# Generate summary report
echo ""
log_info "Generating installation summary..."

if [ -f "${FAILED_PACKAGES_LOG}" ] && [ -s "${FAILED_PACKAGES_LOG}" ]; then
    log_warning "⚠ Some packages failed to install!"
    log_warning "Failed packages summary:"
    cat "${FAILED_PACKAGES_LOG}" | awk -F'|' '{print "  " $2 " - " $3}' | sort -u
    log_warning ""
    log_warning "Please review ${FAILED_PACKAGES_LOG} for details"
else
    log_info "✓ All packages installed successfully!"
fi

log_info ""
log_info "For detailed information, check:"
log_info "  • Full installation log: ${LOG_FILE}"
log_info "  • Error details: ${ERROR_LOG}"
log_info ""
log_info "Installation completed at: $(date '+%Y-%m-%d %H:%M:%S')"
log_info "======================================================="
log_info "======================================================="
