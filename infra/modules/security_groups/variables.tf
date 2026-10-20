variable "name" {
  description = "Name prefix for the security groups."
  type        = string
}

variable "vpc_id" {
  description = "VPC the security groups belong to."
  type        = string
}

variable "enable_https" {
  description = "Open 443 on the ALB (true when an ACM certificate is configured)."
  type        = bool
  default     = false
}
