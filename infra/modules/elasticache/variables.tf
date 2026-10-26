variable "name" {
  description = "Name of the replication group, subnet group and security group."
  type        = string
}

variable "vpc_id" {
  description = "VPC of the cache's security group."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnets for the cache subnet group."
  type        = list(string)
}

variable "client_security_group_ids" {
  description = "Security groups allowed to connect on 6379 (incident-service only)."
  type        = list(string)
}

variable "engine" {
  description = "\"valkey\" (default, cheaper nodes) or \"redis\"."
  type        = string
  default     = "valkey"

  validation {
    condition     = contains(["valkey", "redis"], var.engine)
    error_message = "engine must be \"valkey\" or \"redis\"."
  }
}

variable "engine_version" {
  description = "Engine version (major.minor)."
  type        = string
  default     = "8.0"
}

variable "parameter_group_name" {
  description = "Default parameter group matching engine_version (cluster mode disabled)."
  type        = string
  default     = "default.valkey8"
}

variable "node_type" {
  description = "Smallest burstable node: plenty for a cache of JSON documents and per-tenant counters."
  type        = string
  default     = "cache.t4g.micro"
}
