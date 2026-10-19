variable "region" {
  type = string
}

variable "environment" {
  type = string
}

variable "application_code" {
  type = string
}

variable "vpc_security_group_ids" {
  type = list(string)
}

variable "db_subnet_group_name" {
  type = string
}

variable "db_name" {
  type    = string
  default = null
}

variable "db_engine" {
  type    = string
  default = "mysql"
}

variable "db_engine_version" {
  type    = string
  default = null
}

variable "db_instance_type" {
  type    = string
  default = null
}

variable "kms_key_arn" {
  type    = string
  default = ""
}

variable "master_credentials_secret_name" {
  type = string
}

variable "rds_parameter_group_name" {
  type    = string
  default = ""
}

variable "rds_create_parameter_group" {
  type    = bool
  default = false
}

variable "rds_parameter_group_family" {
  type    = string
  default = ""
}

variable "rds_parameter_group_parameters" {
  type    = list(map(string))
  default = []
}

variable "tags" {
  type = map(string)
}

variable "allocated_storage" {
  type    = string
  default = null
}

variable "snapshot_identifier" {
  type    = string
  default = null
}
