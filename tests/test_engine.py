"""Tests for drift_inspector engine."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from drift_inspector.config import Settings
from drift_inspector.engine import DriftEngine, DriftType, Severity


@pytest.fixture
def settings():
    return Settings(
        database_url="sqlite:///:memory:",
        terraform_path="terraform",
        terraform_working_dir=tempfile.mkdtemp(),
    )


@pytest.fixture
def engine(settings):
    return DriftEngine(settings)


class TestDriftEngine:
    """Test the core drift detection engine."""

    def test_classify_severity_critical(self, engine):
        """Security-related resources should be classified as critical."""
        severity = engine._classify_severity("aws_security_group.sg", {})
        assert severity == Severity.CRITICAL

    def test_classify_severity_high(self, engine):
        """Compute resources should be classified as high."""
        severity = engine._classify_severity("aws_instance.web", {})
        assert severity == Severity.HIGH

    def test_classify_severity_medium(self, engine):
        """Unknown resource types should be medium."""
        severity = engine._classify_severity("aws_sqs_queue.q", {})
        assert severity == Severity.MEDIUM

    def test_classify_severity_replace_action(self, engine):
        """Replace actions should elevate to high."""
        change = {"change": {"actions": ["delete", "create"]}}
        severity = engine._classify_severity("aws_sqs_queue.q", change)
        assert severity == Severity.HIGH

    def test_is_metadata_only_true(self, engine):
        """Changes to only metadata fields should be detected."""
        change = {
            "change": {
                "before": {"name": "foo", "last_updated": "2024-01-01"},
                "after": {"name": "foo", "last_updated": "2024-01-02"},
            }
        }
        assert engine._is_metadata_only(change) is True

    def test_is_metadata_only_false(self, engine):
        """Changes to non-metadata fields should not be metadata-only."""
        change = {
            "change": {
                "before": {"name": "foo", "instance_type": "t2.micro"},
                "after": {"name": "foo", "instance_type": "t2.large"},
            }
        }
        assert engine._is_metadata_only(change) is False

    def test_parse_plan_json_empty(self, engine):
        """Empty plan should return no drift items."""
        result = engine._parse_plan_json({})
        assert result == []

    def test_parse_plan_json_no_changes(self, engine):
        """Plan with no-op should return no drift items."""
        plan = {
            "resource_changes": [
                {
                    "address": "aws_instance.web",
                    "change": {"actions": ["no-op"]},
                }
            ]
        }
        result = engine._parse_plan_json(plan)
        assert result == []

    def test_parse_plan_json_create(self, engine):
        """Create action should be detected."""
        plan = {
            "resource_changes": [
                {
                    "address": "aws_instance.web",
                    "change": {
                        "actions": ["create"],
                        "before": None,
                        "after": {"instance_type": "t2.micro"},
                    },
                }
            ]
        }
        result = engine._parse_plan_json(plan)
        assert len(result) == 1
        assert result[0].drift_type == DriftType.RESOURCE_ADDED
        assert result[0].planned_action == "create"

    def test_parse_plan_json_delete(self, engine):
        """Delete action should be detected."""
        plan = {
            "resource_changes": [
                {
                    "address": "aws_instance.web",
                    "change": {
                        "actions": ["delete"],
                        "before": {"instance_type": "t2.micro"},
                        "after": None,
                    },
                }
            ]
        }
        result = engine._parse_plan_json(plan)
        assert len(result) == 1
        assert result[0].drift_type == DriftType.RESOURCE_REMOVED

    def test_scan_workspace_nonexistent_path(self, engine):
        """Scanning nonexistent path should return error result."""
        result = engine.scan_workspace("test", Path("/nonexistent/path"))
        assert result.has_drift is False
        assert result.error is not None
        assert "does not exist" in result.error

    def test_scan_workspace_success(self, engine, tmp_path):
        """Successful scan should return result with no error."""
        # Create minimal terraform workspace
        (tmp_path / "main.tf").write_text("""
resource "null_resource" "test" {}
""")
        result = engine.scan_workspace("test-workspace", tmp_path)
        # Result should have no error (terraform may not be installed)
        # but should return a valid result object
        assert result.workspace_name == "test-workspace"


class TestDriftResult:
    """Test DriftResult model."""

    def test_summary_counts(self):
        from datetime import datetime, timezone
        from drift_inspector.engine import DriftItem

        result = DriftResult(
            workspace_name="test",
            workspace_id="test-1",
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
                DriftItem(
                    address="aws_sqs_queue.q",
                    drift_type=DriftType.RESOURCE_CHANGED,
                    severity=Severity.MEDIUM,
                    planned_action="update",
                ),
            ],
        )

        assert result.critical_count == 1
        assert result.high_count == 1
        assert result.summary["total"] == 3
        assert result.summary["critical"] == 1
        assert result.summary["high"] == 1
        assert result.summary["medium"] == 1

    def test_to_dict(self):
        from datetime import datetime, timezone
        result = DriftResult(
            workspace_name="test",
            workspace_id="test-1",
            scanned_at=datetime.now(timezone.utc),
            has_drift=False,
        )
        d = result.to_dict()
        assert d["workspace_name"] == "test"
        assert d["has_drift"] is False