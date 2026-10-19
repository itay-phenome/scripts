output "db_endpoint" {
  value = try(
    module.rds.db_endpoint,
    module.rds.db_instance_address,
    module.rds.endpoint,
    module.rds.address,
    null
  )
}
