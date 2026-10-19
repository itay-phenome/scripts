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
