# setup.ps1
Start-Process -FilePath "msiexec.exe" -ArgumentList "/i GoogleChromeStandaloneEnterprise64.msi /qn /norestart" -Wait