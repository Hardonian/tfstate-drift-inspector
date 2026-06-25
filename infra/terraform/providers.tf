# Provider configuration

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    fly = {
      source  = "fly-apps/fly"
      version = "~> 0.1.0"
    }
  }
}

provider "fly" {
  flytoken = var.fly_token
}