output "mysql_bucket_name" {
  value = local.mysql_bucket_name
}

output "secret_name" {
  value = var.secret_name
}

output "secret_arn_like" {
  value = "arn:aws:secretsmanager:${var.region}:${local.account_id}:secret:${var.secret_name}*"
}

output "ecr_repository_names" {
  value = { for r in var.ecr_repositories : r => "${local.prefix}-${r}" }
}

output "ecr_repository_urls" {
  value = { for r in var.ecr_repositories : r => "${local.account_id}.dkr.ecr.${var.region}.amazonaws.com/${local.prefix}-${r}" }
}

output "ecr_repository_arns" {
  value = { for r in var.ecr_repositories : r => "arn:aws:ecr:${var.region}:${local.account_id}:repository/${local.prefix}-${r}" }
}
