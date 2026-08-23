BASF SSM Connect - Quick Start
==============================

This tool replaces logging into the VDI + SSH-ing in. Pick an environment,
pick a server, hit Connect, and you land in that server's terminal.

PREREQUISITES (must be installed once on this laptop before first use):
-------------------------------------------------------------------------
1. AWS CLI v2
   https://awscli.amazonaws.com/AWSCLIV2.msi

2. AWS Session Manager Plugin
   https://s3.amazonaws.com/session-manager-downloads/plugin/latest/windows/SessionManagerPluginSetup.exe

3. At least one AWS CLI profile with valid keys for the environment you need
   (DEV / QA / Migration / PROD). You can add these from inside the app's
   "AWS Profiles" tab, or run `aws configure --profile basf_dev` etc.
   yourself in PowerShell.

Full step-by-step instructions (if this is a brand new laptop) are in the
enclosed SSM-Session-Manager-Setup-Guide-BASF.md.

The app itself (BASF_SSM_Connect.exe) does NOT need Python installed -
everything is bundled into the .exe.

RUNNING THE APP
-------------------------------------------------------------------------
Double-click BASF_SSM_Connect.exe.

Windows SmartScreen may show "Windows protected your PC" the first time,
since the exe isn't code-signed. Click "More info" -> "Run anyway".

USING IT
-------------------------------------------------------------------------
1. "AWS Profiles" tab
   Add / edit / remove / verify your AWS CLI profiles and keys.

2. Environment tabs (DEV / QA / Migration / PROD, or any you add)
   Set Profile + Region, click "Refresh from AWS" to pull the live server
   list for that account, select a server, click Connect (or double-click
   the row). A new PowerShell window opens with the session.
   Use "Connect by Instance ID" to reach a server that isn't in the list.

3. "+ Add Environment" (top of the window)
   Wires up an additional AWS account/environment beyond the 4 built-in
   BASF ones - useful for other projects or clients.

4. Your settings (custom environments, cached server lists) are saved
   locally to:
       %USERPROFILE%\.basf_ssm_connect\config.json
   Nothing is shared between laptops - each install manages its own
   settings and its own AWS CLI profiles (~/.aws/credentials, ~/.aws/config).
