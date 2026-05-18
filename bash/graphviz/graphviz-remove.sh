#!/bin/bash

LOG_FILE="/var/log/graphviz-removal-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "========== Graphviz Removal Script Started at $(date) =========="

echo "[1/6] Uninstalling Graphviz via APT..."
sudo apt-get remove --purge graphviz libgvc6 libcdt5 libcgraph6 libpathplan4 libgvpr2 -y || echo "APT removal skipped."

echo "[2/6] Removing manually installed binaries and libraries from /usr/local..."
sudo rm -vf /usr/local/bin/dot /usr/local/bin/twopi /usr/local/bin/neato
sudo rm -vf /usr/local/lib/libgvc* \
             /usr/local/lib/libcgraph* \
             /usr/local/lib/libcdt* \
             /usr/local/lib/libpathplan* \
             /usr/local/lib/pkgconfig/libgvc.pc \
             /usr/local/lib/pkgconfig/libcgraph.pc \
             /usr/local/lib/pkgconfig/libcdt.pc

echo "[3/6] Removing Graphviz headers from /usr/local/include..."
sudo rm -rvf /usr/local/include/graphviz

echo "[4/6] Refreshing dynamic linker cache..."
sudo ldconfig

echo "[5/6] Checking for IPC::Run Perl module..."
perl -MIPC::Run -e 'print "IPC::Run is installed\\n"' 2>/dev/null || {
  echo "Installing IPC::Run via CPAN..."
  sudo cpan -i IPC::Run
}

echo "[6/6] Graphviz removal completed at $(date)"
echo "Log saved to: $LOG_FILE"

