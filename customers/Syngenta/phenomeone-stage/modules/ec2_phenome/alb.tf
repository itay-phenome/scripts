module "alb" {
  source  = "app.terraform.io/syngenta-tfc/alb-nlb/aws"
  version = "1.0.7"
  count   = local.enable_alb_final ? 1 : 0

  lb_custom_name     = local.alb_custom_name
  load_balancer_type = "application"
  internal           = true

  vpc_id          = var.vpc_id
  security_groups = [var.alb_sg_id]
  subnets         = var.private_subnet_ids

  # HTTP listener - redirect to HTTPS
  http_tcp_listeners = [
    {
      port        = 80
      protocol    = "HTTP"
      action_type = "redirect"
      redirect = {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  ]

  # HTTPS listener
  https_listeners = [
    {
      port               = 443
      protocol           = "HTTPS"
      certificate_arn    = var.acm_certificate_arn
      target_group_index = 0
    }
  ]

  target_groups = [
    {
      name                 = "web"
      backend_protocol     = var.alb_target_protocol
      backend_port         = var.alb_target_port
      target_type          = "instance"
      deregistration_delay = 30

      health_check = {
        enabled             = true
        interval            = 30
        path                = var.alb_healthcheck_path
        port                = "traffic-port"
        healthy_threshold   = 3
        unhealthy_threshold = 3
        timeout             = 6
        protocol            = local.alb_healthcheck_protocol_final
        matcher             = "200-399"
      }

      protocol_version = "HTTP1"

      stickiness = {
        enabled         = true
        type            = "lb_cookie"
        cookie_duration = 86400
      }
    }
  ]

  tags = var.tags
}

resource "aws_lb_target_group_attachment" "web" {
  count = 0

  target_group_arn = module.alb[0].target_group_arns[0]
  target_id        = module.web[count.index].id
  port             = var.alb_target_port
}
