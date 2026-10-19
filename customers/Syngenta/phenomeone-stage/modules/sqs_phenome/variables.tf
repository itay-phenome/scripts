variable "name" {
  type = string
}

variable "env" {
  type = string
}

variable "tags" {
  type = map(string)
}

variable "kms_sqs_key_arn" {
  type    = string
  default = ""
}

variable "sqs_managed_sse_enabled" {
  type    = bool
  default = false
}

variable "visibility_timeout_seconds" {
  type    = number
  default = 300
}

variable "message_retention_seconds" {
  type    = number
  default = 1209600
}

variable "receive_wait_time_seconds" {
  type    = number
  default = 10
}

variable "kms_data_key_reuse_period_seconds" {
  type    = number
  default = 300
}

variable "max_message_size" {
  type    = number
  default = 262144
}

variable "delay_seconds" {
  type    = number
  default = 0
}

variable "mint_account_id" {
  type        = string
  default     = "809800841141"
  description = "AWS account ID for MINT SNS/SQS cross-account policies (test default)."
}

variable "mint_outbound_sqs_material" {
  type        = string
  default     = ""
  description = "Full ARN of MINT SQS for material outbound subscription from our SNS."
}

variable "mint_outbound_sqs_integration" {
  type        = string
  default     = ""
  description = "Full ARN of MINT SQS for integration outbound subscription from our SNS."
}

variable "mint_developer_role_arn" {
  type        = string
  default     = ""
  description = "Exact IAM role ARN MINT uses to subscribe to our SNS topics. When set, topic policy grants this role directly instead of the mint* wildcard principal."
}
