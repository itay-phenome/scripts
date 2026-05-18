#!/bin/bash
set -e

LOG_FILE="/tmp/perl_mutex_diag.log"
echo "📍 Hostname: $(hostname)" > "$LOG_FILE"
echo "📅 Date: $(date)" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

echo "======================" >> "$LOG_FILE"
echo "🔍 Perl Version Info" >> "$LOG_FILE"
echo "======================" >> "$LOG_FILE"
perl -V >> "$LOG_FILE" 2>&1

echo "" >> "$LOG_FILE"
echo "===============================" >> "$LOG_FILE"
echo "🔍 Perl Module .so Linkage Audit" >> "$LOG_FILE"
echo "===============================" >> "$LOG_FILE"
find $(perl -MConfig -e 'print $Config{sitearch}') -name "*.so" | while read so; do
  echo "--- $so" >> "$LOG_FILE"
  readelf -d "$so" | grep -E 'libperl|RUNPATH' >> "$LOG_FILE" || echo "No libperl linkage found" >> "$LOG_FILE"
done

echo "" >> "$LOG_FILE"
echo "======================" >> "$LOG_FILE"
echo "📦 Installed Perl Modules" >> "$LOG_FILE"
echo "======================" >> "$LOG_FILE"
perl -MExtUtils::Installed -e 'print join("\n", ExtUtils::Installed->new->modules), "\n"' >> "$LOG_FILE" 2>&1

echo "" >> "$LOG_FILE"
echo "======================" >> "$LOG_FILE"
echo "📜 Search for END blocks" >> "$LOG_FILE"
echo "======================" >> "$LOG_FILE"
grep END -R ~/svn/trunk/JobServer/lib/ >> "$LOG_FILE" 2>/dev/null || echo "No END blocks found" >> "$LOG_FILE"

echo "" >> "$LOG_FILE"
echo "======================" >> "$LOG_FILE"
echo "🔎 Thread usage in codebase" >> "$LOG_FILE"
echo "======================" >> "$LOG_FILE"
grep -r 'threads' ~/svn/trunk/JobServer/ >> "$LOG_FILE" 2>/dev/null || echo "No thread usage found" >> "$LOG_FILE"

echo "" >> "$LOG_FILE"
echo "======================" >> "$LOG_FILE"
echo "🧪 Minimal XS Crash Reproducer Test" >> "$LOG_FILE"
echo "======================" >> "$LOG_FILE"
perl -MImage::Magick -e 'Image::Magick->new->Read("nonexistent.jpg")' >> "$LOG_FILE" 2>&1 || echo "Error during XS test" >> "$LOG_FILE"

echo "" >> "$LOG_FILE"
echo "✅ All diagnostics collected into: $LOG_FILE"
