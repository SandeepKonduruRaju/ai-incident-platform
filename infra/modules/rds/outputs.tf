output "address" {
  description = "Hostname of the instance."
  value       = aws_db_instance.this.address
}

output "port" {
  value = aws_db_instance.this.port
}

output "db_name" {
  value = aws_db_instance.this.db_name
}

output "master_user_secret_arn" {
  description = "Secrets Manager secret (JSON with username and password) created and rotated by RDS."
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
}
