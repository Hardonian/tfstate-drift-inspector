# Main infrastructure resources

# ── Fly.io App ────────────────────────────────────────────────────
resource "null_resource" "fly_app" {
  triggers = {
    app_name = var.app_name
    region   = var.region
  }

  provisioner "local-exec" {
    command = "fly apps create ${var.app_name} --region ${var.region} || echo 'App may already exist'"
    on_failure = continue
  }

  provisioner "local-exec" {
    when    = destroy
    command = "fly apps destroy -y ${self.triggers.app_name} || true"
    on_failure = continue
  }
}

# ── Environment Variables ─────────────────────────────────────────
resource "null_resource" "fly_secrets" {
  triggers = {
    app_name = var.app_name
  }

  provisioner "local-exec" {
    command = <<-EOT
      fly secrets set -a ${var.app_name} \
        ENVIRONMENT=${var.environment} \
        GITHUB_APP_ID=${var.github_app_id} \
        SLACK_BOT_TOKEN=${var.slack_bot_token} \
        SLACK_DEFAULT_CHANNEL=${var.slack_default_channel} \
        LOG_LEVEL=${var.log_level} \
        SCAN_CRON=${var.scan_cron}
    EOT
    on_failure = continue
  }

  depends_on = [null_resource.fly_app]
}

# ── Deploy (triggered by image changes) ──────────────────────────
resource "null_resource" "fly_deploy" {
  triggers = {
    app_name = var.app_name
    image    = "${var.image}:${var.image_tag}"
  }

  provisioner "local-exec" {
    command = "fly deploy -a ${var.app_name} --remote-only --image ${var.image}:${var.image_tag}"
  }

  depends_on = [null_resource.fly_app, null_resource.fly_secrets]
}

# ── Outputs ──────────────────────────────────────────────────────
output "app_url" {
  value = "https://${var.app_name}.fly.dev"
}

output "api_endpoint" {
  value = "https://${var.app_name}.fly.dev/api/v1"
}

output "app_name" {
  value = var.app_name
}