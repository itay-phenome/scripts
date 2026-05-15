# terraform/

This folder contains **Terraform IaC (Infrastructure as Code) configurations**.

## Structure suggestion
```
terraform/
  <cloud-provider>/
      <project>/
            main.tf
                  variables.tf
                        outputs.tf
                              terraform.tfvars.example
                              ```

                              ## Naming convention
                              Group by cloud provider (aws, azure, gcp) and then by project/module.

                              ## Examples of what goes here
                              - Cloud resource provisioning (VMs, networks, storage)
                              - Kubernetes cluster definitions
                              - DNS & load balancer configurations
                              - Module definitions (reusable Terraform modules)
