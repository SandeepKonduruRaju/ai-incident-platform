variable "repository_names" {
  description = "ECR repository names (one per image)."
  type        = list(string)
}

variable "keep_images" {
  description = "Number of images kept per repository; older ones are expired."
  type        = number
  default     = 10
}

variable "force_delete" {
  description = "Allow destroying repositories that still contain images (demo: true; production: false)."
  type        = bool
  default     = true
}
