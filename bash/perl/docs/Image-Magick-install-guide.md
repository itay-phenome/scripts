Steps to Install Image::Magick without Reintroducing MUTEX_LOCK
1. Remove Any CPAN Traces of Image::Magick
bash
Copy
Edit
rm -rf /usr/local/lib/x86_64-linux-gnu/perl/5.30.0/auto/Image/Magick
rm -rf /usr/local/lib/x86_64-linux-gnu/perl/5.30.0/Image/Magick.pm
find /usr/local/lib -name 'Magick.so'
Ensure Magick.so is not in /usr/local.

2. Reinstall from System Packages Only
bash
Copy
Edit
sudo apt-get update
sudo apt-get install --reinstall libimage-magick-perl
This guarantees Image::Magick binds correctly to your system Perl and links against Debian's libMagickCore safely.

3. Verify Correct Binary Source
bash
Copy
Edit
perl -MConfig -e 'print "$Config{vendorarch}/auto/Image/Magick/Magick.so\n"' | xargs file
✅ You should see:

vbnet
Copy
Edit
/usr/lib/.../Magick.so: ELF 64-bit LSB shared object...
4. Run Environment Audit
Run your perl_xs_comprehensive_audit.sh again. Confirm:

No /usr/local/lib/.../Magick.so

Image::Magick is resolved only from /usr/lib

All loaded XS modules align with system paths

5. Final Test
bash
Copy
Edit
perl -MImage::Magick -le 'my $i = Image::Magick->new; print "OK"' 
Then restart your app.