@echo off
set SRC_REGION=eu-west-1
set DST_REGION=eu-west-3

REM Replace with your actual document names
set DOCS=AccessKeysRotation CloudWatch_Agent_Installation DeployUnityRevisionJob DeployUnityRevisionWeb Install-Cynet-If-Missing SSM-SessionManagerRunShell

for %%D in (%DOCS%) do (
    echo Processing %%D...

    aws ssm get-document --region %SRC_REGION% --name %%D --document-version $LATEST --query "{Content:Content,DocumentType:DocumentType,DocumentFormat:DocumentFormat}" --output json > doc.json

    if exist doc.json (
        aws ssm delete-document --region %DST_REGION% --name %%D >nul 2>&1

        for /f "delims=" %%C in ('type doc.json') do set CONTENT=%%C

        REM This will fail for large content or multiline documents. For safety, prefer PowerShell or WSL for bulk.
        aws ssm create-document --region %DST_REGION% --name %%D --content "%CONTENT%" --document-type "Command" --document-format "JSON" --target-type "/"
    )

    del doc.json
)