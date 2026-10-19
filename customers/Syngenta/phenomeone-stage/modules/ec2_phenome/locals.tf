locals {
  kms_key_id_final     = trimspace(var.kms_key_arn) != "" ? var.kms_key_arn : null
  ebs_kms_key_id_final = local.kms_key_id_final

  s3 = var.s3_buckets

  uploads_bucket_name   = try(local.s3["uploads"], "")
  images_bucket_name    = try(local.s3["images"], "")
  analyses_bucket_name  = try(local.s3["analyses"], "")
  reports_bucket_name   = try(local.s3["reports"], "")
  documents_bucket_name = try(local.s3["documents"], "")
  tiledb_bucket_name    = try(local.s3["tiledb"], "")

  sqs_queue_name                 = var.sqs_queue_name != "" ? var.sqs_queue_name : "${var.name}-${var.env}-sqs"
  effective_revision             = trimspace(var.revision) != "" ? var.revision : var.ssm_revision
  alb_healthcheck_protocol_final = upper(var.alb_healthcheck_protocol)

  elastic_agent_vars = {
    env                   = var.env
    fleet_url             = var.fleet_url
    elastic_agent_version = var.elastic_agent_version
  }
  elastic_agent_web = templatefile("${path.module}/userdata/elastic_agent.sh.tftpl", merge(local.elastic_agent_vars, { role = "web" }))
  elastic_agent_job = templatefile("${path.module}/userdata/elastic_agent.sh.tftpl", merge(local.elastic_agent_vars, { role = "job" }))

  web_user_data = templatefile("${path.module}/userdata/web.sh.tftpl", {
    region                = var.region
    elastic_agent         = local.elastic_agent_web
    image_region          = var.image_region
    revision              = local.effective_revision
    ssm_param_path        = local.create_app ? module.ssm_revision[0].ssm_parameter_name : ""
    web_workers           = var.web_workers
    web_secret_name       = var.web_secret_id
    db_name               = var.db_name
    db_user               = var.db_user
    db_port               = var.db_port
    db_endpoint           = var.db_endpoint
    uploads_bucket_name   = local.uploads_bucket_name
    images_bucket_name    = local.images_bucket_name
    analyses_bucket_name  = local.analyses_bucket_name
    reports_bucket_name   = local.reports_bucket_name
    documents_bucket_name = local.documents_bucket_name
    tiledb_bucket_name    = local.tiledb_bucket_name
    sqs_queue_name        = local.sqs_queue_name

    sns_mint_material_arn    = var.sns_mint_material_arn
    sns_mint_integration_arn = var.sns_mint_integration_arn
    sqs_mint_material_arn    = var.sqs_mint_material_arn
    sqs_mint_integration_arn = var.sqs_mint_integration_arn
  })

  job_user_data = templatefile("${path.module}/userdata/job.sh.tftpl", {
    region                = var.region
    elastic_agent         = local.elastic_agent_job
    image_region          = var.image_region
    revision              = local.effective_revision
    ssm_param_path        = local.create_app ? module.ssm_revision[0].ssm_parameter_name : ""
    web_secret_name       = var.web_secret_id
    db_name               = var.db_name
    db_user               = var.db_user
    db_port               = var.db_port
    db_endpoint           = var.db_endpoint
    uploads_bucket_name   = local.uploads_bucket_name
    images_bucket_name    = local.images_bucket_name
    analyses_bucket_name  = local.analyses_bucket_name
    reports_bucket_name   = local.reports_bucket_name
    documents_bucket_name = local.documents_bucket_name
    tiledb_bucket_name    = local.tiledb_bucket_name
    sqs_queue_name        = local.sqs_queue_name

    sns_mint_material_arn    = var.sns_mint_material_arn
    sns_mint_integration_arn = var.sns_mint_integration_arn
    sqs_mint_material_arn    = var.sqs_mint_material_arn
    sqs_mint_integration_arn = var.sqs_mint_integration_arn
  })

  db_import_user_data = templatefile("${path.module}/userdata/db_import.sh.tftpl", {
    region          = var.region
    web_secret_name = var.web_secret_id
    db_name         = var.db_name
    db_user         = var.db_user
    db_port         = var.db_port
    db_endpoint     = var.db_endpoint
  })

  mode           = lower(var.ec2_mode)
  create_app     = local.mode == "application"
  create_restore = local.mode == "restore"

  create_web_asg = local.create_app && var.enable_web_asg

  prefix   = "${var.application_code}-${var.name}-${var.env}"
  asg_name = "${local.prefix}-web-asg"

  enable_alb_final = var.enable_alb

  alb_custom_name = "web"

  alb_subnet_ids_final = local.enable_alb_final ? (
    length(var.alb_subnet_ids) > 0 ? var.alb_subnet_ids : (
      var.alb_internal
      ? try(data.aws_subnets.alb_private[0].ids, [])
      : try(data.aws_subnets.alb_public[0].ids, [])
    )
  ) : []
}
