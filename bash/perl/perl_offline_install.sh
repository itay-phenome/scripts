#!/bin/bash

set -euo pipefail

LOG_FILE="/tmp/perl_offline_setup.log"
ERR_FILE="/tmp/perl_offline_setup_error.log"
TARBALL_DIR="/tmp/perl_tarballs"
MANIFEST_FILE="/tmp/perl_manifest.txt"

# Start fresh logs
echo "" > "$LOG_FILE"
echo "" > "$ERR_FILE"
exec 2>> "$ERR_FILE"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "========== Starting Perl Offline Environment Setup =========="

# Create tarball storage folder if not exists
mkdir -p "$TARBALL_DIR"

log "📦 Extracting list of installed Perl modules..."
perl -MExtUtils::Installed -MData::Dumper -e 'print Dumper([ExtUtils::Installed->new()->modules])' | \
  perl -ne 'if (/\"(.+?)\"/) { print "$1\n"; }' | sort | uniq > "$MANIFEST_FILE"

log "📄 Saved manifest to $MANIFEST_FILE"

log "⬇️  Downloading tarballs using CPAN..."
while read -r module; do
  log "📦 Downloading $module..."
  cpan -g "$module" >> "$LOG_FILE" 2>> "$ERR_FILE" || log "⚠️  Failed to download $module"
done < "$MANIFEST_FILE"

log "📁 Moving tarballs to $TARBALL_DIR..."
find . -maxdepth 1 -name "*.tar.gz" -exec mv -t "$TARBALL_DIR" {} +

log "✅ Tarballs prepared for offline use in $TARBALL_DIR"

log "📦 Installing modules system-wide from tarballs..."
cd "$TARBALL_DIR"

for tar in *.tar.gz; do
  log "🛠️ Installing $tar"
  tarball_dir=$(basename "$tar" .tar.gz)
  rm -rf "$tarball_dir"
  tar -xzf "$tar"
  cd "$tarball_dir"
  perl Makefile.PL >> "$LOG_FILE" 2>> "$ERR_FILE" || log "⚠️  Makefile.PL failed for $tarball_dir"
  make >> "$LOG_FILE" 2>> "$ERR_FILE" || log "⚠️  make failed for $tarball_dir"
  sudo make install >> "$LOG_FILE" 2>> "$ERR_FILE" || log "⚠️  make install failed for $tarball_dir"
  cd "$TARBALL_DIR"
done

log "🎉 Perl offline install completed. Check $LOG_FILE and $ERR_FILE for details."
exit 0
