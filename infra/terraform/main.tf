# Main infrastructure resources

variable "fly_token" {}
variable "github_app_id" {}
variable "github_private_key" { sensitive = true }
variable "github_client_id" { default = "" }
variable "github_client_secret" { default = "" sensitive = true }
variable "slack_bot_token" { default = "" sensitive = true }
variable "slack_default_channel" { default = "#devops-alerts" }
variable "stripe_secret_key" { default = "" sensitive = true }
variable "stripe_price_id_monthly" { default = "" }
variable "app_name" { default = "tfstate-drift-inspector" }
variable "region" { default = "iad" }
variable "environment" { default = "production" }

provider "fly" {
  flytoken = var.fly_token
}

# ── Fly.io App ────────────────────────────────────────────────────
resource "fly_app" "drift_inspector" {
  name = var.app_name
  org  = "personal"
}

# ── PostgreSQL Database ───────────────────────────────────────────
resource "fly_volume" "pg_data" {
  name   = "pg_data"
  app    = fly_app.drift_inspector.name
  size   = 1  # 1GB
  region = var.region
}

resource "fly_postgres" "drift_db" {
  name       = "${var.app_name}-db"
  app        = fly_app.drift_inspector.name
  region     = var.region
  # Fly Postgres requires a separate cluster. Simplified here.
  # In production, use fly_postgres resource with a cluster:
  # See: https://registry.terraform.io/providers/fly-apps/fly/latest/docs/resources/postgres
}

# ── Machine (API Server) ─────────────────────────────────────────
resource "fly_machine" "api" {
  app    = fly_app.drift_inspector.name
  region = var.region
  name   = "${var.app_name}-api"

  image = "ghcr.io/yourorg/tfstate-drift-inspector:latest"

  cpus    = 1
  memorymb = 256

  env = {
    ENVIRONMENT          = var.environment
    DATABASE_URL         = fly_postgres.drift_db.connection_string
    GITHUB_APP_ID        = var.github_app_id
    GITHUB_APP_PRIVATE_KEY = var.github_private_key
    GITHUB_CLIENT_ID     = var.github_client_id
    GITHUB_CLIENT_SECRET = var.github_client_secret
    SLACK_BOT_TOKEN      = var.slack_bot_token
    SLACK_DEFAULT_CHANNEL = var.slack_default_channel
    STRIPE_SECRET_KEY    = var.stripe_secret_key
    STRIPE_PRICE_ID_MONTHLY = var.stripe_price_id_monthly
    SCAN_CRON            = "0 2 * * *"
    LOG_LEVEL            = "INFO"
  }

  services {
    internal_port = 8080
    protocol      = "tcp"

    ports {
      port     = 80
      handlers = ["http"]
    }

    ports {
      port     = 443
      handlers = ["tls", "http"]
    }

    force_instance_start = true
    min_machines_running = 1
    max_machines_running = 1
  }

  depends_on = [fly_app.drift_inspector]
}

# ── Scheduled Machine (Nightly Scan) ─────────────────────────────
resource "fly_machine" "scanner" {
  app    = fly_app.drift_inspector.name
  region = var.region
  name   = "${var.app_name}-scanner"

  image = "ghcr.io/yourorg/tfstate-drift-inspector:latest"

  cpus     = 1
  memorymb = 512

  env = {
    ENVIRONMENT          = var.environment
    DATABASE_URL         = fly_postgres.drift_db.connection_string
    GITHUB_APP_ID        = var.github_app_id
    GITHUB_APP_PRIVATE_KEY = var.github_private_key
    SLACK_BOT_TOKEN      = var.slack_bot_token
    SLACK_DEFAULT_CHANNEL = var.slack_default_channel
    SCAN_MODE            = "scheduled"
    SCAN_CRON            = "0 2 * * *"
  }

  # Use Fly's schedule to run only during scan window (saves cost)
  lifecycle {
    ignore_changes = [services]
  }

  depends_on = [fly_app.drift_inspector]
}

# ── Outputs ──────────────────────────────────────────────────────
output "app_url" {
  value = "https://${fly_app.drift_inspector.name}.fly.dev"
}

output "api_endpoint" {
  value = "https://${fly_app.drift_inspector.name}.fly.dev/api/v1"
}

output "app_name" {
  value = fly_app.drift_inspector.name
}

output "db_connection_string" {
  value     = fly_postgres.drift_db.connection_string
  sensitive = true
}