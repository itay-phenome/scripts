locals {
  account_id = data.aws_caller_identity.current.account_id

  app_code_final = "phn"
  name_env       = lower("${var.name}-${var.env}")
  prefix         = "${local.app_code_final}-${local.name_env}"

  raw_mysql_bucket_name = lower("${local.prefix}-mysql-${local.account_id}")
  mysql_bucket_name     = trim(substr(local.raw_mysql_bucket_name, 0, 63), "-")

  kms_key_arn_final       = trimspace(var.kms_key_arn) != "" ? var.kms_key_arn : null
  secret_kms_key_id_final = trimspace(var.secret_kms_key_id) != "" ? var.secret_kms_key_id : local.kms_key_arn_final

  secret_payload = jsonencode({
    db_password            = var.db_password
    fleet_enrollment_token = var.fleet_enrollment_token
  })

  secret_principals = length(var.secret_reader_arns) > 0 ? var.secret_reader_arns : ["arn:aws:iam::${local.account_id}:root"]

  ecr_repos = toset(var.ecr_repositories)

  ecr_lifecycle_policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last N images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = var.ecr_keep_last_images
        }
        action = {
          type = "expire"
        }
      }
    ]
  })

  tags_final = merge(
    var.tags,
    {
      IACFramework    = lookup(var.tags, "IACFramework", "Terraform")
      ProjectIONumber = lookup(var.tags, "ProjectIONumber", "")
    }
  )
}
