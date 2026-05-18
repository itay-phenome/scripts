# 📁 powershell/aws/ssm

Scripts for copying AWS SSM Documents between regions.

---

## Copy-SSMDocuments-YAML.ps1
Copies SSM Documents from one AWS region to another.
Extracts the YAML content, deletes the document in the target region if it exists, and recreates it.

**Configure at the top of the script:**
```powershell
$SourceRegion = "eu-west-1"
$TargetRegion = "eu-west-3"

$Documents = @(
    "AccessKeysRotation",
    "DeployUnityRevisionJob",
    "DeployUnityRevisionWeb",
    "Install-Cynet-If-Missing"
)
```

**Run:**
```powershell
.\Copy-SSMDocuments-YAML.ps1
```
> Requires AWS CLI with permissions: `ssm:GetDocument`, `ssm:CreateDocument`, `ssm:DeleteDocument`
