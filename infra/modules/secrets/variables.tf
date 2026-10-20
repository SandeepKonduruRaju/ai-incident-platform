variable "name_prefix" {
  description = "Secret name prefix, e.g. ai-incident-platform/demo."
  type        = string
}

variable "create_anthropic_api_key_secret" {
  description = "Create the (empty) ANTHROPIC_API_KEY secret, for LLM_PROVIDER=anthropic."
  type        = bool
  default     = false
}

variable "recovery_window_in_days" {
  description = "0 = delete immediately on destroy, so the same names can be recreated (demo). Production: 7-30."
  type        = number
  default     = 0
}

variable "jwt_secret_version" {
  description = "Increment to generate and store a new JWT signing key."
  type        = number
  default     = 1
}

variable "internal_api_token_version" {
  description = "Increment to generate and store a new internal API token."
  type        = number
  default     = 1
}
