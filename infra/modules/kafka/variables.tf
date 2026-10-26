variable "kafka_mode" {
  description = "How Kafka is provided. Only \"single-broker-fargate\" (demo) is implemented; see main.tf for MSK/SQS."
  type        = string
  default     = "single-broker-fargate"

  validation {
    condition     = var.kafka_mode == "single-broker-fargate"
    error_message = "Only \"single-broker-fargate\" is implemented (MSK and SQS are documented alternatives)."
  }
}

variable "name_prefix" {
  description = "Prefix for task definition families, roles and log groups."
  type        = string
}

variable "iam_path" {
  description = "IAM path of the task roles."
  type        = string
}

variable "cluster_arn" {
  description = "ECS cluster."
  type        = string
}

variable "namespace_id" {
  description = "Cloud Map private DNS namespace id."
  type        = string
}

variable "namespace_name" {
  description = "Cloud Map namespace name (the broker is kafka.<namespace_name>)."
  type        = string
}

variable "subnet_ids" {
  description = "Task subnets."
  type        = list(string)
}

variable "security_group_id" {
  description = "Kafka security group (also used by the topics task)."
  type        = string
}

variable "assign_public_ip" {
  description = "Public IP for image pulls when there is no NAT gateway."
  type        = bool
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention."
  type        = number
  default     = 7
}
