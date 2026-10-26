variable "name" {
  description = "Load balancer name (max 32 characters)."
  type        = string
}

variable "vpc_id" {
  description = "VPC of the target group."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnets (two AZs)."
  type        = list(string)
}

variable "security_group_id" {
  description = "ALB security group."
  type        = string
}

variable "certificate_arn" {
  description = "ACM certificate for HTTPS. null = HTTP-only demo mode."
  type        = string
  default     = null
}

variable "target_port" {
  description = "incident-service container port."
  type        = number
  default     = 8080
}

variable "health_check_path" {
  description = "Target health check: the existing public health endpoint."
  type        = string
  default     = "/api/v1/health"
}
