output "alb_url" {
  description = "Public API base URL; health: <alb_url>/api/v1/health."
  value       = module.alb.url
}

output "ecr_repository_urls" {
  value = module.ecr.repository_urls
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "service_names" {
  value = {
    incident_service     = module.incident_service.service_name
    investigation_worker = module.investigation_worker.service_name
    kafka                = module.kafka.service_name
  }
}

# Everything the deploy workflow needs for `aws ecs run-task`.
output "one_off_tasks" {
  value = {
    kafka_topics = { family = module.kafka.topics_task_definition_family, security_group = module.security_groups.kafka_id }
    migrate      = { family = module.migrate.task_definition_family, security_group = module.security_groups.worker_id }
    ingest       = { family = module.ingest.task_definition_family, security_group = module.security_groups.worker_id }
  }
}

output "task_subnet_ids" {
  value = module.network.task_subnet_ids
}

output "task_assign_public_ip" {
  value = module.network.task_assign_public_ip
}

output "rds_master_user_secret_arn" {
  description = "The DB credentials secret (managed and rotated by RDS)."
  value       = module.rds.master_user_secret_arn
}
