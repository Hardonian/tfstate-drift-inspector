# Variables

variable "app_name" {
  description = "Fly.io app name"
  type        = string
  default     = "tfstate-drift-inspector"
}

variable "region" {
  description = "Fly.io region"
  type        = string
  default     = "iad"
}

variable "environment" {
  description = "Environment (staging, production)"
  type        = string
  default     = "production"
}

variable "image" {
  description = "Docker image"
  type        = string
  default     = "ghcr.io/hardonian/tfstate-drift-inspector"
}

variable "image_tag" {
  description = "Docker image tag"
  type        = string
  default     = "latest"
}

variable "github_app_id" {
  description = "GitHub App ID"
  type        = string
}

variable "github_private_key" {
  description = "GitHub App private key (PEM)"
  type        = string
  sensitive   = true
}

variable "github_client_id" {
  description = "GitHub OAuth Client ID"
  type        = string
  default     = ""
}

variable "github_client_secret" {
  description = "GitHub OAuth Client Secret"
  type        = string
  sensitive   = true
  default     = ""
}

variable "slack_bot_token" {
  description = "Slack Bot User OAuth Token"
  type        = string
  sensitive   = true
  default     = ""
}

variable "slack_default_channel" {
  description = "Default Slack channel for alerts"
  type        = string
  default     = "#devops-alerts"
}

variable "stripe_secret_key" {
  description = "Stripe Secret Key"
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_price_id_monthly" {
  description = "Stripe Price ID for monthly plan"
  type        = string
  default     = ""
}

variable "scan_cron" {
  description = "Cron schedule for nightly scans"
  type        = string
  default     = "0 2 * * *"
}

variable "log_level" {
  description = "Log level"
  type        = string
  default     = "INFO"
}