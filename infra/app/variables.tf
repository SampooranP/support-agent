variable "domain_name" {
  description = "A domain with a public hosted zone in Route 53 in this account, e.g. example.com."
  type        = string
}

variable "api_subdomain" {
  description = "The API is served at <api_subdomain>.<domain_name>."
  type        = string
  default     = "api"
}

variable "region" {
  type    = string
  default = "eu-west-1"
}

variable "name" {
  description = "Must match infra/base."
  type        = string
  default     = "support-agent"
}

variable "image_tag" {
  description = "The image tag to run. CI pushes :latest and :<git sha> on every deploy."
  type        = string
  default     = "latest"
}

variable "desired_count" {
  description = "0 or 1. Use 0 for the first apply, before any image has been pushed (infra/README.md)."
  type        = number
  default     = 1
  validation {
    condition     = contains([0, 1], var.desired_count)
    error_message = "The API keeps per-conversation state in memory, so it runs as at most one task."
  }
}

variable "cpu" {
  type    = number
  default = 256 # 0.25 vCPU: the work is waiting on Claude, not computing
}

variable "memory" {
  type    = number
  default = 512
}

variable "agent_model" {
  type    = string
  default = "claude-sonnet-5-5"
}

variable "router_model" {
  type    = string
  default = "claude-haiku-5-5"
}

variable "daily_spend_cap_usd" {
  type    = number
  default = 5
}

variable "secret_keys" {
  description = "Keys read from the infra/base secret into the container's environment. Every key must exist in the secret, or the task won't start."
  type        = list(string)
  default     = ["ANTHROPIC_API_KEY", "VOYAGE_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "AGENT_API_SECRET"]
}
