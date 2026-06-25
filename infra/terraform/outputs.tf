# Outputs

output "app_url" {
  description = "URL of the deployed app"
  value       = "https://${var.app_name}.fly.dev"
}

output "api_endpoint" {
  description = "API endpoint"
  value       = "https://${var.app_name}.fly.dev/api/v1"
}

output "app_name" {
  description = "Fly.io app name"
  value       = fly_app.drift_inspector.name
}

output "db_connection_string" {
  description = "Database connection string (sensitive)"
  value       = fly_postgres.drift_db.connection_string
  sensitive   = true
}

output "github_app_url" {
  description = "GitHub App settings URL"
  value       = "https://github.com/settings/apps/${var.app_name}"
}