# Set AWS regions
$SourceRegion = "eu-west-1"
$TargetRegion = "eu-west-3"

# Document names to copy
$Documents = @(
    "AccessKeysRotation",
    "CloudWatch_Agent_Installation",
    "DeployUnityRevisionJob",
    "DeployUnityRevisionWeb",
    "Install-Cynet-If-Missing",
    "SSM-SessionManagerRunShell"
)

# Create a temp directory
$TempDir = "$PSScriptRoot\ssm_tmp"
New-Item -ItemType Directory -Path $TempDir -Force | Out-Null

foreach ($Doc in $Documents) {
    Write-Host "`n--- Processing $Doc ---"

    $FullJsonPath = Join-Path $TempDir "$Doc.full.json"
    $YamlPath = Join-Path $TempDir "$Doc.yaml"

    try {
        # Step 1: Pull the full document from source
        & aws ssm get-document `
            --region $SourceRegion `
            --name $Doc `
            --document-version '$LATEST' `
            --output json `
            > $FullJsonPath
    } catch {
        Write-Warning "❌ Failed to get $Doc from $SourceRegion"
        continue
    }

    # Step 2: Extract just the YAML content
    try {
        $DocJson = Get-Content $FullJsonPath -Raw | ConvertFrom-Json
        if (-not $DocJson.Content -or $DocJson.Content.Trim().Length -eq 0) {
            Write-Warning "⚠️ $Doc has empty Content. Skipping."
            continue
        }

        # Normalize line endings and save as YAML
        $YamlClean = $DocJson.Content -replace "`r`n", "`n"
        Set-Content -Path $YamlPath -Value $YamlClean -Encoding UTF8
    } catch {
        Write-Warning "❌ Failed to extract YAML from $Doc"
        continue
    }

    # Step 3: Delete if exists in target
    & aws ssm delete-document --region $TargetRegion --name $Doc 2>$null

    # Step 4: Create the document in target
    try {
        & aws ssm create-document `
            --region $TargetRegion `
            --name $Doc `
            --content file://$YamlPath `
            --document-type $DocJson.DocumentType `
            --document-format YAML `
            --target-type "/"

        Write-Host "✅ $Doc successfully recreated in $TargetRegion"
    } catch {
        Write-Warning "❌ Failed to create $Doc in $TargetRegion"
    }
}

# Step 5: Clean up
Remove-Item -Path $TempDir -Recurse -Force
Write-Host "`n✔️ All done. Temporary files removed."
