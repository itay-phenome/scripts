#!/bin/bash

################################### for docker ################################
# TZ="Europe/Kiev"                                                           ##
# ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone ##

# ln -s /opt/phn/unity.R13026 /opt/phn/unity
# ln -s /opt/phn/unity/WebApp/lib /srv/vhosts/unity/lib
# ln -s /opt/phn/unity/WebApp/root /srv/vhosts/unity/root

###############################################################################

# Logging configuration
LOG_DIR="/var/log/web_server_install"
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
    
    for i in mc git unzip gcc mysql-client libcpanplus-perl libcatalyst-devel-perl libtext-csv-perl libdbix-class-perl liblog-log4perl-perl perlmagick libgraphics-magick-perl libdatetime-format-mysql-perl libmail-sendmail-perl libemail-sender-perl libemail-mime-perl sendmail nfs-common libswitch-perl apache2 apache2-utils libapache2-mod-fcgid libapache2-mod-gnutls libcatalyst-plugin-scheduler-perl libcatalyst-plugin-smarturi-perl libcatalystx-simplelogin-perl libcatalystx-simplelogin-perl libfcgi-perl libfcgi-procmanager-perl libarchive-zip-perl libdbd-mysql-perl cpanminus ;do 
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
        log_error "The following APT packages failed to install: ${failed_packages[*]}"
        log_error "Check ${ERROR_LOG} for details"
        exit 1
    fi

    log_info "======================================================="
    log_info "======================================================="
    log_info "apt-get stage finished successfully"
    log_info "All logs saved to: ${LOG_FILE}"
    log_info "======================================================="
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
        log_error "Check ${FAILED_PACKAGES_LOG} for complete list"
        log_error "Check ${ERROR_LOG} for detailed errors"
        
        # Ask if we should continue despite failures
        log_warning "Some Perl modules failed. Continuing may cause issues."
        log_warning "Check logs and consider re-running: ${LOG_FILE}"
        
        # Exit if critical modules failed
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
    log_info "perl lib stage finished"
    log_info "======================================================="
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
    echo "chmod conf stage finished successfully"
    echo "======================================================="
    echo "======================================================="
}

php_package(){
    log_info "Starting PHP packages installation..."
    
    apt update || {
        log_error "Failed to run apt update for PHP"
        exit 1
    }
    
    local failed_packages=()
    
    for i in php php-cli php-common php-json php-opcache php-mysql php-mbstring php-zip php-fpm php-intl php-xml php-curl php-gd ;do 
        log_info "Installing PHP package: $i"
        if apt-get install -y $i; then
            log_info "✓ Successfully installed: $i"
        else
            log_error "✗ Failed to install: $i"
            log_package_failure "PHP" "$i" "apt-get install failed"
            failed_packages+=("$i")
        fi
    done

    if [ ${#failed_packages[@]} -gt 0 ]; then
        log_error "The following PHP packages failed to install: ${failed_packages[*]}"
        log_error "Check ${ERROR_LOG} for details"
        exit 1
    fi

    log_info "======================================================="
    log_info "PHP packages stage finished successfully"
    log_info "Installed PHP version:"
    php -v | head -1
    log_info "======================================================="

}

r_package(){
    log_info "Starting R installation and R packages..."
    
    # Install prerequisites
    log_info "Installing R prerequisites..."
    if ! apt-get install -y software-properties-common dirmngr; then
        log_error "Failed to install R prerequisites"
        log_package_failure "R" "prerequisites" "Failed to install software-properties-common or dirmngr"
        exit 1
    fi
    
    # Add CRAN repository
    log_info "Adding CRAN repository..."
    if ! wget -qO- https://cloud.r-project.org/bin/linux/ubuntu/marutter_pubkey.asc | tee -a /etc/apt/trusted.gpg.d/cran_ubuntu_key.asc; then
        log_warning "Failed to add CRAN GPG key, trying alternative method..."
    fi
    
    if ! add-apt-repository -y "deb https://cloud.r-project.org/bin/linux/ubuntu $(lsb_release -cs)-cran40/"; then
        log_error "Failed to add CRAN repository"
        log_package_failure "R" "repository" "Failed to add CRAN apt repository"
        exit 1
    fi
    
    apt update || {
        log_error "Failed to update after adding CRAN repository"
        exit 1
    }
    
    # Install R base
    log_info "Installing R base and development tools..."
    if ! apt-get install -y r-base r-base-dev; then
        log_error "Failed to install R base"
        log_package_failure "R" "r-base" "apt-get install r-base failed"
        exit 1
    fi
    
    log_info "✓ R base installed successfully"
    log_info "Installed R version:"
    R --version | head -1
    
    # Install R packages
    log_info "Installing R packages (this may take several minutes)..."
    
    local r_packages=("ggplot2" "dplyr" "tidyr" "readr" "data.table" "stringr" "lubridate" "jsonlite")
    local failed_r_packages=()
    local successful_r_packages=()
    
    for pkg in "${r_packages[@]}"; do
        log_info "Installing R package: $pkg"
        
        local r_log="${LOG_DIR}/R_${pkg}_$(date +%s).log"
        
        if R -e "install.packages('$pkg', repos='https://cloud.r-project.org/', dependencies=TRUE)" > "$r_log" 2>&1; then
            # Verify installation
            if R -e "library($pkg)" > /dev/null 2>&1; then
                log_info "✓ Successfully installed and verified: $pkg"
                successful_r_packages+=("$pkg")
                rm -f "$r_log"
            else
                log_error "✗ Installation succeeded but package $pkg cannot be loaded"
                log_package_failure "R" "$pkg" "Package installed but library() failed"
                failed_r_packages+=("$pkg")
            fi
        else
            log_error "✗ Failed to install R package: $pkg"
            log_error "   Check detailed log: $r_log"
            log_package_failure "R" "$pkg" "install.packages() failed - see $r_log"
            failed_r_packages+=("$pkg")
            
            # Log last lines of error
            if [ -f "$r_log" ]; then
                log_error "   Last 15 lines of error:"
                tail -15 "$r_log" | while read line; do
                    log_error "   $line"
                done
            fi
        fi
    done
    
    log_info "======================================================="
    log_info "R Installation Summary:"
    log_info "  Successful: ${#successful_r_packages[@]} packages"
    log_info "  Failed: ${#failed_r_packages[@]} packages"
    
    if [ ${#failed_r_packages[@]} -gt 0 ]; then
        log_warning "The following R packages failed to install:"
        for pkg in "${failed_r_packages[@]}"; do
            log_warning "  - $pkg"
        done
        log_warning "R is installed but some packages are missing"
        log_warning "You can manually install them later with: R -e \"install.packages('package_name')\""
    else
        log_info "All R packages installed successfully!"
    fi
    
    log_info "======================================================="
    log_info "R packages stage finished"
    log_info "======================================================="
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
    log_info "Starting Flask and Python installation..."
    
    # Install pip and venv
    log_info "Installing Python prerequisites..."
    if ! apt install -y python3-pip python3-venv; then
        log_error "Failed to install python3-pip or python3-venv"
        log_package_failure "PYTHON" "prerequisites" "apt install python3-pip python3-venv failed"
        exit 1
    fi
    
    # Create virtual environment
    log_info "Creating Python virtual environment..."
    if ! python3 -m venv /opt/phn/python-venv; then
        log_error "Failed to create virtual environment"
        log_package_failure "PYTHON" "venv" "python3 -m venv failed"
        exit 1
    fi
    
    source /opt/phn/python-venv/bin/activate || {
        log_error "Failed to activate virtual environment"
        exit 1
    }
    
    # Upgrade pip
    log_info "Upgrading pip..."
    if ! pip install --upgrade pip; then
        log_warning "Failed to upgrade pip, continuing with current version"
    fi
    
    # Install Flask and waitress
    log_info "Installing Flask and waitress..."
    local python_log="${LOG_DIR}/python_packages_$(date +%s).log"
    
    if pip install waitress Flask > "$python_log" 2>&1; then
        log_info "✓ Successfully installed Flask and waitress"
        rm -f "$python_log"
    else
        log_error "✗ Failed to install Flask or waitress"
        log_error "   Check detailed log: $python_log"
        log_package_failure "PYTHON" "Flask/waitress" "pip install failed - see $python_log"
        
        tail -20 "$python_log" | while read line; do
            log_error "   $line"
        done
        
        deactivate
        exit 1
    fi
    
    # Install requirements.txt if exists
    if [ -d /opt/phn/unity/WebApp/lib/PHN/Python ]; then
        cd /opt/phn/unity/WebApp/lib/PHN/Python
        
        if [ -f requirements.txt ]; then
            log_info "Installing packages from requirements.txt..."
            local req_log="${LOG_DIR}/python_requirements_$(date +%s).log"
            
            if pip install -r requirements.txt > "$req_log" 2>&1; then
                log_info "✓ Successfully installed requirements.txt packages"
                rm -f "$req_log"
            else
                log_error "✗ Some packages from requirements.txt failed"
                log_error "   Check detailed log: $req_log"
                log_package_failure "PYTHON" "requirements.txt" "pip install -r failed - see $req_log"
                
                # Show failed packages
                grep -i "error\|failed" "$req_log" | while read line; do
                    log_error "   $line"
                done
                
                log_warning "Continuing despite requirements.txt failures..."
            fi
        else
            log_info "No requirements.txt found, skipping"
        fi
    else
        log_warning "Directory /opt/phn/unity/WebApp/lib/PHN/Python not found"
    fi
    
    log_info "Starting Flask App..."
    if [ -f waitress_server.py ]; then
        python3 waitress_server.py &
        local flask_pid=$!
        sleep 2
        
        if kill -0 $flask_pid 2>/dev/null; then
            log_info "✓ Flask app started successfully (PID: $flask_pid)"
        else
            log_error "✗ Flask app failed to start"
            log_package_failure "PYTHON" "Flask app" "waitress_server.py failed to start"
        fi
    else
        log_warning "waitress_server.py not found, skipping Flask app start"
    fi
    
    deactivate
    
    log_info "======================================================="
    log_info "Flask installation finished"
    log_info "======================================================="
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
    
    # Install latest Elastic Agent - will download current version
    curl -L -O https://artifacts.elastic.co/downloads/beats/elastic-agent/elastic-agent-$(curl -s https://www.elastic.co/downloads/elastic-agent | grep -oP 'elastic-agent-\K[0-9]+\.[0-9]+\.[0-9]+' | head -1)-linux-x86_64.tar.gz || \
    curl -L -O https://artifacts.elastic.co/downloads/beats/elastic-agent/elastic-agent-8.17.0-linux-x86_64.tar.gz
    
    # Extract (will work with whatever version was downloaded)
    tar xzvf elastic-agent-*-linux-x86_64.tar.gz
    cd elastic-agent-*-linux-x86_64
    
    # Install with your enrollment token (you'll need to update this)
    ./elastic-agent install --non-interactive --url=https://eb7afb93d5084ef79484bb19b9a20ea2.fleet.eu-west-1.aws.found.io:443 --enrollment-token=V0tvaWlvb0JjTVRMc19vMkRvU3U6RVNFYzRNWVRUMldPanctM29SbDFPZw==

}

cd /home/ubuntu

# Install AWS CLI v2 (latest)
apt update
apt install curl unzip -y
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "/tmp/awscliv2.zip"
unzip /tmp/awscliv2.zip -d /tmp
/tmp/aws/install
ln -sf /usr/local/bin/aws /bin/aws


# Environment variables should be set externally or via secure parameter store
# Example (DO NOT hardcode credentials in production):
# export AWS_ACCESS_KEY_ID="your-key-here"
# export AWS_SECRET_ACCESS_KEY="your-secret-here"
# export REVISION="20873"
# export MYSQL_HOST="your-db-host"
# export MYSQL_USER="your-db-user"
# export MYSQL_PASS="your-db-pass"
# export LOCAL_STORAGE="/data/public/"
# export WS_ROOT="https://phenome.gdmseeds.com/ /public"
# export SQS="aws-on-prem"


glob_package
perl_lib
chmod_conf
php_package
r_package  # NEW: Install R packages

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


echo "======================================================="
echo "======================================================="
log_info "Init Web Server done! Have a nice day!"
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
echo "======================================================="
echo "======================================================="
