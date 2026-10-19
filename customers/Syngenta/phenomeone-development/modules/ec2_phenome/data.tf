data "aws_subnets" "alb_public" {
  count = local.enable_alb_final && !var.alb_internal && length(var.alb_subnet_ids) == 0 ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }

  tags = var.alb_public_subnet_tags
}

data "aws_subnets" "alb_private" {
  count = local.enable_alb_final && var.alb_internal && length(var.alb_subnet_ids) == 0 ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }

  tags = var.alb_private_subnet_tags
}