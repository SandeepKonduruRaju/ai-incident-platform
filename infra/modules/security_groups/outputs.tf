output "alb_id" {
  value = aws_security_group.alb.id
}

output "incident_service_id" {
  value = aws_security_group.incident_service.id
}

output "worker_id" {
  value = aws_security_group.worker.id
}

output "kafka_id" {
  value = aws_security_group.kafka.id
}

output "rds_id" {
  value = aws_security_group.rds.id
}
