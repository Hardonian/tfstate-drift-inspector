"""Tests for configuration."""

import os
import pytest
from pathlib import Path


class TestSettings:

    def test_default_database_url(self, monkeypatch):
        """Default database should be SQLite."""
        from drift_inspector.config import Settings
        monkeypatch.delenv("DATABASE_URL", raising=False)
        settings = Settings()
        assert "sqlite" in settings.database_url

    def test_github_app_id_from_env(self, monkeypatch):
        """Should load GITHUB_APP_ID from environment."""
        from drift_inspector.config import Settings
        monkeypatch.setenv("GITHUB_APP_ID", "12345")
        settings = Settings()
        assert settings.github_app_id == "12345"

    def test_slack_token_from_env(self, monkeypatch):
        """Should load SLACK_BOT_TOKEN from environment."""
        from drift_inspector.config import Settings
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        settings = Settings()
        assert settings.slack_bot_token == "xoxb-test"

    def test_terraform_path_default(self, monkeypatch):
        """Default terraform path should be 'terraform'."""
        from drift_inspector.config import Settings
        monkeypatch.delenv("TERRAFORM_PATH", raising=False)
        settings = Settings()
        assert settings.terraform_path == "terraform"

    def test_alert_email_list_empty(self, monkeypatch):
        """Empty email list should return empty list."""
        from drift_inspector.config import Settings
        monkeypatch.setenv("ALERT_TO_EMAILS", "")
        settings = Settings()
        assert settings.alert_email_list == []

    def test_alert_email_list_multiple(self, monkeypatch):
        """Multiple emails should be parsed."""
        from drift_inspector.config import Settings
        monkeypatch.setenv("ALERT_TO_EMAILS", "a@b.com, c@d.com")
        settings = Settings()
        assert settings.alert_email_list == ["a@b.com", "c@d.com"]

    def test_get_settings_singleton(self, monkeypatch):
        """get_settings should return same instance."""
        from drift_inspector.config import get_settings
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2