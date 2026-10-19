module "sqs" {
  source  = "app.terraform.io/syngenta-tfc/sqs/aws"
  version = "1.0.3"

  name        = local.queue_name
  name_prefix = null

  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = var.message_retention_seconds
  max_message_size           = var.max_message_size
  delay_seconds              = var.delay_seconds
  receive_wait_time_seconds  = var.receive_wait_time_seconds

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowMINTSNSToSendMessages"
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = "*"
      Condition = {
        ArnLike = {
          "aws:SourceArn" = "arn:aws:sns:us-east-1:809800841141:mint*"
        }
      }
    }]
  })
  redrive_policy       = null
  redrive_allow_policy = null

  fifo_queue                  = false
  content_based_deduplication = false
  deduplication_scope         = null
  fifo_throughput_limit       = null

  sqs_managed_sse_enabled           = local.use_sqs_managed_sse
  kms_master_key_id                 = local.use_sqs_managed_sse ? null : local.kms_sqs_key_arn_final
  kms_data_key_reuse_period_seconds = var.kms_data_key_reuse_period_seconds

  tags = var.tags
}



module "sqs_fifo_integration" {
  source  = "app.terraform.io/syngenta-tfc/sqs/aws"
  version = "1.0.3"

  name        = "mint-integration"
  name_prefix = null

  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = var.message_retention_seconds
  max_message_size           = var.max_message_size
  delay_seconds              = var.delay_seconds
  receive_wait_time_seconds  = var.receive_wait_time_seconds

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowMINTSNSToSendMessages"
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = "*"
      Condition = {
        ArnLike = {
          "aws:SourceArn" = "arn:aws:sns:us-east-1:809800841141:mint*"
        }
      }
    }]
  })
  redrive_policy       = null
  redrive_allow_policy = null

  fifo_queue                  = true
  content_based_deduplication = true
  deduplication_scope         = "messageGroup"
  fifo_throughput_limit       = "perMessageGroupId"

  sqs_managed_sse_enabled           = local.use_sqs_managed_sse
  kms_master_key_id                 = local.use_sqs_managed_sse ? null : local.kms_sqs_key_arn_final
  kms_data_key_reuse_period_seconds = var.kms_data_key_reuse_period_seconds

  tags = var.tags
}

module "sns_fifo_integration" {
  source  = "app.terraform.io/syngenta-tfc/sns/aws"
  version = "1.0.5"

  name        = "mint-integration"
  name_prefix = null

  fifo_topic                  = true
  content_based_deduplication = true

  kms_master_key_id = local.use_sqs_managed_sse ? null : local.kms_sqs_key_arn_final

  create_subscription = false

  create_aws_sns_topic_policy            = true
  allowed_iam_arns_for_sns_publish       = []
  allowed_aws_services_for_sns_published = []
  sns_topic_policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowPhenomeoneAccessToTopic"
        Effect = "Allow"
        Principal = {
          AWS = "*"
        }
        Action = [
          "sns:Subscribe",
          "sns:ListSubscriptionsByTopic",
          "sns:GetTopicAttributes"
        ]
        Resource = "*"
        Condition = {
          StringLike = {
            "aws:PrincipalArn" = "arn:aws:iam::809800841141:role/mint*"
          }
        }
      }
    ]
  })

  tags = var.tags
}

# MINT Material Management integration

module "sqs_fifo_material" {
  source  = "app.terraform.io/syngenta-tfc/sqs/aws"
  version = "1.0.3"

  name        = "mint-material"
  name_prefix = null

  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = var.message_retention_seconds
  max_message_size           = var.max_message_size
  delay_seconds              = var.delay_seconds
  receive_wait_time_seconds  = var.receive_wait_time_seconds

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowMINTSNSToSendMessages"
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = "*"
      Condition = {
        ArnLike = {
          "aws:SourceArn" = "arn:aws:sns:us-east-1:809800841141:mint*"
        }
      }
    }]
  })
  redrive_policy       = null
  redrive_allow_policy = null

  fifo_queue                  = true
  content_based_deduplication = true
  deduplication_scope         = "messageGroup"
  fifo_throughput_limit       = "perMessageGroupId"

  sqs_managed_sse_enabled           = local.use_sqs_managed_sse
  kms_master_key_id                 = local.use_sqs_managed_sse ? null : local.kms_sqs_key_arn_final
  kms_data_key_reuse_period_seconds = var.kms_data_key_reuse_period_seconds

  tags = var.tags
}

module "sns_fifo_material" {
  source  = "app.terraform.io/syngenta-tfc/sns/aws"
  version = "1.0.5"

  name        = "mint-material"
  name_prefix = null

  fifo_topic                  = true
  content_based_deduplication = true

  kms_master_key_id = local.use_sqs_managed_sse ? null : local.kms_sqs_key_arn_final

  create_subscription = false

  create_aws_sns_topic_policy            = true
  allowed_iam_arns_for_sns_publish       = []
  allowed_aws_services_for_sns_published = []
  sns_topic_policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowMINTAccessToTopic"
        Effect = "Allow"
        Principal = {
          AWS = "*"
        }
        Action = [
          "sns:Subscribe",
          "sns:ListSubscriptionsByTopic",
          "sns:GetTopicAttributes"
        ]
        Resource = "*"
        Condition = {
          StringLike = {
            "aws:PrincipalArn" = "arn:aws:iam::809800841141:role/mint*"
          }
        }
      }
    ]
  })

  tags = var.tags
}
