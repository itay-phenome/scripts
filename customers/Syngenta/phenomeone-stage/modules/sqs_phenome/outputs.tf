output "queue_url" {
  value = try(
    module.sqs.sqs_queue_id,
    module.sqs.queue_url,
    module.sqs.sqs,
    null
  )
}

output "queue_arn" {
  value = try(
    module.sqs.sqs_queue_arn,
    module.sqs.queue_arn,
    null
  )
}

output "queue_name" {
  value = try(
    module.sqs.sqs_queue_name,
    module.sqs.name,
    null
  )
}


output "sns_fifo_integration_arn" {
  description = "ARN of SNS FIFO integration topic"
  value       = module.sns_fifo_integration.sns_topic_arn
}

output "sqs_fifo_integration_arn" {
  description = "ARN of SQS FIFO integration queue"
  value       = module.sqs_fifo_integration.sqs_queue_arn
}

output "sqs_fifo_integration_url" {
  description = "URL of SQS FIFO integration queue"
  value       = module.sqs_fifo_integration.sqs_queue_id
}

output "sns_fifo_material_arn" {
  description = "ARN of SNS FIFO material management topic"
  value       = module.sns_fifo_material.sns_topic_arn
}

output "sqs_fifo_material_arn" {
  description = "ARN of SQS FIFO material management queue"
  value       = module.sqs_fifo_material.sqs_queue_arn
}

output "sqs_fifo_material_url" {
  description = "URL of SQS FIFO material management queue"
  value       = module.sqs_fifo_material.sqs_queue_id
}



