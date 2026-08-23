# Building BASF SSM Connect for macOS

This folder has everything needed to build a native Mac version of the app.
It only needs to be done once (or again if the app is updated).

## Prerequisites on the Mac

1. Python 3, from https://www.python.org/downloads/macos/
   (the built-in system `python3` on some macOS versions is missing tkinter -
   the python.org installer includes it).
2. That's it - the build script installs everything else (PyInstaller) into
   a throwaway virtual environment, it won't touch anything else on the Mac.

## Steps

1. Copy this whole folder (`BASF_SSM_Connect_Mac_BuildKit`) to the Mac -
   e.g. via AirDrop, a USB drive, or a shared drive.
2. Open **Terminal** and `cd` into the folder, e.g.:
   ```
   cd ~/Downloads/BASF_SSM_Connect_Mac_BuildKit
   ```
3. Run the build script:
   ```
   ./build_mac.sh
   ```
   If that's blocked, run `chmod +x build_mac.sh` first, then try again.
4. When it finishes, the app is at:
   ```
   dist/BASF_SSM_Connect.app
   ```

## Sending the app back / running it

- Copy `dist/BASF_SSM_Connect.app` out of the build folder (e.g. to
  Applications, or Desktop) - it's fully self-contained.
- Since it isn't code-signed (no Apple Developer certificate), the first
  launch will be blocked by Gatekeeper ("cannot be opened because it is
  from an unidentified developer"). To allow it:
  - **Right-click (or Control-click) the app -> Open -> Open**, or
  - In Terminal: `xattr -cr /path/to/BASF_SSM_Connect.app`
- After that first approval, it opens normally every time.

## Also required on the Mac to actually use the app

Same prerequisites as the Windows version (see the main README.txt in
`BASF_SSM_Connect_Package`):
- AWS CLI v2 - https://awscli.amazonaws.com/AWSCLIV2.pkg
- Session Manager Plugin (Mac build) -
  https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html
- At least one AWS CLI profile with valid keys, added via the app's
  "AWS Profiles" tab or `aws configure --profile basf_dev` in Terminal.

On macOS, clicking "Connect" opens a new **Terminal.app** window running the
`aws ssm start-session` command (on Windows it opens a PowerShell window -
same idea, different terminal).
