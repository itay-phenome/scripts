output "bucket_names" {
  value = local.resolved
}

output "uploads_bucket_name" {
  value = local.resolved["uploads"]
}

output "images_bucket_name" {
  value = local.resolved["images"]
}

output "analyses_bucket_name" {
  value = local.resolved["analyses"]
}

output "reports_bucket_name" {
  value = local.resolved["reports"]
}

output "documents_bucket_name" {
  value = local.resolved["documents"]
}

output "tiledb_bucket_name" {
  value = local.resolved["tiledb"]
}
