# Connecting to BASF Servers via AWS SSM Session Manager
## A Complete, No-Assumptions Walkthrough (Empty Desktop → Connected)

**What this replaces:** Logging into the VDI (~20 minutes) and then SSH-ing into a server.
**What you'll do instead:** Run two short commands from your own laptop and land directly in a server's terminal.

**How to read this guide:** Anywhere you see something wrapped like `<this>`, it's a placeholder — replace the whole thing, including the `< >` symbols, with your real value. Every other line is meant to be copied exactly as written.

**Estimated one-time setup time:** 10–15 minutes. After that, connecting takes seconds.

---

## Before You Start — What You'll Need

Please make sure you have the relevant AWS Keys or AWScli Preconfigured - #Don't begin installing anything until you have this information#

| Environment | Access Key ID | Secret Access Key | Region |
|---|---|---|---|
| DEV | | | |
| QA | | | |
| Migration | | | |
| PROD | | | |

You do **not** need to create these yourself anywhere. You do **not** need AWS Console access. In case you don't have the Relevant AWS Keys you can go to your Company's System Administrator for Assistance.

---

## Part 1 — Install the Two Required Programs

### Step 1: Open PowerShell

Click the **Start** button (bottom-left of your screen) → type `powershell` → press **Enter**. A blue or black window with a text prompt will open. This is where every command in this guide gets typed.

---

### Step 2: Install the AWS CLI

1. Open your web browser and go to:
   `https://awscli.amazonaws.com/AWSCLIV2.msi`
   (This downloads a file called `AWSCLIV2.msi`.)
2. Open the downloaded file (double-click it, usually found in your **Downloads** folder).
3. Click **Next** through the installer using all the default options, then **Finish**.
4. **Close** the PowerShell window from Step 1 completely, and open a **new** one (Start → `powershell` → Enter). This step matters — the new program won't be recognized in the old window.
5. In the new window, type this exactly and press Enter:
   ```powershell
   aws --version
   ```
6. **You should see** something like:
   ```
   aws-cli/2.15.0 Python/3.11.6 Windows/10 exe/AMD64
   ```
   If instead you see `'aws' is not recognized...`, close the window and open a brand new one again — this is almost always a PATH refresh issue, not a broken install.

---

### Step 3: Install the Session Manager Plugin

1. In your browser, go to:
   `https://s3.amazonaws.com/session-manager-downloads/plugin/latest/windows/SessionManagerPluginSetup.exe`
2. Open the downloaded `SessionManagerPluginSetup.exe` file.
3. Click through the installer with default options.
4. Close and reopen PowerShell again (same reasoning as Step 2).
5. Type this exactly and press Enter:
   ```powershell
   session-manager-plugin
   ```
6. **You should see** a message like:
   ```
   The Session Manager plugin was installed successfully. Use the AWS CLI to start a session.
   ```
   That message means it's working correctly — it's not an error, even though it sounds like one at first glance.

---

## Part 2 — Set Up Your Login (One Time Per Environment)

An AWS "profile" is just a saved login for one specific AWS account, stored under a name you choose. Since BASF has 4 separate AWS accounts, you'll create one profile per environment you were given keys for in the table at the top.

### Step 4: Configure a Profile

For **each** environment you have keys for, type:

```powershell
aws configure --profile basf_dev
```

PowerShell will ask you four questions, one at a time. Paste your answer after each and press Enter:

```
AWS Access Key ID [None]: <paste the Access Key ID you were given for DEV>
AWS Secret Access Key [None]: <paste the Secret Access Key you were given for DEV>
Default region name [None]: <paste the region you were given for DEV>
Default output format [None]: json
```

Nothing will visibly print back after pasting the keys — that's normal, it just doesn't echo them to the screen.

**Repeat the exact same process** for every other environment you need, changing only the profile name and the values you paste in:

```powershell
aws configure --profile basf_qa
aws configure --profile basf_mig
aws configure --profile basf_prod
```

---

### Step 5: Double-Check Your Setup Worked

**Check 1 — did all your profiles get saved?**
```powershell
aws configure list-profiles
```
**You should see** the name of every profile you just configured, one per line, e.g.:
```
basf_dev
basf_qa
```
If a name is missing, redo Step 4 for that one.

**Check 2 — is each profile pointing at the correct AWS account?**

Run this once per profile you set up:
```powershell
aws sts get-caller-identity --profile basf_dev
```
**You should see** something like:
```json
{
    "UserId": "AIDAEXAMPLE",
    "Account": "891376961316",
    "Arn": "arn:aws:iam::891376961316:user/PhenomeOne_Sec_keys"
}
```
Check the `"Account"` number against this table:

| Profile | Account number it must show |
|---|---|
| basf_dev | 891376961316 |
| basf_qa | 589860219747 |
| basf_migration | 942237908740 |
| basf_prod | 439763252024 |

If the number doesn't match, you pasted a key into the wrong profile — redo Step 4 for that one with the correct key.

---

## Part 3 — Find and Connect to a Server

### Step 6: List the Servers in an Environment

You need a server's **Instance ID** before you can connect to it. This command shows every server in one environment, with its name, ID, and current status:

```powershell
aws ec2 describe-instances --profile basf_dev --region us-east-1 --query "Reservations[].Instances[].{Name:Tags[?Key=='Name']|[0].Value, InstanceId:InstanceId, State:State.Name, PrivateIP:PrivateIpAddress}" --output table
```

**You should see** a table like this:
```
------------------------------------------------------------------------
|                          DescribeInstances                            |
+------------------------+----------------------+---------+-------------+
|  InstanceId            |  Name                |  State  |  PrivateIP  |
+------------------------+----------------------+---------+-------------+
|  i-0abc1234def567890   |  basf-dev-web-01     |  running|  10.0.1.15  |
+------------------------+----------------------+---------+-------------+
```

Note the `InstanceId` of the server you want (e.g. `i-0abc1234def567890`) — you'll paste that into Step 7.

**To only see servers that are currently on:**
```powershell
aws ec2 describe-instances --profile basf-dev --region <region> --filters "Name=instance-state-name,Values=running" --query "Reservations[].Instances[].{Name:Tags[?Key=='Name']|[0].Value, InstanceId:InstanceId}" --output table
```


To browse a different environment, change `--profile basf_dev` to `basf_qa`, `basf_migration`, or `basf_prod`.

---

### Step 7: Connect to the Server

Take the Instance ID from Step 6 and plug it in here:

```powershell
aws ssm start-session --target <instance-id-from-step-6> --region us-east-1 --profile basf_dev
```

**Important:** the `--profile` here must be the *same one* you used to find the server in Step 6. Using a different environment's profile will fail, even if the instance ID is correct, because that server simply doesn't exist inside that other account.

**You should see:**
```
Starting session with SSM Agent v3.1.x.x (linux)
To exit a session, you can type 'exit' or press 'Ctrl+C'

sh-4.2$
```

**That `sh-4.2$` prompt means you are now inside the server**, exactly as if you had SSH'd in — except you never touched the VDI.

---

### Step 8: Exit When You're Done

```
sh-4.2$ exit
```
This closes the session and returns you to your normal PowerShell window on your own laptop.

---

## ✅ Setup Complete — Checklist

- [ ] AWS CLI installed (`aws --version` works)
- [ ] Session Manager Plugin installed (`session-manager-plugin` shows the success message)
- [ ] A profile configured for each environment I need (`aws configure list-profiles` lists them)
- [ ] Each profile verified against the correct account number (`aws sts get-caller-identity`)
- [ ] Successfully listed servers in at least one environment (Step 6)
- [ ] Successfully connected to a server and saw the `sh-4.2$` prompt (Step 7)

---

## Everyday Use, From Now On (Skip Parts 1 & 2 — Only Do This Once Ever)

```powershell
# 1. Find the server
aws ec2 describe-instances --profile <basf-dev|basf-qa|basf-migration|basf-prod> --region <region> --query "Reservations[].Instances[].{Name:Tags[?Key=='Name']|[0].Value, InstanceId:InstanceId, State:State.Name}" --output table

# 2. Connect to it
aws ssm start-session --target <instance-id> --region <region> --profile <same profile as above>
```

---

## Reference: Accounts & Profiles

| Environment | Account ID | IAM User | Profile Name |
|---|---|---|---|
| DEV | 891376961316 | `PhenomeOne_Sec_keys` | `basf_dev` |
| QA | 589860219747 | `phenomeOne_qual` | `basf_qa` |
| Migration | 942237908740 | `FuAWSmigration` | `basf_mig` |
| PROD | 439763252024 | `phenome_one` | `basf_prod` |

---

## Reference: Full Server Inventory

Use these tables instead of running Step 6 yourself — everything you need to connect is already here. If a server is later added, removed, or renamed, re-run Step 6 to refresh this list.

### DEV Environment (Account: 891376961316 — profile `basf-dev`)

| Instance ID | Name | Type | State | Private IP |
|---|---|---|---|---|
| `i-09501fb8a153b5c4d` | Phen_Basf_Dev_Web_Virginia | x8i.xlarge | running | 10.193.162.73 |
| `i-073c3cdf5ff77cb0c` | Phen_Basf_Dev_Job_VIRGINIA | x8i.large | running | 10.193.162.92 |
| `i-06fb6679e91bdbaf0` | Phen_Basf_Dev_Logstash_VIRGINIA | m7i.large | running | 10.193.162.72 |
| `i-0d7c75a8e25582957` | phenome-docker-env | m6i.xlarge | running | 10.193.161.219 |

**Region:** `us-east-1` (Virginia, based on server naming — to be confirmed if a connection fails)

### QA Environment (Account: 589860219747 — profile `basf-qa`)

| Instance ID | Name | Type | State | Private IP |
|---|---|---|---|---|
| `i-0a31308a77baf2d12` | basf_qual_web | m7i.2xlarge | running | 10.193.162.23 |
| `i-012f4e634c01672f2` | basf_qual_job | m7i.2xlarge | running | 10.193.162.25 |
| `i-0c0efcd4a4b690186` | basf_qual_logstash | m7i.xlarge | running | 10.193.162.10 |

**Region:** to be confirmed

### Migration Environment (Account: 942237908740 — profile `basf-migration`)

| Instance ID | Name | Type | State | Private IP |
|---|---|---|---|---|
| `i-0ef421b74b2fa3767` | basf_mig_web | c7i-flex.xlarge | running | 10.193.180.69 |
| `i-0618e844b93c29243` | basf_mig_job | r6i.xlarge | running | 10.193.180.70 |

**Region:** to be confirmed

### PROD Environment (Account: 439763252024 — profile `basf-prod`)

| Instance ID | Name | Type | State | Private IP |
|---|---|---|---|---|
| `i-05b6924480fdce479` | basf-prod-web | m7i.xlarge | running | 10.193.160.38 |
| `i-0d75c3fda96f39566` | basf-prod-logstash | m7i.xlarge | running | 10.193.160.62 |
| `i-0f972ee9bb6137b19` | basf-prod-job | m7i.xlarge | running | 10.193.161.232 |

**Region:** to be confirmed

---

## Quick Connect — Copy, Fill In the Region, Go

```powershell
# DEV — Web
aws ssm start-session --target i-09501fb8a153b5c4d --region us-east-1 --profile basf-dev

# DEV — Job
aws ssm start-session --target i-073c3cdf5ff77cb0c --region us-east-1 --profile basf-dev

# DEV — Logstash
aws ssm start-session --target i-06fb6679e91bdbaf0 --region us-east-1 --profile basf-dev

# DEV — Docker env
aws ssm start-session --target i-0d7c75a8e25582957 --region us-east-1 --profile basf-dev

# QA — Web
aws ssm start-session --target i-0a31308a77baf2d12 --region <qa-region> --profile basf-qa

# QA — Job
aws ssm start-session --target i-012f4e634c01672f2 --region <qa-region> --profile basf-qa

# QA — Logstash
aws ssm start-session --target i-0c0efcd4a4b690186 --region <qa-region> --profile basf-qa

# Migration — Web
aws ssm start-session --target i-0ef421b74b2fa3767 --region <migration-region> --profile basf-migration

# Migration — Job
aws ssm start-session --target i-0618e844b93c29243 --region <migration-region> --profile basf-migration

# PROD — Web
aws ssm start-session --target i-05b6924480fdce479 --region <prod-region> --profile basf-prod

# PROD — Logstash
aws ssm start-session --target i-0d75c3fda96f39566 --region <prod-region> --profile basf-prod

# PROD — Job
aws ssm start-session --target i-0f972ee9bb6137b19 --region <prod-region> --profile basf-prod
```

---

## Reference: Handy Commands Once You're Inside a Server

```bash
# Docker
docker ps
docker logs <container-name>

# Logs
tail -f /var/log/application.log
grep ERROR /var/log/application.log | tail -20

# Connectivity / firewall checks
curl -v https://get.docker.com
openssl s_client -connect <host>:443 -showcerts | head -60

# System info
df -h
free -m
ps aux | grep <process-name>

# Network
ip addr show
ip route show
netstat -tlnp

# Services
sudo systemctl status <service>
sudo systemctl restart <service>
```
