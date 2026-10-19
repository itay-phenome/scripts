module "mysql_bucket" {
  source  = "app.terraform.io/syngenta-tfc/s3/aws"
  version = "1.0.7"

  bucket = local.mysql_bucket_name

  acl = "private"

  sse_algorithm      = local.kms_key_arn_final != null ? "aws:kms" : "AES256"
  kms_key_id         = local.kms_key_arn_final
  bucket_key_enabled = local.kms_key_arn_final != null

  versioning = {
    status     = "Enabled"
    mfa_delete = "Disabled"
  }

  lifecycle_rule = var.mysql_bucket_lifecycle_rule

  tags = merge(local.tags_final, { Name = local.mysql_bucket_name })
}

module "secret" {
  source  = "app.terraform.io/syngenta-tfc/secretsmanager/aws"
  version = "1.0.3"

  secret_name        = var.secret_name
  secret_description = var.secret_description
  secret_string      = local.secret_payload

  kms_key_id = local.secret_kms_key_id_final
  policy     = data.aws_iam_policy_document.secret_policy.json

  tags = merge(local.tags_final, { Name = var.secret_name })
}

module "ecr" {
  for_each = local.ecr_repos

  source  = "app.terraform.io/syngenta-tfc/ecr/aws"
  version = "1.0.2"

  repository_name = "${local.app_code_final}-${each.key}"

  repository_encryption_type = "KMS"
  repository_kms_key         = local.kms_key_arn_final

  repository_image_tag_mutability = "MUTABLE"
  repository_image_scan_on_push   = true

  repository_read_access_arns       = var.ecr_read_access_arns
  repository_read_write_access_arns = var.ecr_read_write_access_arns

  create_lifecycle_policy     = true
  repository_lifecycle_policy = local.ecr_lifecycle_policy

  tags = merge(local.tags_final, { Name = "${local.app_code_final}-${each.key}" })
}
