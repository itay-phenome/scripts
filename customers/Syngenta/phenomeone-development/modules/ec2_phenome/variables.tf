variable "region" { 
    type = string 
}

variable "name" { 
    type = string 
}

variable "env" { 
    type = string 
}

variable "tags" { 
    type = map(string) 
}

variable "application_code" { 
    type = string 
}

variable "ec2_mode" {
  type    = string
  default = "false"

  validation {
    condition     = contains(["false", "restore", "application"], lower(var.ec2_mode))
    error_message = "ec2_mode must be one of: \"false\", \"restore\", \"application\"."
  }
}

variable "private_subnet_ids" { type = list(string) }
variable "web_sg_id" { type = string }

variable "ami_id" {
  type    = string
  default = ""
}

variable "instance_profile_name" {
  type    = string
  default = ""
}

variable "create_launch_configuration" {
  type    = bool
  default = true
}

variable "web_instance_type" { type = string }
variable "web_asg_instance_type" { type = string }
variable "web_asg_volume_size" { type = number }
variable "web_instance_volume_size" { type = number }

variable "web_min_number" { type = number }
variable "web_max_number" { type = number }
variable "web_desired_number" { type = number }

variable "job_instance_type" { type = string }
variable "job_instance_count" { type = number }
variable "job_instance_volume_size" { type = number }

variable "db_import_instance_volume_size" {
  type    = number
  default = 50
}
variable "enable_ec2" {
  type    = bool
  default = true
}

variable "revision" {
  type = string
}

variable "ssm_revision" {
  type        = string
  default     = ""
  description = "Revision written to the SSM parameter. Defaults to var.revision if not set."
}

variable "web_workers" {
  type = number
}

variable "web_secret_name" {
  type = string
}

variable "web_secret_id" {
  type        = string
  description = "Full AWS Secrets Manager secret name (as created by the Syngenta module)"
}

variable "db_name" {
  type = string
}

variable "db_user" {
  type = string
}

variable "db_port" {
  type = number
}

variable "db_endpoint" {
  type = string
}

variable "image_region" {
  type = string
}

variable "s3_buckets" {
  type    = map(string)
  default = {}
}
variable "sqs_queue_arn" {
  type    = string
  default = ""
}

variable "sqs_queue_name" {
  type    = string
  default = ""
}

variable "enable_alb" {
  type    = bool
  default = true
}

variable "vpc_id" {
  type    = string
  default = ""
}


variable "alb_sg_id" {
  type    = string
  default = ""
}

variable "alb_internal" {
  type    = bool
  default = false
}

variable "acm_certificate_arn" {
  type    = string
  default = ""

  validation {
    condition     = var.enable_alb == false || lower(var.ec2_mode) != "application" || trimspace(var.acm_certificate_arn) != ""
    error_message = "acm_certificate_arn must be non-empty when enable_alb=true and ec2_mode=application."
  }
}


variable "alb_healthcheck_path" {
  type    = string
  default = "/"
}

variable "alb_listener_ssl_policy" {
  type    = string
  default = "ELBSecurityPolicy-TLS13-1-2-2021-06"
}

variable "alb_target_port" {
  type    = number
  default = 80
}

variable "alb_target_protocol" {
  type    = string
  default = "HTTP"
}

variable "alb_subnet_ids" {
  type    = list(string)
  default = []
}

variable "alb_public_subnet_tags" {
  type    = map(string)
  default = {}
}

variable "alb_private_subnet_tags" {
  type    = map(string)
  default = {}
}

variable "alb_healthcheck_protocol" {
  type    = string
  default = "HTTP"

  validation {
    condition     = contains(["HTTP", "HTTPS"], upper(var.alb_healthcheck_protocol))
    error_message = "alb_healthcheck_protocol must be HTTP or HTTPS."
  }
}

variable "kms_key_arn" {
  type    = string
  default = ""
}
variable "ssh_key_name" {
  type    = string
  default = null
}

variable "enable_web_asg" {
  type    = bool
  default = false
}

variable "fleet_url" {
  type    = string
  default = "https://phenome-networks-dffc32.fleet.eu-west-1.aws.found.io:443"
}

variable "elastic_agent_version" {
  type    = string
  default = "8.11.0"
}
