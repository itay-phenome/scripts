data "aws_secretsmanager_secret_version" "master" {
  secret_id = var.master_credentials_secret_name
}
locals {
  master_creds = try(jsondecode(data.aws_secretsmanager_secret_version.master.secret_string), {})

  master_username = try(
    local.master_creds["username"],
    local.master_creds["master_username"],
    local.master_creds["user"],
    null
  )

  master_password = try(
    local.master_creds["password"],
    local.master_creds["master_password"],
    null
  )

  kms_key_id_final = trimspace(var.kms_key_arn) != "" ? var.kms_key_arn : null

  parameter_group_name_final = trimspace(var.rds_parameter_group_name) != "" ? var.rds_parameter_group_name : null

  tags_final = merge(
    var.tags,
    {
      IACFramework    = lookup(var.tags, "IACFramework", "Terraform")
      ProjectIONumber = lookup(var.tags, "ProjectIONumber", "REPLACE_ME")
    }
  )
}
