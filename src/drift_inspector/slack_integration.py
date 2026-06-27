"""Slack integration for drift alerts and notifications."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from drift_inspector.config import get_settings
from drift_inspector.engine import DriftResult, Severity

logger = structlog.get_logger(__name__)


@dataclass
class SlackMessage:
    """Slack message payload."""
    channel: str
    text: str
    blocks: list[dict[str, Any]] | None = None
    thread_ts: str | None = None


class SlackClient:
    """Slack API client for sending drift alerts."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self._client: WebClient | None = None

    @property
    def client(self) -> WebClient:
        if self._client is None:
            if not self.settings.slack_bot_token:
                raise ValueError("Slack bot token not configured")
            self._client = WebClient(token=self.settings.slack_bot_token)
        return self._client

    def send_message(self, message: SlackMessage) -> dict[str, Any]:
        """Send a message to Slack."""
        try:
            response = self.client.chat_postMessage(
                channel=message.channel,
                text=message.text,
                blocks=message.blocks,
                thread_ts=message.thread_ts,
            )
            return {"ok": True, "ts": response["ts"], "channel": response["channel"]}
        except SlackApiError as e:
            logger.exception("Failed to send Slack message", error=str(e))
            return {"ok": False, "error": str(e)}

    def send_drift_alert(self, result: DriftResult, channel: str | None = None) -> dict[str, Any]:
        """Send a drift alert to Slack."""
        channel = channel or self.settings.slack_default_channel

        # Build summary text
        critical_high = result.critical_count + result.high_count
        has_critical_high = critical_high > 0

        # Main text (fallback for notifications)
        text = (
            f"{'🚨' if has_critical_high else '⚠️'} Drift detected in `{result.workspace_name}`: "
            f"{result.summary['total']} changes ({critical_high} critical/high)"
        )

        # Build blocks for rich formatting
        blocks = self._build_drift_blocks(result, has_critical_high)

        return self.send_message(SlackMessage(channel=channel, text=text, blocks=blocks))

    def _build_drift_blocks(self, result: DriftResult, has_critical_high: bool) -> list[dict[str, Any]]:
        """Build Slack Block Kit payload for drift alert."""
        blocks = []

        # Header
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{'🚨 Critical' if has_critical_high else '⚠️'} Drift Detected: {result.workspace_name}",
                "emoji": True,
            },
        })

        # Context
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"*Scanned:* {result.scanned_at.strftime('%Y-%m-%d %H:%M UTC')}"},
                {"type": "mrkdwn", "text": f"*Terraform:* {result.terraform_version}"},
                {"type": "mrkdwn", "text": f"*Total:* {result.summary['total']} changes"},
            ],
        })

        # Severity breakdown
        severity_fields = [
            {"type": "mrkdwn", "text": f"*🔴 Critical:*\n{result.summary['critical']}"},
            {"type": "mrkdwn", "text": f"*🟠 High:*\n{result.summary['high']}"},
            {"type": "mrkdwn", "text": f"*🟡 Medium:*\n{result.summary['medium']}"},
            {"type": "mrkdwn", "text": f"*🟢 Low:*\n{result.summary['low']}"},
        ]
        blocks.append({"type": "section", "fields": severity_fields})

        # Top drift items (max 5)
        if result.drift_items:
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Top Drift Items:*"},
            })

            for item in result.drift_items[:5]:
                severity_emoji = {
                    Severity.CRITICAL: "🔴",
                    Severity.HIGH: "🟠",
                    Severity.MEDIUM: "🟡",
                    Severity.LOW: "🟢",
                }.get(item.severity, "⚪")

                action_emoji = {
                    "create": "➕",
                    "update": "🔄",
                    "delete": "🗑️",
                    "replace": "🔁",
                }.get(item.planned_action, "❓")

                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{severity_emoji} `{item.address}`\n{action_emoji} {item.planned_action} • {item.drift_type}",
                    },
                })

        # Footer with actions
        blocks.extend([
            {"type": "divider"},
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": "Generated by *tfstate-drift-inspector* • "
                     "<https://github.com/yourorg/tfstate-drift-inspector|View Source>"},
                ],
            },
        ])

        return blocks

    def send_daily_digest(self, results: list[DriftResult], channel: str | None = None) -> dict[str, Any]:
        """Send a daily digest of all drift scans."""
        channel = channel or self.settings.slack_default_channel

        total_drift = sum(r.summary['total'] for r in results)
        total_critical = sum(r.critical_count for r in results)
        total_high = sum(r.high_count for r in results)
        workspaces_with_drift = sum(1 for r in results if r.has_drift)

        text = (
            f"📊 Daily Drift Digest: {workspaces_with_drift}/{len(results)} workspaces have drift "
            f"({total_critical} critical, {total_high} high, {total_drift} total)"
        )

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"📊 Daily Drift Digest — {datetime.now(UTC).strftime('%Y-%m-%d')}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Workspaces Scanned:*\n{len(results)}"},
                    {"type": "mrkdwn", "text": f"*Workspaces with Drift:*\n{workspaces_with_drift}"},
                    {"type": "mrkdwn", "text": f"*🔴 Critical:*\n{total_critical}"},
                    {"type": "mrkdwn", "text": f"*🟠 High:*\n{total_high}"},
                    {"type": "mrkdwn", "text": f"*🟡 Medium:*\n{sum(r.summary['medium'] for r in results)}"},
                    {"type": "mrkdwn", "text": f"*🟢 Low:*\n{sum(r.summary['low'] for r in results)}"},
                ],
            },
        ]

        # Add per-workspace summary
        if workspaces_with_drift > 0:
            blocks.append({"type": "divider"})
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Workspaces with Drift:*"}})

            for result in results:
                if result.has_drift:
                    blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"• `{result.workspace_name}`: {result.summary['total']} changes "
                                  f"({result.critical_count}🔴 {result.high_count}🟠)",
                        },
                    })

        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "Generated by *tfstate-drift-inspector*"},
            ],
        })

        return self.send_message(SlackMessage(channel=channel, text=text, blocks=blocks))

    def test_connection(self) -> dict[str, Any]:
        """Test Slack connection."""
        try:
            auth = self.client.auth_test()
            return {"ok": True, "user": auth["user"], "team": auth["team"]}
        except SlackApiError as e:
            return {"ok": False, "error": str(e)}
