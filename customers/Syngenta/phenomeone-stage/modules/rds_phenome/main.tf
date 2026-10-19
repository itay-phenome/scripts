module "rds" {
  source  = "app.terraform.io/syngenta-tfc/rds/aws"
  version = "1.0.4"

  region                 = var.region
  environment            = var.environment
  application_code       = var.application_code
  vpc_security_group_ids = var.vpc_security_group_ids
  db_subnet_group_name   = var.db_subnet_group_name
  allocated_storage   = var.allocated_storage
  snapshot_identifier = var.snapshot_identifier

  engine         = var.db_engine
  engine_version = var.db_engine_version
  instance_class = var.db_instance_type

  db_name         = var.db_name
  master_username = local.master_username
  password        = local.master_password

  kms_key_id = local.kms_key_id_final

  create_parameter_group     = var.rds_create_parameter_group
  parameter_group_name       = local.parameter_group_name_final
  parameter_group_family     = var.rds_parameter_group_family
  parameter_group_parameters = var.rds_parameter_group_parameters

  tags = local.tags_final
}
