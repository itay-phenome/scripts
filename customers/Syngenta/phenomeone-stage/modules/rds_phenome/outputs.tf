output "db_endpoint" {
  value = try(
    module.rds.db_instance_address,
    module.rds.address,
    split(":", try(module.rds.db_endpoint, module.rds.endpoint, ""))[0],
    null
  )
}
