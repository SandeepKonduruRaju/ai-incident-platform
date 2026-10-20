output "bootstrap_servers" {
  value = "kafka.${var.namespace_name}:9092"
}

output "service_name" {
  value = module.broker.service_name
}

output "topics_task_definition_family" {
  value = module.topics.task_definition_family
}
