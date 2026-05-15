# ansible/

This folder contains **Ansible playbooks and roles**.

## Structure suggestion
```
ansible/
  inventory/
    playbooks/
      roles/
      ```

      ## Naming convention
      `<action>_<target>.yml` — e.g. `install_docker.yml`, `configure_nginx.yml`

      ## Examples of what goes here
      - Server provisioning playbooks
      - Configuration management tasks
      - Application deployment playbooks
      - Inventory files (hosts)
