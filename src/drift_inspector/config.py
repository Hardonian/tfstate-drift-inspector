"""Configuration management for tfstate-drift-inspector."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = Field(
        default="sqlite:///./drift_inspector.db",
        description="SQLAlchemy database URL",
    )

    # GitHub App
    github_app_id: str | None = Field(
        default=None,
        description="GitHub App ID for installation authentication",
    )
    github_app_private_key: str | None = Field(
        default=None,
        description="GitHub App private key (PEM format)",
    )
    github_webhook_secret: str | None = Field(
        default=None,
        description="GitHub webhook secret for validation",
    )

    # GitHub OAuth (for user installations)
    github_client_id: str | None = Field(default=None)
    github_client_secret: str | None = Field(default=None)

    # Slack
    slack_bot_token: str | None = Field(
        default=None,
        description="Slack Bot User OAuth Token (xoxb-)",
    )
    slack_signing_secret: str | None = Field(default=None)
    slack_default_channel: str = Field(
        default="#devops-alerts",
        description="Default Slack channel for drift alerts",
    )

    # Email (SendGrid/SES)
    sendgrid_api_key: str | None = Field(default=None)
    alert_from_email: str = Field(default="drift-inspector@yourdomain.com")
    alert_to_emails: str = Field(default="", description="Comma-separated list")

    # Terraform
    terraform_path: str = Field(
        default="terraform",
        description="Path to terraform binary",
    )
    terraform_working_dir: str = Field(
        default="/tmp/tf-drift-workspaces",
        description="Working directory for terraform operations",
    )

    # Scheduling
    scan_cron: str = Field(
        default="0 2 * * *",
        description="Cron expression for nightly scan (UTC)",
    )

    # Application
    log_level: str = Field(default="INFO")
    environment: str = Field(default="development")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080)

    # Stripe
    stripe_secret_key: str | None = Field(default=None)
    stripe_webhook_secret: str | None = Field(default=None)
    stripe_price_id_monthly: str | None = Field(default=None)

    @property
    def alert_email_list(self) -> list[str]:
        return [e.strip() for e in self.alert_to_emails.split(",") if e.strip()]


_settings: Settings | None = None


def get_settings() -> Settings:
    """Get cached settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
