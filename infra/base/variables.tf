variable "region" {
  description = "AWS region. us-east-1 is next to the demo Supabase project, which every agent turn calls several times."
  type        = string
  default     = "us-east-1"
}

variable "name" {
  description = "Prefix for every resource name. infra/app must use the same value."
  type        = string
  default     = "support-agent"
}

variable "github_repo" {
  description = "The repository whose main branch may push images and redeploy, as GitHub's OIDC token names it: owner@owner_id/name@repo_id (see repos/<owner>/<repo>/actions/oidc/customization/sub)."
  type        = string
  default     = "SampooranP@98943576/support-agent@1441825424"
}

variable "create_github_oidc_provider" {
  description = "Create GitHub's OIDC provider in this account. Set false if the account already has one (only one is allowed)."
  type        = bool
  default     = true
}

variable "secret_keys" {
  description = "The keys the API secret must hold (for the description and infra/app's task definition)."
  type        = list(string)
  default     = ["ANTHROPIC_API_KEY", "VOYAGE_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "AGENT_API_SECRET"]
}
