output "jwt_secret_arn" {
  value = aws_secretsmanager_secret.jwt_secret.arn
}

output "internal_api_token_arn" {
  value = aws_secretsmanager_secret.internal_api_token.arn
}

output "anthropic_api_key_arn" {
  description = "Null unless create_anthropic_api_key_secret = true."
  value       = try(aws_secretsmanager_secret.anthropic_api_key[0].arn, null)
}
