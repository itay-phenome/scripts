module "sg_web" {
  source  = "app.terraform.io/syngenta-tfc/securitygroup/aws"
  version = "1.0.4"

  security_group_name = local.web_sg_name
  vpc_id              = var.vpc_id
  description         = "Web servers SG"

  ingress_rules = [
    {
      cidr_blocks  = local.internet_cidrs
      description  = "HTTP"
      from_port    = 80
      to_port      = 80
      protocol     = "tcp"
    },
    {
      cidr_blocks  = local.internet_cidrs
      description  = "HTTPS"
      from_port    = 443
      to_port      = 443
      protocol     = "tcp"
    },
    {
      cidr_blocks  = local.ssh_cidrs
      description  = "SSH"
      from_port    = 22
      to_port      = 22
      protocol     = "tcp"
    }
  ]

  egress_rules = [
    {
      cidr_blocks = local.internet_cidrs
      description = "All egress"
      from_port   = 0
      to_port     = 0
      protocol    = "-1"
    }
  ]

  tags = var.tags
}


module "sg_db" {
  source  = "app.terraform.io/syngenta-tfc/securitygroup/aws"
  version = "1.0.4"

  security_group_name = local.db_sg_name
  vpc_id              = var.vpc_id
  description         = "DB SG"

  ingress_rules = [
    {
      cidr_blocks = ["172.16.0.0/12"]
      description = "Syngenta internal"
      from_port   = 3306
      to_port     = 3306
      protocol    = "tcp"
    },
    {
      cidr_blocks = ["192.168.0.0/16"]
      description = "Syngenta internal"
      from_port   = 3306
      to_port     = 3306
      protocol    = "tcp"
    },
    {
      cidr_blocks = ["10.60.128.0/19"]
      description = "AWS Workspaces EUC1"
      from_port   = 3306
      to_port     = 3306
      protocol    = "tcp"
    },
    {
      cidr_blocks = ["10.111.128.0/19"]
      description = "AWS Workspaces USE1"
      from_port   = 3306
      to_port     = 3306
      protocol    = "tcp"
    },
    {
      cidr_blocks = ["10.63.152.0/23"]
      description = "Zscaler ZPA EUC1"
      from_port   = 3306
      to_port     = 3306
      protocol    = "tcp"
    },
    {
      cidr_blocks = ["10.113.248.0/23"]
      description = "Zscaler ZPA USE1"
      from_port   = 3306
      to_port     = 3306
      protocol    = "tcp"
    }
  ]

  ingress_rules_with_source_security_group_ids = [
    {
      source_security_group_id = module.sg_web.security_group_id
      description              = "MySQL from web"
      from_port                = 3306
      to_port                  = 3306
      protocol                 = "tcp"
    }
  ]

  egress_rules = [
    {
      cidr_blocks = local.internet_cidrs
      description = "All egress"
      from_port   = 0
      to_port     = 0
      protocol    = "-1"
    }
  ]

  tags = var.tags
}


module "sg_alb" {
  source  = "app.terraform.io/syngenta-tfc/securitygroup/aws"
  version = "1.0.4"

  security_group_name = local.alb_sg_name
  vpc_id              = var.vpc_id
  description         = "ALB SG"

  ingress_rules = [
    {
      cidr_blocks  = local.internet_cidrs
      description  = "HTTP"
      from_port    = 80
      to_port      = 80
      protocol     = "tcp"
    },
    {
      cidr_blocks  = local.internet_cidrs
      description  = "HTTPS"
      from_port    = 443
      to_port      = 443
      protocol     = "tcp"
    }
  ]

  egress_rules = [
    {
      cidr_blocks = local.internet_cidrs
      description = "All egress"
      from_port   = 0
      to_port     = 0
      protocol    = "-1"
    }
  ]

  tags = var.tags
}

module "sg_vpc_endpoints" {
  source  = "app.terraform.io/syngenta-tfc/securitygroup/aws"
  version = "1.0.4"

  security_group_name = local.vpc_endpoints_sg_name
  vpc_id              = var.vpc_id
  description         = "Security group for VPC endpoints"

  ingress_rules = [
    {
      cidr_blocks  = local.vpc_cidrs
      description  = "HTTPS from VPC"
      from_port    = 443
      to_port      = 443
      protocol     = "tcp"
    }
  ]

  egress_rules = [
    {
      cidr_blocks = local.internet_cidrs
      description = "All egress"
      from_port   = 0
      to_port     = 0
      protocol    = "-1"
    }
  ]

  tags = var.tags
}
