variable "region" {
  type = string
}

variable "name" {
  type = string
}

variable "env" {
  type = string
}

variable "application_code" {
  type = string
}

variable "tags" {
  type = map(string)
}

variable "kms_key_arn" {
  type    = string
  default = ""
}

variable "mysql_bucket_lifecycle_rule" {
  type    = any
  default = []
}

variable "ecr_repositories" {
  type    = list(string)
  default = ["web", "job", "flask"]
}

variable "ecr_keep_last_images" {
  type    = number
  default = 30
}

variable "ecr_read_access_arns" {
  type    = list(string)
  default = []
}

variable "ecr_read_write_access_arns" {
  type    = list(string)
  default = []
}

variable "secret_name" {
  type    = string
  default = "aws/creds"
}

variable "secret_description" {
  type    = string
  default = "Phenome init secret"
}

variable "secret_kms_key_id" {
  type    = string
  default = ""
}

variable "secret_reader_arns" {
  type    = list(string)
  default = []
}

variable "db_password" {
  type      = string
  sensitive = true
  default   = ""
}

variable "fleet_enrollment_token" {
  type      = string
  sensitive = true
  default   = ""
}
