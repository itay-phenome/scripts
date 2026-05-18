# 📁 utils/aws/ssm

SSM Documents and utility scripts for AWS Systems Manager.

---

## copy_ssm.cmd
Windows CMD script that copies SSM Documents between regions.
> ⚠️ Limited — fails on multi-line documents. Prefer `Copy-SSMDocuments-YAML.ps1` instead.

---

## documents/

SSM Document definitions used by AWS Systems Manager.

| File | Description |
|------|-------------|
| `DeployUnityRevisionJob.txt` | Deploys a Unity revision to Job Server |
| `DeployUnityRevisionWeb.txt` | Deploys a Unity revision to Web Server |
| `DeployUnityRevisionJob-External.txt` | Same — for external/customer accounts |
| `DeployUnityRevisionWeb-External.txt` | Same — for external/customer accounts |
| `AccessKeysRotation.txt` | Rotates IAM access keys |
| `AWS-Rotate-Keys.txt` | Alternative key rotation document |
| `Install-Cynet-If-Missing.txt` | Installs Cynet EDR agent if not present |
| `cynet-installation.txt` | Manual Cynet installation steps |
| `cynet-ssm-document.yaml` | SSM Document (YAML) for Cynet installation |
| `install-and-monitor-cynet.yaml` | SSM Document — install + monitor Cynet |

**To register a document in AWS SSM:**
```bash
aws ssm create-document \
  --name "DocumentName" \
  --content file://documents/DocumentName.yaml \
  --document-type Command \
  --document-format YAML \
  --region your-region
```
