provider "aws" {
  region = var.region
}

module "init_phenome" {
  count  = var.enable_init ? 1 : 0
  source = "./modules/init_phenome"

  region           = var.region
  name             = var.name
  env              = var.env
  application_code = var.application_code

  tags       = var.tags
  kms_key_arn = var.kms_key_arn

  secret_name        = var.web_secret_name
  secret_description = "Phenome init secret"

  db_password            = var.db_password
  fleet_enrollment_token = var.fleet_enrollment_token
}


module "s3_phenome" {
  count  = var.enable_s3 ? 1 : 0
  source = "./modules/s3_phenome"

  name              = var.name
  env               = var.env
  buckets           = var.s3_buckets
  bucket_versioning = var.s3_bucket_versioning
  tags              = var.tags

  kms_key_arn = var.kms_key_arn
}

module "sqs_phenome" {
  count  = var.enable_sqs ? 1 : 0
  source = "./modules/sqs_phenome"

  name = var.name
  env  = var.env
  tags = var.tags

  kms_sqs_key_arn = var.kms_key_arn
}

module "sg_phenome" {
  count  = var.enable_sg ? 1 : 0
  source = "./modules/sg_phenome"

  name   = var.name
  env    = var.env
  vpc_id = var.vpc_id
  tags   = var.tags
}

module "ec2_phenome" {
  count  = var.enable_ec2 ? 1 : 0
  source = "./modules/ec2_phenome"

  region           = var.region
  name             = var.name
  env              = var.env
  tags             = var.tags
  ami_id           = var.ami_id
  application_code = var.application_code

  ec2_mode = var.ec2_mode

  private_subnet_ids = var.private_subnet_ids
  web_sg_id          = module.sg_phenome[0].web_sg_id

  revision        = var.revision
  ssm_revision    = var.ssm_revision
  ssh_key_name = var.ssh_key_name
  web_workers     = var.web_workers
  web_secret_name = var.web_secret_name
  web_secret_id   = var.web_secret_id
  db_name         = var.db_name
  db_user         = var.db_user
  db_port         = var.db_port
  db_endpoint     = var.enable_db ? module.rds_phenome[0].db_endpoint : var.db_endpoint
  enable_alb          = var.enable_alb
  vpc_id              = var.vpc_id
  alb_sg_id           = module.sg_phenome[0].alb_sg_id
  alb_internal        = var.alb_internal
  acm_certificate_arn = var.acm_certificate_arn

  image_region           = var.image_region
  instance_profile_name  = var.instance_profile_name
  kms_key_arn = var.kms_key_arn
  s3_buckets = var.enable_s3 ? module.s3_phenome[0].bucket_names : {}

  web_instance_type        = var.web_instance_type
  web_asg_instance_type    = var.web_asg_instance_type
  web_asg_volume_size      = var.web_asg_volume_size
  web_instance_volume_size = var.web_instance_volume_size
  web_min_number           = var.web_min_number
  web_max_number           = var.web_max_number
  web_desired_number       = var.web_desired_number

  job_instance_type        = var.job_instance_type
  job_instance_count       = var.job_instance_count
  job_instance_volume_size = var.job_instance_volume_size

  db_import_instance_volume_size = var.db_import_instance_volume_size

  sqs_queue_name = var.enable_sqs ? module.sqs_phenome[0].queue_name : ""

  enable_web_asg = var.enable_web_asg
}


module "rds_phenome" {
  count  = var.enable_db ? 1 : 0
  source = "./modules/rds_phenome"

  region           = var.region
  environment      = var.env
  application_code = var.application_code
  allocated_storage = var.db_allocated_storage

  vpc_security_group_ids = [module.sg_phenome[0].db_sg_id]
  db_subnet_group_name   = var.db_subnet_group_name

  db_name           = var.db_name
  db_engine_version = var.db_engine_version
  db_instance_type  = var.db_instance_type

  kms_key_arn = var.kms_key_arn

  master_credentials_secret_name = var.rds_master_credentials_secret_name

  rds_parameter_group_name = var.rds_parameter_group_name
  rds_create_parameter_group = var.create_parameter_group
  rds_parameter_group_family = var.rds_parameter_group_family
  rds_parameter_group_parameters = var.rds_parameter_group_parameters

  tags = var.tags
}

