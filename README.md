# scripts

Personal scripts repository organized by language and purpose.

## Folder Structure

| Folder | Contents |
|--------|----------|
| `bash/` | Bash / Shell scripts (.sh) |
| `python/` | Python scripts (.py) |
| `powershell/` | PowerShell scripts (.ps1) |
| `docker/` | Dockerfiles & Docker Compose configs |
| `ansible/` | Ansible playbooks & roles |
| `terraform/` | Terraform IaC configurations |
| `utils/` | General-purpose utility scripts |

## Naming Conventions

- **Bash:** `<purpose>_<description>.sh` — e.g. `backup_home_dir.sh`
- - **Python:** `<purpose>_<description>.py` — e.g. `parse_logs.py`
  - - **PowerShell:** `<Verb>-<Description>.ps1` — e.g. `Get-DiskReport.ps1`
    - - **Docker:** Group by project name in subfolders
      - - **Ansible:** `<action>_<target>.yml` — e.g. `install_docker.yml`
        - - **Terraform:** Group by cloud provider, then project
         
          - ## How to Contribute / Add a Script
         
          - 1. Place the script in the correct folder based on its language or purpose
            2. 2. Follow the naming convention for that folder
               3. 3. Add a short comment header at the top of every script explaining what it does
                  4. 4. Commit with a clear message: `add: backup script for /home directory`
                    
                     5. ## Commit Message Convention
                    
                     6. Use short prefixes to keep history clean:
                     7. - `add:` — new script added
                        - - `fix:` — bug fix in existing script
                          - - `update:` — improvement or change
                            - - `remove:` — deleted an old script
                              - - `docs:` — README or documentation change
