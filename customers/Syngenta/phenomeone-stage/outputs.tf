
output "s3_bucket_names" {
  value = var.enable_s3 ? module.s3_phenome[0].bucket_names : null
}

output "uploads_bucket_name" {
  value = var.enable_s3 ? module.s3_phenome[0].uploads_bucket_name : null
}

output "images_bucket_name" {
  value = var.enable_s3 ? module.s3_phenome[0].images_bucket_name : null
}

output "analyses_bucket_name" {
  value = var.enable_s3 ? module.s3_phenome[0].analyses_bucket_name : null
}

output "reports_bucket_name" {
  value = var.enable_s3 ? module.s3_phenome[0].reports_bucket_name : null
}

output "documents_bucket_name" {
  value = var.enable_s3 ? module.s3_phenome[0].documents_bucket_name : null
}

output "tiledb_bucket_name" {
  value = var.enable_s3 ? module.s3_phenome[0].tiledb_bucket_name : null
}

output "web_asg_name" {
  value = var.enable_ec2 ? module.ec2_phenome[0].web_asg_name : null
}

output "job_instance_ids" {
  value = var.enable_ec2 ? module.ec2_phenome[0].job_instance_ids : null
}

output "job_private_ips" {
  value = var.enable_ec2 ? module.ec2_phenome[0].job_private_ips : null
}

output "db_import_instance_id" {
  value = var.enable_ec2 ? module.ec2_phenome[0].db_import_instance_id : null
}

output "db_import_private_ip" {
  value = var.enable_ec2 ? module.ec2_phenome[0].db_import_private_ip : null
}

output "sqs_queue_url" {
  value = var.enable_sqs ? module.sqs_phenome[0].queue_url : null
}

output "sqs_queue_arn" {
  value = var.enable_sqs ? module.sqs_phenome[0].queue_arn : null
}

output "sqs_queue_name" {
  value = var.enable_sqs ? module.sqs_phenome[0].queue_name : null
}

# MINT Identity Management
output "sqs_fifo_integration_arn" {
  value = var.enable_sqs ? module.sqs_phenome[0].sqs_fifo_integration_arn : null
}

output "sqs_fifo_integration_url" {
  value = var.enable_sqs ? module.sqs_phenome[0].sqs_fifo_integration_url : null
}

output "sns_fifo_integration_arn" {
  value = var.enable_sqs ? module.sqs_phenome[0].sns_fifo_integration_arn : null
}

# MINT Material Management
output "sqs_fifo_material_arn" {
  value = var.enable_sqs ? module.sqs_phenome[0].sqs_fifo_material_arn : null
}

output "sqs_fifo_material_url" {
  value = var.enable_sqs ? module.sqs_phenome[0].sqs_fifo_material_url : null
}

output "sns_fifo_material_arn" {
  value = var.enable_sqs ? module.sqs_phenome[0].sns_fifo_material_arn : null
}

output "web_sg_id" {
  value = var.enable_sg ? module.sg_phenome[0].web_sg_id : null
}

output "db_sg_id" {
  value = var.enable_sg ? module.sg_phenome[0].db_sg_id : null
}

output "alb_sg_id" {
  value = var.enable_sg ? module.sg_phenome[0].alb_sg_id : null
}

output "vpc_endpoints_sg_id" {
  value = var.enable_sg ? module.sg_phenome[0].vpc_endpoints_sg_id : null
}

output "alb_dns_name" {
  value = var.enable_ec2 ? module.ec2_phenome[0].alb_dns_name : null
}

output "alb_arn" {
  value = var.enable_ec2 ? module.ec2_phenome[0].alb_arn : null
}

output "alb_target_group_arns" {
  value = var.enable_ec2 ? module.ec2_phenome[0].alb_target_group_arns : null
}

