variable "name" {
  description = "Workload name (container name, Cloud Map name, ECS service name)."
  type        = string
}

variable "name_prefix" {
  description = "Prefix for the task definition family, IAM roles and log group."
  type        = string
}

variable "iam_path" {
  description = "IAM path of the roles (the deploy roles may only PassRole roles under this path)."
  type        = string
}

variable "image" {
  description = "Full image reference, e.g. <account>.dkr.ecr.<region>.amazonaws.com/incident-service:<git sha>."
  type        = string
}

variable "ecr_repository_arn" {
  description = "ECR repository the execution role may pull from (null for public Docker Hub images)."
  type        = string
  default     = null
}

variable "cpu" {
  description = "Fargate task CPU units (256 = 0.25 vCPU)."
  type        = number
}

variable "memory" {
  description = "Fargate task memory in MiB (must be valid for the CPU size)."
  type        = number
}

variable "command" {
  description = "Container command override (null = the image's CMD)."
  type        = list(string)
  default     = null
}

variable "container_ports" {
  description = "Container ports; the first one is registered with the target group."
  type        = list(number)
  default     = []
}

variable "environment" {
  description = "Non-secret environment variables."
  type        = map(string)
  default     = {}
}

variable "secrets" {
  description = "Environment variable name -> Secrets Manager reference (secret ARN, or ARN:json-key:: for one key)."
  type        = map(string)
  default     = {}
}

variable "readonly_root_filesystem" {
  description = "Read-only root filesystem with a writable /tmp volume."
  type        = bool
  default     = true
}

variable "health_check_command" {
  description = "Container health check (CMD-SHELL), or null."
  type        = string
  default     = null
}

variable "health_check_start_period" {
  description = "Seconds before failed container health checks count (startup time)."
  type        = number
  default     = 120
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention."
  type        = number
  default     = 7
}

variable "create_service" {
  description = "false = task definition only (one-off tasks started with aws ecs run-task)."
  type        = bool
  default     = true
}

variable "cluster_arn" {
  description = "ECS cluster of the service."
  type        = string
  default     = null
}

variable "desired_count" {
  description = "Number of running tasks."
  type        = number
  default     = 1
}

variable "deployment_minimum_healthy_percent" {
  description = "100 = start the new task before stopping the old one (zero downtime); 0 for single-replica stateful tasks."
  type        = number
  default     = 100
}

variable "subnet_ids" {
  description = "Subnets of the tasks."
  type        = list(string)
  default     = []
}

variable "security_group_ids" {
  description = "Security groups of the tasks."
  type        = list(string)
  default     = []
}

variable "assign_public_ip" {
  description = "Public IP for outbound internet access when there is no NAT gateway."
  type        = bool
  default     = false
}

variable "service_discovery_namespace_id" {
  description = "Cloud Map namespace to register the service in (null = not registered)."
  type        = string
  default     = null
}

variable "target_group_arn" {
  description = "ALB target group for the first container port (null = no load balancer)."
  type        = string
  default     = null
}

variable "health_check_grace_period" {
  description = "Seconds the ALB health check is ignored after a task starts."
  type        = number
  default     = 180
}
