output "web_sg_id" {
  value = module.sg_web.security_group_id
}

output "db_sg_id" {
  value = module.sg_db.security_group_id
}

output "alb_sg_id" {
  value = module.sg_alb.security_group_id
}

output "vpc_endpoints_sg_id" {
  value = module.sg_vpc_endpoints.security_group_id
}
