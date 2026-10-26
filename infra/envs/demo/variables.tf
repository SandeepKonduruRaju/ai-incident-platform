variable "region" {
  description = "AWS region (the same as infra/bootstrap)."
  type        = string
  default     = "eu-west-2"
}

variable "image_tag" {
  description = "Git commit SHA the images were built from (ECR tags are immutable); set by the deploy workflow."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{7,40}$", var.image_tag))
    error_message = "image_tag must be a git commit SHA (7-40 lowercase hex characters), never \"latest\"."
  }
}

variable "enable_nat_gateway" {
  description = "true = tasks in private subnets behind one NAT gateway (extra hourly cost). false = tasks in public subnets with public IPs, no inbound (see modules/network)."
  type        = bool
  default     = false
}

variable "certificate_arn" {
  description = "ACM certificate for HTTPS on the ALB. null = HTTP-only DEMO mode (traffic not encrypted)."
  type        = string
  default     = null
}

variable "kafka_mode" {
  description = "Kafka provisioning; only \"single-broker-fargate\" (demo) is implemented."
  type        = string
  default     = "single-broker-fargate"
}

variable "llm_provider" {
  description = "fake (no key, no cost) or anthropic (put the key into the ANTHROPIC_API_KEY secret first)."
  type        = string
  default     = "fake"

  validation {
    condition     = contains(["fake", "anthropic"], var.llm_provider)
    error_message = "llm_provider must be \"fake\" or \"anthropic\"."
  }
}

variable "spring_profiles_active" {
  description = "\"dev\" enables POST /api/v1/dev/token: ANYONE who can reach the ALB can then mint tokens. Only for a short, data-free demo; never with real data."
  type        = string
  default     = ""
}

variable "incident_service_desired_count" {
  description = "incident-service tasks."
  type        = number
  default     = 1
}

variable "worker_desired_count" {
  description = "investigation-worker tasks (at most 3 = the partitions of incident-events)."
  type        = number
  default     = 1

  validation {
    condition     = var.worker_desired_count >= 0 && var.worker_desired_count <= 3
    error_message = "worker_desired_count must be 0-3: more consumers than partitions would sit idle."
  }
}

variable "postgres_major_version" {
  description = "RDS PostgreSQL major version (compose uses 18; use 17 if 18 is not offered in the region yet)."
  type        = string
  default     = "18"
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for every task."
  type        = number
  default     = 7
}

variable "enable_redis" {
  description = "Create ElastiCache (one cache.t4g.micro Valkey node, about $0.3/day = $10/month EXTRA) for incident-service's investigation cache and per-tenant rate limit. false = both features off: the API works the same, every investigation read goes to the worker and incident creation is not rate limited."
  type        = bool
  default     = false
}
