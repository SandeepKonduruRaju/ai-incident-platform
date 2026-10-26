variable "name" {
  description = "Name prefix for the VPC and its resources."
  type        = string
}

variable "cidr_block" {
  description = "VPC CIDR. Subnets are /24s carved from it (public 0..n, private 10..n)."
  type        = string
  default     = "10.40.0.0/16"
}

variable "az_count" {
  description = "Number of Availability Zones (one public and one private subnet each)."
  type        = number
  default     = 2

  validation {
    condition     = var.az_count >= 2 && var.az_count <= 3
    error_message = "az_count must be 2 or 3 (the ALB and the RDS subnet group need at least two AZs)."
  }
}

variable "enable_nat_gateway" {
  description = "One NAT gateway so tasks can run in private subnets. false = tasks in public subnets with public IPs (see main.tf)."
  type        = bool
  default     = false
}
