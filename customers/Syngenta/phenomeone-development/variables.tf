variable "enable_kms" {
  type    = bool
  default = false
}

variable "enable_init" {
  type    = bool
  default = false
}

variable "enable_s3" {
  type    = bool
  default = false
}

variable "enable_sqs" {
  type    = bool
  default = false
}

variable "enable_sg" {
  type    = bool
  default = false
}

variable "enable_ec2" {
  type    = bool
  default = false
}

variable "enable_alb" {
  type    = bool
  default = false
}

variable "enable_db" {
  type    = bool
  default = false
}

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

variable "kms_key_arn" {
  type    = string
  default = ""
}

variable "application_code" {
  type    = string
  default = ""

  validation {
    condition = (
      (var.enable_init || var.enable_ec2 || var.enable_db) == false
      || trimspace(var.application_code) != ""
    )
    error_message = "application_code is required when enable_init/enable_ec2/enable_db is true."
  }
}

variable "web_secret_name" {
  type    = string
  default = "aws/creds"
}

variable "web_secret_id" {
  type        = string
  description = "Full AWS Secrets Manager secret name (as created by the Syngenta module)"
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

variable "s3_buckets" {
  type    = map(string)
  default = {}
}

variable "s3_bucket_versioning" {
  type    = map(bool)
  default = {}
}

variable "vpc_id" {
  type    = string
  default = ""

  validation {
    condition = (
      (var.enable_sg || var.enable_ec2 || var.enable_alb || var.enable_db) == false
      || trimspace(var.vpc_id) != ""
    )
    error_message = "vpc_id is required when enable_sg/enable_ec2/enable_alb/enable_db is true."
  }
}

variable "db_security_group_ids" {
  type    = list(string)
  default = []

  validation {
    condition     = var.enable_db == false || var.enable_sg == true || length(var.db_security_group_ids) > 0
    error_message = "db_security_group_ids must be provided when enable_db is true and enable_sg is false."
  }
}

variable "private_subnet_ids" {
  type    = list(string)
  default = []

  validation {
    condition = (
      (var.enable_ec2 || var.enable_db) == false
      || length(var.private_subnet_ids) > 0
    )
    error_message = "private_subnet_ids is required when enable_ec2/enable_db is true."
  }
}

variable "public_subnet_ids" {
  type    = list(string)
  default = []

  validation {
    condition = (
      var.enable_alb == false
      || var.alb_internal == true
      || length(var.public_subnet_ids) > 0
    )
    error_message = "public_subnet_ids is required when enable_alb is true and alb_internal is false."
  }
}


variable "alb_internal" {
  type    = bool
  default = false
}

variable "acm_certificate_arn" {
  type    = string
  default = ""

  validation {
    condition = (
      var.enable_alb == false
      || trimspace(var.acm_certificate_arn) != ""
    )
    error_message = "acm_certificate_arn is required when enable_alb is true."
  }
}

variable "ec2_mode" {
  type    = string
  default = "false"

  validation {
    condition     = contains(["false", "restore", "application"], lower(var.ec2_mode))
    error_message = "ec2_mode must be one of: \"false\", \"restore\", \"application\"."
  }
}

variable "revision" {
  type    = string
  default = ""

  validation {
    condition = (
      var.enable_ec2 == false
      || lower(var.ec2_mode) == "false"
      || trimspace(var.revision) != ""
    )
    error_message = "revision is required when enable_ec2 is true and ec2_mode != false."
  }
}

variable "ssm_revision" {
  type        = string
  default     = ""
  description = "Revision written to the SSM parameter (read by cron on instances). Defaults to var.revision if not set."
}

variable "web_workers" {
  type    = number
  default = 0

  validation {
    condition = (
      var.enable_ec2 == false
      || lower(var.ec2_mode) == "false"
      || var.web_workers > 0
    )
    error_message = "web_workers must be > 0 when enable_ec2 is true and ec2_mode != false."
  }
}

variable "db_name" {
  type    = string
  default = ""

  validation {
    condition = (
      var.enable_ec2 == false
      || lower(var.ec2_mode) == "false"
      || trimspace(var.db_name) != ""
    )
    error_message = "db_name is required when enable_ec2 is true and ec2_mode != false."
  }
}

variable "db_user" {
  type    = string
  default = ""

  validation {
    condition = (
      var.enable_ec2 == false
      || lower(var.ec2_mode) == "false"
      || trimspace(var.db_user) != ""
    )
    error_message = "db_user is required when enable_ec2 is true and ec2_mode != false."
  }
}

variable "db_port" {
  type    = number
  default = 3306

  validation {
    condition = (
      var.enable_ec2 == false
      || lower(var.ec2_mode) == "false"
      || var.db_port > 0
    )
    error_message = "db_port must be > 0 when enable_ec2 is true and ec2_mode != false."
  }
}

variable "db_endpoint" {
  type    = string
  default = ""

  validation {
    condition = (
      var.enable_ec2 == false
      || lower(var.ec2_mode) == "false"
      || var.enable_db == true
      || trimspace(var.db_endpoint) != ""
    )
    error_message = "db_endpoint is required when enable_ec2=true and ec2_mode!=false and enable_db=false."
  }
}

variable "image_region" {
  type    = string
  default = ""

  validation {
    condition = (
      var.enable_ec2 == false
      || lower(var.ec2_mode) == "false"
      || trimspace(var.image_region) != ""
    )
    error_message = "image_region is required when enable_ec2 is true and ec2_mode != false."
  }
}

variable "instance_profile_name" {
  type    = string
  default = ""

  validation {
    condition = (
      var.enable_ec2 == false
      || lower(var.ec2_mode) == "false"
      || trimspace(var.instance_profile_name) != ""
    )
    error_message = "instance_profile_name is required when enable_ec2 is true and ec2_mode != false."
  }
}

variable "web_instance_type" {
  type    = string
  default = ""

  validation {
    condition = (
      var.enable_ec2 == false
      || lower(var.ec2_mode) == "false"
      || trimspace(var.web_instance_type) != ""
    )
    error_message = "web_instance_type is required when enable_ec2 is true and ec2_mode != false."
  }
}

variable "web_asg_instance_type" {
  type    = string
  default = "t3.xlarge"
}

variable "web_asg_volume_size" {
  type    = number
  default = 100
}

variable "web_instance_volume_size" {
  type    = number
  default = 0

  validation {
    condition = (
      var.enable_ec2 == false
      || lower(var.ec2_mode) == "false"
      || var.web_instance_volume_size > 0
    )
    error_message = "web_instance_volume_size must be > 0 when enable_ec2 is true and ec2_mode != false."
  }
}

variable "web_min_number" {
  type    = number
  default = 0
}

variable "web_max_number" {
  type    = number
  default = 0
}

variable "web_desired_number" {
  type    = number
  default = 0
}

variable "job_instance_type" {
  type    = string
  default = ""
}

variable "job_instance_count" {
  type    = number
  default = 0
}

variable "job_instance_volume_size" {
  type    = number
  default = 0
}

variable "db_import_instance_volume_size" {
  type    = number
  default = 0
}

variable "db_subnet_group_name" {
  type    = string
  default = null

  validation {
    condition     = var.enable_db == false || (var.db_subnet_group_name != null && var.db_subnet_group_name != "")
    error_message = "db_subnet_group_name is required when enable_db is true."
  }
}

variable "db_engine_version" {
  type    = string
  default = null

  validation {
    condition     = var.enable_db == false || (var.db_engine_version != null && var.db_engine_version != "")
    error_message = "db_engine_version is required when enable_db is true."
  }
}

variable "db_instance_type" {
  type    = string
  default = null

  validation {
    condition     = var.enable_db == false || (var.db_instance_type != null && var.db_instance_type != "")
    error_message = "db_instance_type is required when enable_db is true."
  }
}

variable "rds_master_credentials_secret_name" {
  type    = string
  default = null

  validation {
    condition     = var.enable_db == false || (var.rds_master_credentials_secret_name != null && var.rds_master_credentials_secret_name != "")
    error_message = "rds_master_credentials_secret_name is required when enable_db is true."
  }
}
variable "create_parameter_group" {
  description = "Whether to create a custom RDS parameter group"
  type        = bool
  default     = false
}

variable "rds_parameter_group_name" {
  type    = string
  default = ""
}

variable "rds_parameter_group_parameters" {
  type    = list(map(string))
  default = []
}

variable "rds_parameter_group_family" {
  type    = string
  default = "mysql8.0"
}

variable "db_allocated_storage" {
  type    = string
  default = null

  validation {
    condition     = var.enable_db == false || (var.db_allocated_storage != null && trimspace(var.db_allocated_storage) != "")
    error_message = "db_allocated_storage is required when enable_db is true."
  }
}
variable "ami_id" {
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
