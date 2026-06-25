# Provider configuration.

terraform {
  required_version = ">= 1.5.0"
}

# Fly.io does not have a public Terraform provider.
# We use null_resource with local-exec to drive flyctl directly.
# Before running: `fly auth login` and ensure flyctl is in PATH.