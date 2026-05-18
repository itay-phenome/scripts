# 📁 bash/perl

Scripts for managing the Perl environment on Unity servers.

---

## perl_offline_install.sh
Downloads all installed Perl modules from CPAN and prepares them for offline installation.

**Step 1 — on a machine with internet:**
```bash
bash perl_offline_install.sh
```
> Downloads tarballs to `/tmp/perl_tarballs/`

**Step 2 — copy the tarballs to the offline machine, then run again to install.**

---

## reset_and_rebuild_perl_detect.sh
Completely removes Perl from the system and rebuilds from scratch.
Installs all required CPAN modules and restores custom PDF modules from S3.

> ⚠️ Destructive — removes all existing Perl packages first.

**Run (as root):**
```bash
sudo bash reset_and_rebuild_perl_detect.sh
```

---

## audit_and_fix_perl_so_linkage.sh
Scans Perl `.so` (XS) module files and checks which version of `libperl` they link against.
Used to diagnose MUTEX crashes caused by mixed Perl library versions.

**Run:**
```bash
bash audit_and_fix_perl_so_linkage.sh
```
> Log: `/tmp/perl_so_audit_HOSTNAME_DATE.log`

---

## perl_mutex_diagnostics.sh
Collects full Perl diagnostic info: installed modules, `.so` linkage, END blocks in codebase, thread usage, and XS crash test with Image::Magick.

**Run:**
```bash
bash perl_mutex_diagnostics.sh
```
> Log: `/tmp/perl_mutex_diag.log`

---

## docs/Image-Magick-install-guide.md
Step-by-step guide for installing `Image::Magick` from system packages (not CPAN) to avoid MUTEX_LOCK crashes.
