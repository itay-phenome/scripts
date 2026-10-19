locals {
  defaults = {
    uploads   = "${var.name}-${var.env}-uploads"
    images    = "${var.name}-${var.env}-images"
    analyses  = "${var.name}-${var.env}-analyses"
    reports   = "${var.name}-${var.env}-reports"
    documents = "${var.name}-${var.env}-documents"
    tiledb    = "${var.name}-${var.env}-tiledb"
  }

  overrides = {
    for k, v in var.buckets : k => v
    if try(trimspace(v), "") != ""
  }

  resolved = merge(local.defaults, local.overrides)

  kms_key_arn_final = trimspace(var.kms_key_arn) != "" ? var.kms_key_arn : null
  kms_key_id_final  = local.kms_key_arn_final != null ? element(reverse(split("/", local.kms_key_arn_final)), 0) : null
}
