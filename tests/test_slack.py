"""Tests for Slack integration."""

import pytest
from unittest.mock import MagicMock, patch

from drift_inspector.config import Settings
from drift_inspector.slack_integration import SlackClient, SlackMessage
from drift_inspector.engine import DriftResult, DriftItem, DriftType, Severity
from datetime import datetime, timezone


@pytest.fixture
def settings():
    return Settings(
        database_url="sqlite:///:memory:",
        slack_bot_token="xoxb-test-token",
        slack_default_channel="#test",
    )


@pytest.fixture
def slack(settings):
    return SlackClient(settings)


@pytest.fixture
def sample_result():
    return DriftResult(
        workspace_name="test-workspace",
        workspace_id="ws-123",
        scanned_at=datetime.now(timezone.utc),
        has_drift=True,
        drift_items=[
            DriftItem(
                address="aws_security_group.sg",
                drift_type=DriftType.RESOURCE_CHANGED,
                severity=Severity.CRITICAL,
                planned_action="update",
            ),
            DriftItem(
                address="aws_instance.web",
                drift_type=DriftType.RESOURCE_ADDED,
                severity=Severity.HIGH,
                planned_action="create",
            ),
        ],
    )


class TestSlackClient:

    def test_build_drift_blocks_has_critical(self, slack, sample_result):
        """Blocks should include critical alert styling."""
        blocks = slack._build_drift_blocks(sample_result, has_critical_high=True)
        assert len(blocks) > 0
        # Header should contain the workspace name
        header = blocks[0]
        assert "test-workspace" in header["text"]["text"]

    def test_build_drift_blocks_no_drift(self, slack):
        """Non-drift result should produce minimal blocks."""
        result = DriftResult(
            workspace_name="clean",
            workspace_id="ws-456",
            scanned_at=datetime.now(timezone.utc),
            has_drift=False,
        )
        blocks = slack._build_drift_blocks(result, has_critical_high=False)
        assert len(blocks) > 0

    @patch("drift_inspector.slack_integration.WebClient")
    def test_send_message_success(self, mock_webclient, slack):
        """Successful message send should return ok."""
        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ts": "123.456", "channel": "#test"}
        slack._client = mock_client

        msg = SlackMessage(channel="#test", text="Hello")
        response = slack.send_message(msg)
        assert response["ok"] is True

    @patch("drift_inspector.slack_integration.WebClient")
    def test_send_drift_alert(self, mock_webclient_class, slack, sample_result):
        """Drift alert should call chat_postMessage."""
        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ts": "123.456", "channel": "#test"}
        mock_webclient_class.return_value = mock_client
        # Reset the cached client so it uses our mock
        slack._client = None

        slack.send_drift_alert(sample_result)
        mock_client.chat_postMessage.assert_called_once()

    @patch("drift_inspector.slack_integration.WebClient")
    def test_send_daily_digest(self, mock_webclient_class, slack, sample_result):
        """Daily digest should include all workspaces."""
        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ts": "123.456", "channel": "#test"}
        mock_webclient_class.return_value = mock_client
        # Reset the cached client so it uses our mock
        slack._client = None

        slack.send_daily_digest([sample_result])
        mock_client.chat_postMessage.assert_called_once()