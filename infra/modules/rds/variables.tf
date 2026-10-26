variable "name" {
  description = "Identifier prefix for the DB instance, subnet group and parameter group."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnets (at least two AZs) for the DB subnet group."
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group of the instance (5432 from the application tasks only)."
  type        = string
}

variable "engine_major_version" {
  description = "PostgreSQL major version (compose uses 18). Use 17 if 18 is not yet offered in the region."
  type        = string
  default     = "18"
}

variable "instance_class" {
  description = "Instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "allocated_storage_gb" {
  description = "gp3 storage size in GB."
  type        = number
  default     = 20
}

variable "db_name" {
  description = "Database created at launch."
  type        = string
  default     = "incident_platform"
}

variable "username" {
  description = "Master user name (its password is managed by RDS in Secrets Manager)."
  type        = string
  default     = "incident_app"
}

variable "backup_retention_days" {
  description = "Automated backup retention (1 = minimal, for the demo)."
  type        = number
  default     = 1
}

variable "deletion_protection" {
  description = "Demo: false. Production: true."
  type        = bool
  default     = false
}

variable "skip_final_snapshot" {
  description = "Demo: true. Production: false."
  type        = bool
  default     = true
}
