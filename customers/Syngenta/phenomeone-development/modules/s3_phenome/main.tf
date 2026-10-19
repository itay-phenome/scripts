module "bucket" {
  for_each = local.resolved

  source  = "app.terraform.io/syngenta-tfc/s3/aws"
  version = "1.0.7"

  bucket = each.value

  acl = "private"

  sse_algorithm      = local.kms_key_id_final != null ? "aws:kms" : "AES256"
  kms_key_id         = local.kms_key_id_final
  bucket_key_enabled = local.kms_key_id_final != null

  versioning = {
    status     = lookup(var.bucket_versioning, each.key, false) ? "Enabled" : "Suspended"
    mfa_delete = "Disabled"
  }

  lifecycle_rule = []

  tags = var.tags
}
