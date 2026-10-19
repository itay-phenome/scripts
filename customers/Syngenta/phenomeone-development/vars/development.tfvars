########################Switch##########################

enable_init = true
enable_sqs  = true
enable_sg   = true
enable_s3   = true
enable_ec2  = true
enable_alb  = true
enable_db      = true
enable_web_asg = true

########################ENV_settings##########################

region = "us-east-1"
name   = "phenome"
env    = "dev"

vpc_id = "vpc-0e5273708f62e6bc0"

private_subnet_ids = [
  "subnet-0bf8c8485a54416a6",
  "subnet-0a329de88f400523a",
]
public_subnet_ids = []

ec2_mode = "application"

########################S3_options###########################

s3_buckets = {
  uploads   = "phn-phenome-dev-uploads-590183981388"
  images    = "phn-phenome-dev-images-590183981388"
  analyses  = "phn-phenome-dev-analyses-590183981388"
  reports   = "phn-phenome-dev-reports-590183981388"
  documents = "phn-phenome-dev-documents-590183981388"
  tiledb    = "phn-phenome-dev-tiledb-590183981388"
}

s3_bucket_versioning = {
  uploads = true
  reports = true
}

########################ALB_options##########################

application_code = "phn"

alb_internal        = true
acm_certificate_arn = "arn:aws:acm:us-east-1:590183981388:certificate/24b3202a-615d-4367-9346-f437a463e0b9"

########################KMS_options##########################

kms_key_arn = "arn:aws:kms:us-east-1:590183981388:key/mrk-81dd82cfc4c84865a4176444a5d7360a"

########################EC2_options##########################
####Only change the ssm_revision parameter, do not change the revision parameter######
revision        = "23248"
ssm_revision    = "59"
ami_id        = "ami-03d029e79c819921a"
web_workers     = 6
web_secret_name = "creds-secret"
web_secret_id   = "phenomeone-dev-creds-secret-secret"

db_name           = "pheno20"
db_engine_version = "8.4.11"
db_instance_type  = "db.m6i.large"
db_user           = "pheno20_admin"
db_port           = 3306
db_endpoint       = "usaedmysphnt001.c5ocmqwi20xe.us-east-1.rds.amazonaws.com"

image_region          = "eu-west-1"
instance_profile_name = "phenome-dev-ec2-ssm-role"

web_instance_type        = "c7i-flex.large"
web_asg_instance_type    = "c7i-flex.xlarge"
web_asg_volume_size      = 100
web_instance_volume_size = 50
web_min_number           = 1
web_max_number           = 6
web_desired_number       = 1

job_instance_type        = "m7i-flex.xlarge"
job_instance_count       = 1
job_instance_volume_size = 50

db_import_instance_volume_size = 50


########################RDS_options##########################

rds_master_credentials_secret_name = "590183981388-rds-mastercredentials"
db_allocated_storage = "399"
db_subnet_group_name = "av-35-1-complete-vpc-applicationsrdsdbsubnetgroup-pztgphkrpahv"

create_parameter_group     = true
rds_parameter_group_name = "phenome-mysql84-parameters"
rds_parameter_group_family = "mysql8.4"
rds_parameter_group_parameters = [
  { name = "group_concat_max_len", value = "1000000", apply_method = "immediate" },
  { name = "innodb_adaptive_hash_index", value = "1", apply_method = "immediate" },
  { name = "innodb_autoinc_lock_mode", value = "2", apply_method = "pending-reboot" },
  { name = "innodb_flush_log_at_trx_commit", value = "2", apply_method = "immediate" },
  { name = "innodb_strict_mode", value = "0", apply_method = "immediate" },
  { name = "log_bin_trust_function_creators", value = "1", apply_method = "immediate" },
  { name = "log_output", value = "FILE", apply_method = "immediate" },
  { name = "long_query_time", value = "10", apply_method = "immediate" },
  { name = "max_allowed_packet", value = "100000000", apply_method = "immediate" },
  { name = "slow_query_log", value = "1", apply_method = "immediate" },
  { name = "sql_mode", value = "NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION", apply_method = "immediate" },
  { name = "binlog_format", value = "ROW", apply_method = "immediate" },
  { name = "authentication_policy", value = "*:caching_sha2_password", apply_method = "pending-reboot" },
  { name = "connect_timeout", value = "108000", apply_method = "immediate" },
  { name = "innodb_print_all_deadlocks", value = "1", apply_method = "immediate" },
  { name = "interactive_timeout", value = "108000", apply_method = "immediate" },
  { name = "net_read_timeout", value = "108000", apply_method = "immediate" },
  { name = "net_write_timeout", value = "108000", apply_method = "immediate" },
  { name = "range_optimizer_max_mem_size", value = "268435456", apply_method = "immediate" },
  { name = "wait_timeout", value = "108000", apply_method = "immediate" }
]
#######################TAGS##########################

tags = {
  Name             = "phenome-dev"
  BusinessFunction = "Vegetable and Flower R+D"
  Platform         = "PhenomeNetwork"
  Application      = "PhenomeOne"
  CostCenter       = "RGCVE408"
  OwnerEmail       = "Diganta.Adhikari@syngenta.com"
  ContactEmail     = "Pradeep.Kethireddy@syngenta.com"
  Environment      = "Development"
  Purpose          = "PhenomeOne Application"
  Application_code = "PHE"
  CreatedByEmail   = "Denys.Novikov@syngenta.com"

  CreatedBy   = "Denys.Novikov@syngenta.com"
  SupportedBy = "Syngenta"

  IACFramework    = "Terraform"
  ProjectIONumber = "REPLACE_ME"
}

##############################################################