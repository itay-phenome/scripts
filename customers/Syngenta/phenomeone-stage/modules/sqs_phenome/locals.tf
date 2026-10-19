locals {
  queue_name = "${var.name}-${var.env}-sqs"

  sqs_managed_sse_enabled_final = coalesce(var.sqs_managed_sse_enabled, false)
  kms_sqs_key_arn_final         = trimspace(coalesce(var.kms_sqs_key_arn, ""))

  use_sqs_managed_sse = local.sqs_managed_sse_enabled_final || local.kms_sqs_key_arn_final == ""

  mint_account_id_final    = trimspace(var.mint_account_id) != "" ? trimspace(var.mint_account_id) : "809800841141"
  mint_region              = "us-east-1"
  mint_sns_source_wildcard = "arn:aws:sns:${local.mint_region}:${local.mint_account_id_final}:mint*"
  mint_sns_principal       = "arn:aws:iam::${local.mint_account_id_final}:role/mint*"

  mint_outbound_sqs_material    = trimspace(var.mint_outbound_sqs_material)
  mint_outbound_sqs_integration = trimspace(var.mint_outbound_sqs_integration)

  mint_developer_role_arn_final = trimspace(var.mint_developer_role_arn)

  mint_subscription_defaults = {
    protocol                        = "sqs"
    endpoint_auto_confirms          = true
    raw_message_delivery            = true
    filter_policy                   = null
    delivery_policy                 = null
    confirmation_timeout_in_minutes = null
    redrive_policy                  = null
    subscription_role_arn           = null
  }

  mint_sqs_fifo_mint_sns_source_condition = {
    ArnLike = {
      "aws:SourceArn" = local.mint_sns_source_wildcard
    }
  }

  mint_sqs_fifo_material_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowMINTSNSToSendMessages"
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = "*"
      Condition = local.mint_sqs_fifo_mint_sns_source_condition
    }]
  })

  mint_sqs_fifo_integration_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowMINTSNSToSendMessages"
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = "*"
      Condition = local.mint_sqs_fifo_mint_sns_source_condition
    }]
  })

  mint_sns_topic_policy_integration_json = jsonencode({
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
            "aws:PrincipalArn" = local.mint_sns_principal
          }
        }
      }
    ]
  })

  mint_sns_topic_policy_material_json = jsonencode({
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
            "aws:PrincipalArn" = local.mint_sns_principal
          }
        }
      }
    ]
  })
}
