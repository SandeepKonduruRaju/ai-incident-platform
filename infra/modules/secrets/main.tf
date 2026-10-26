# Application secrets in Secrets Manager, injected into the ECS tasks by the task execution role (never as plain
# environment variables in the task definition).
#
# JWT_SECRET and INTERNAL_API_TOKEN are generated with EPHEMERAL random values and written through write-only
# arguments (secret_string_wo): they exist in Secrets Manager only, never in the Terraform plan or state.
# Bump *_version to rotate. ANTHROPIC_API_KEY is only an empty container: put the value in yourself
# (aws secretsmanager put-secret-value ...), so it never passes through Terraform at all.

ephemeral "random_password" "jwt_secret" {
  length  = 64
  special = false
}

ephemeral "random_password" "internal_api_token" {
  length  = 48
  special = false
}

#trivy:ignore:AVD-AWS-0098 Encrypted with the AWS-managed Secrets Manager key instead of a customer-managed KMS key (demo cost).
resource "aws_secretsmanager_secret" "jwt_secret" {
  name                    = "${var.name_prefix}/jwt-secret"
  description             = "incident-service: HS256 signing key for JWTs"
  recovery_window_in_days = var.recovery_window_in_days
}

resource "aws_secretsmanager_secret_version" "jwt_secret" {
  secret_id                = aws_secretsmanager_secret.jwt_secret.id
  secret_string_wo         = ephemeral.random_password.jwt_secret.result
  secret_string_wo_version = var.jwt_secret_version
}

#trivy:ignore:AVD-AWS-0098 Encrypted with the AWS-managed Secrets Manager key instead of a customer-managed KMS key (demo cost).
resource "aws_secretsmanager_secret" "internal_api_token" {
  name                    = "${var.name_prefix}/internal-api-token"
  description             = "Shared secret between incident-service and investigation-worker (X-Internal-Token)"
  recovery_window_in_days = var.recovery_window_in_days
}

resource "aws_secretsmanager_secret_version" "internal_api_token" {
  secret_id                = aws_secretsmanager_secret.internal_api_token.id
  secret_string_wo         = ephemeral.random_password.internal_api_token.result
  secret_string_wo_version = var.internal_api_token_version
}

#trivy:ignore:AVD-AWS-0098 Encrypted with the AWS-managed Secrets Manager key instead of a customer-managed KMS key (demo cost).
resource "aws_secretsmanager_secret" "anthropic_api_key" {
  count = var.create_anthropic_api_key_secret ? 1 : 0

  name                    = "${var.name_prefix}/anthropic-api-key"
  description             = "investigation-worker: Claude API key. Value set by the operator, never by Terraform."
  recovery_window_in_days = var.recovery_window_in_days
}
