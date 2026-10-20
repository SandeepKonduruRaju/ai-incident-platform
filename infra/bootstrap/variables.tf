variable "region" {
  description = "AWS region for the state bucket and the demo stack."
  type        = string
  default     = "eu-west-2"
}

variable "budget_alert_email" {
  description = "E-mail address for the budget alerts (confirm nothing: AWS Budgets e-mails directly)."
  type        = string
}

variable "monthly_budget_usd" {
  description = "Monthly cost budget in USD."
  type        = number
  default     = 5
}

variable "state_bucket_prefix" {
  description = "State bucket name prefix; the account id and region are appended to make it globally unique."
  type        = string
  default     = "ai-incident-platform-tfstate"
}

variable "github_repository" {
  description = "owner/repo allowed to assume the GitHub roles."
  type        = string
  default     = "SandeepKonduruRaju/ai-incident-platform"
}

variable "github_branch" {
  description = "The only branch whose workflows may assume the roles."
  type        = string
  default     = "main"
}

variable "cluster_name" {
  description = "ECS cluster name used by infra/envs/demo (scopes the deploy role's ECS permissions)."
  type        = string
  default     = "ai-incident-platform-demo"
}

variable "ecs_service_names" {
  description = "The ECS services the deploy role may update."
  type        = list(string)
  default     = ["incident-service", "investigation-worker"]
}

variable "ecr_repository_names" {
  description = "The ECR repositories the deploy role may push to."
  type        = list(string)
  default     = ["incident-service", "investigation-worker"]
}

variable "secrets_name_prefix" {
  description = "Secrets Manager name prefix of infra/envs/demo (scopes the terraform role)."
  type        = string
  default     = "ai-incident-platform/demo"
}
