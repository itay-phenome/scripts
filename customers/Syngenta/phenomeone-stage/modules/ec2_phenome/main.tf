
module "web" {
  source  = "app.terraform.io/syngenta-tfc/ec2/aws"
  version = "1.1.4"

  count = 0

  server_count        = format("%03d", count.index + 1)
  region              = var.region
  server_type         = "infrastructure"
  server_os           = "linux"
  application_code    = var.application_code

  name                        = "${local.prefix}-web-${format("%03d", count.index + 1)}"
  ami                         = var.ami_id
  instance_type               = var.web_instance_type
  subnet_id                   = element(var.private_subnet_ids, count.index % length(var.private_subnet_ids))
  vpc_security_group_ids      = [var.web_sg_id, "sg-059f3036b87ee4adb", "sg-06c5d31b8f9602f77"]
  associate_public_ip_address = false
  iam_instance_profile        = var.instance_profile_name != "" ? var.instance_profile_name : null
  additional_volumes_for_attach_detach = []

  # Frozen userdata: points to the committed template to avoid instance restart.
  # New changes go into web.sh.tftpl which is used by the ASG launch template.
  # Remove this module entirely once ASG is verified.
  user_data = templatefile("${path.module}/userdata/web_frozen.sh.tftpl", {
    region                = var.region
    revision              = local.effective_revision
    db_name               = var.db_name
    db_endpoint           = var.db_endpoint
    db_port               = var.db_port
    db_user               = var.db_user
    sqs_queue_name        = var.sqs_queue_name
    tiledb_bucket_name    = var.s3_buckets["tiledb"]
    uploads_bucket_name   = var.s3_buckets["uploads"]
    images_bucket_name    = var.s3_buckets["images"]
    analyses_bucket_name  = var.s3_buckets["analyses"]
    reports_bucket_name   = var.s3_buckets["reports"]
    documents_bucket_name = var.s3_buckets["documents"]
  })

  root_block_device = [
    {
      volume_type = "gp3"
      volume_size = var.web_instance_volume_size
      encrypted   = true
      kms_key_id  = local.ebs_kms_key_id_final
    }
  ]

  tags = merge(
    var.tags,
    {
      Name = "${local.prefix}-web-${format("%03d", count.index + 1)}"
    }
  )
}

###############################################################################
# SSM Parameter — current revision (read by cron on instances)
###############################################################################
module "ssm_revision" {
  source  = "app.terraform.io/syngenta-tfc/ssmparameters/aws"
  version = "1.0.1"
  count   = local.create_app ? 1 : 0

  name        = "revision"
  value       = var.ssm_revision != "" ? var.ssm_revision : var.revision
  type        = "String"
  overwrite   = true
  description = "Current application revision number"
  tags        = var.tags
}

###############################################################################
# Web ASG — Syngenta autoscaling module (Launch Template + ASG)
###############################################################################
module "web_asg" {
  source  = "app.terraform.io/syngenta-tfc/autoscaling/aws"
  version = "1.0.7"

  count = local.create_web_asg ? 1 : 0

  asg_name = local.asg_name
  region   = var.region

  create_launch_template      = true
  launch_template_description = "Launch template for ${local.prefix} web ASG"

  image_id      = var.ami_id
  instance_type = var.web_asg_instance_type

  security_groups           = [var.web_sg_id, "sg-059f3036b87ee4adb", "sg-06c5d31b8f9602f77"]
  iam_instance_profile_name = var.instance_profile_name != "" ? var.instance_profile_name : null

  # IMDSv2 optional: legacy Perl AWS libs (VM::EC2::Security::CredentialCache) only support
  # the v1 token-less GET, not the v2 PUT-token handshake.
  metadata_options = {
    http_endpoint               = "enabled"
    http_tokens                 = "optional"
    http_put_response_hop_limit = "2"
  }

  user_data = base64gzip(local.web_user_data)

  block_device_mappings = [
    {
      device_name = "/dev/xvda"
      ebs = {
        volume_size = var.web_asg_volume_size
        volume_type = "gp3"
        encrypted   = true
      }
    }
  ]

  vpc_zone_identifier = var.private_subnet_ids
  target_group_arns   = local.enable_alb_final ? [module.alb[0].target_group_arns[0]] : []

  min_size         = var.web_min_number
  max_size         = var.web_max_number
  desired_capacity = var.web_desired_number

  health_check_type         = "EC2"
  health_check_grace_period = 600

  instance_refresh = {
    strategy = "Rolling"
    preferences = {
      min_healthy_percentage = 50
      instance_warmup        = 300
    }
    triggers = ["tag"]
  }

  tag_specifications = [
    {
      resource_type = "instance"
      tags = merge(var.tags, {
        Name = "${local.prefix}-web-asg"
      })
    },
    {
      resource_type = "volume"
      tags = merge(var.tags, {
        Name = "${local.prefix}-web-asg"
      })
    }
  ]

  scaling_policies = {
    cpu-scaling = {
      policy_type               = "TargetTrackingScaling"
      estimated_instance_warmup = 900
      target_tracking_configuration = {
        predefined_metric_specification = {
          predefined_metric_type = "ASGAverageCPUUtilization"
        }
        target_value = 80.0
      }
    }
  }

  tags = merge(var.tags, {
    Name                    = "${local.prefix}-web-asg"
    MetadataOptionsRevision = "3"
  })
}

module "job" {
  source  = "app.terraform.io/syngenta-tfc/ec2/aws"
  version = "1.1.4"

  count = local.create_app ? var.job_instance_count : 0

  server_count                         = format("%03d", count.index + 1)
  region                               = var.region
  server_type                          = "infrastructure"
  additional_volumes_for_attach_detach = []
  server_os                            = "linux"
  application_code                     = var.application_code

  name                        = "${local.prefix}-job-${format("%03d", count.index + 1)}"
  ami                         = var.ami_id
  instance_type               = var.job_instance_type
  subnet_id                   = element(var.private_subnet_ids, count.index % length(var.private_subnet_ids))
  vpc_security_group_ids      = [var.web_sg_id, "sg-059f3036b87ee4adb", "sg-06c5d31b8f9602f77"]
  associate_public_ip_address = false
  iam_instance_profile        = var.instance_profile_name != "" ? var.instance_profile_name : null

  # IMDSv2 optional: legacy Perl AWS libs (VM::EC2::Security::CredentialCache) only support
  # the v1 token-less GET, not the v2 PUT-token handshake.
  metadata_options = {
    http_endpoint               = "enabled"
    http_tokens                 = "optional"
    http_put_response_hop_limit = "2"
  }

  user_data = local.job_user_data

  root_block_device = [
    {
      volume_type = "gp3"
      volume_size = var.job_instance_volume_size
      encrypted   = true
      kms_key_id  = local.ebs_kms_key_id_final
    }
  ]

  tags = merge(
    var.tags,
    {
      Name = "${local.prefix}-job-${format("%03d", count.index + 1)}"
    }
  )
}


module "db_import" {
  source  = "app.terraform.io/syngenta-tfc/ec2/aws"
  version = "1.1.4"

  count = local.create_restore ? 1 : 0

  server_count                         = "001"
  region                               = var.region
  server_type                          = "infrastructure"
  additional_volumes_for_attach_detach = []
  server_os                            = "linux"
  application_code                     = var.application_code

  name                        = "${local.prefix}-db-import-001"
  ami                         = "ami-03d029e79c819921a"
  instance_type               = "t3.xlarge"
  subnet_id                   = var.private_subnet_ids[0]
  vpc_security_group_ids      = [var.web_sg_id, "sg-059f3036b87ee4adb", "sg-06c5d31b8f9602f77"]
  associate_public_ip_address = false
  iam_instance_profile        = "phenome-dev-ec2-ssm-role"

  root_block_device = [
    {
      volume_type = "gp3"
      volume_size = var.db_import_instance_volume_size
      encrypted   = true
      kms_key_id  = local.ebs_kms_key_id_final
    }
  ]

  tags = var.tags
}




