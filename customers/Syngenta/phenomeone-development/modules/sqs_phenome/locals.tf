locals {
  queue_name = "${var.name}-${var.env}-sqs"

  sqs_managed_sse_enabled_final = coalesce(var.sqs_managed_sse_enabled, false)
  kms_sqs_key_arn_final         = trimspace(coalesce(var.kms_sqs_key_arn, ""))

  use_sqs_managed_sse = local.sqs_managed_sse_enabled_final || local.kms_sqs_key_arn_final == ""
}
