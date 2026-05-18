#!/bin/bash

set -e
LOGFILE="/tmp/perl_so_audit_$(hostname)_$(date +%Y%m%d_%H%M%S).log"

echo "📍 Hostname: $(hostname)" | tee -a "$LOGFILE"
echo "📅 Date: $(date)" | tee -a "$LOGFILE"
echo "🧠 Perl binary: $(which perl)" | tee -a "$LOGFILE"
echo "🧠 Perl version: $(perl -v | grep 'This is perl')" | tee -a "$LOGFILE"

# Get sitelib and sitearch
SITELIB=$(perl -MConfig -e 'print $Config{sitelib}')
SITEARCH=$(perl -MConfig -e 'print $Config{sitearch}')

echo -e "\n📁 Perl sitelib: $SITELIB" | tee -a "$LOGFILE"
echo "📁 Perl sitearch: $SITEARCH" | tee -a "$LOGFILE"

echo -e "\n🔍 Scanning for .so files and their linkage details..." | tee -a "$LOGFILE"
find "$SITEARCH" -name '*.so' | while read sofile; do
    echo -e "\n🔗 $sofile" | tee -a "$LOGFILE"
    readelf -d "$sofile" 2>/dev/null | grep -E 'libperl|RUNPATH' | tee -a "$LOGFILE"
done

echo -e "\n🛠️ Recommended next steps if any .so linked to wrong libperl:" | tee -a "$LOGFILE"
echo "1. Rebuild the module with:" | tee -a "$LOGFILE"
echo "     perl Makefile.PL" | tee -a "$LOGFILE"
echo "     sed -i 's@-lperl@/opt/perl/perl-5.38.4/lib/5.38.4/x86_64-linux-thread-multi/CORE/libperl.so@' Makefile" | tee -a "$LOGFILE"
echo "     make && make install" | tee -a "$LOGFILE"

echo -e "\n✅ Done. Full report logged to $LOGFILE" | tee -a "$LOGFILE"
