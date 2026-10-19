variable "name" { type = string }
variable "env"  { type = string }

variable "buckets" {
  type    = map(string)
  default = {}
}

variable "bucket_versioning" {
  type    = map(bool)
  default = {}
}

variable "tags" {
  type = map(string)
}
variable "kms_key_arn" {
  type    = string
  default = ""
}