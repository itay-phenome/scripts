output "web_asg_name" {
  value = local.create_web_asg ? module.web_asg[0].autoscaling_group_name : null
}

output "web_launch_template_id" {
  value = local.create_web_asg ? try(module.web_asg[0].launch_template_id, null) : null
}

output "job_instance_ids" {
  value = [for m in module.job : m.id]
}

output "job_private_ips" {
  value = [for m in module.job : m.private_ip]
}

output "db_import_instance_id" {
  value = length(module.db_import) > 0 ? module.db_import[0].id : null
}

output "db_import_private_ip" {
  value = length(module.db_import) > 0 ? module.db_import[0].private_ip : null
}

output "alb_dns_name" {
  value = local.enable_alb_final ? try(module.alb[0].lb_dns_name, null) : null
}

output "alb_arn" {
  value = local.enable_alb_final ? try(module.alb[0].lb_arn, null) : null
}

output "alb_target_group_arns" {
  value = local.enable_alb_final ? try(module.alb[0].target_group_arns, []) : []
}
