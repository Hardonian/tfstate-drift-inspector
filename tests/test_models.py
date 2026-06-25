"""Tests for database models."""

import pytest
from datetime import datetime, timezone

from drift_inspector.config import Settings
from drift_inspector.models import Database, DriftScan
from drift_inspector.engine import DriftResult, DriftItem, DriftType, Severity


@pytest.fixture
def db():
    """Create a fresh in-memory database for each test."""
    settings = Settings(database_url="sqlite:///:memory:")
    database = Database(settings)
    database.create_tables()
    return database


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


class TestDatabase:

    def test_create_tables(self, db):
        """Tables should be created without error."""
        # If we get here, tables were created successfully
        assert db.engine is not None

    def test_record_scan(self, db, sample_result):
        """Recording a scan should return a scan ID."""
        scan_id = db.record_scan(sample_result)
        assert scan_id > 0

    def test_record_scan_persists_items(self, db, sample_result):
        """Drift items should be persisted with the scan."""
        scan_id = db.record_scan(sample_result)
        items = db.get_scan_items(scan_id)
        assert len(items) == 2

    def test_get_recent_scans(self, db, sample_result):
        """Recent scans should include recorded scan."""
        db.record_scan(sample_result)
        scans = db.get_recent_scans(limit=10)
        assert len(scans) == 1
        assert scans[0]["workspace_name"] == "test-workspace"

    def test_get_recent_scans_with_workspace_filter(self, db, sample_result):
        """Filter by workspace should work."""
        db.record_scan(sample_result)
        scans = db.get_recent_scans(workspace_name="test-workspace")
        assert len(scans) == 1

        scans = db.get_recent_scans(workspace_name="nonexistent")
        assert len(scans) == 0

    def test_get_workspace_stats(self, db, sample_result):
        """Stats should aggregate correctly."""
        db.record_scan(sample_result)
        stats = db.get_workspace_stats(days=7)
        assert stats["total_scans"] == 1
        assert stats["scans_with_drift"] == 1
        assert stats["total_items"] == 2
        assert stats["total_critical"] == 1

    def test_multiple_scans(self, db):
        """Multiple scans should accumulate."""
        result1 = DriftResult(
            workspace_name="ws1",
            workspace_id="1",
            scanned_at=datetime.now(timezone.utc),
            has_drift=True,
            drift_items=[
                DriftItem(
                    address="a.b",
                    drift_type=DriftType.RESOURCE_ADDED,
                    severity=Severity.HIGH,
                    planned_action="create",
                ),
            ],
        )
        result2 = DriftResult(
            workspace_name="ws2",
            workspace_id="2",
            scanned_at=datetime.now(timezone.utc),
            has_drift=False,
            drift_items=[],
        )
        db.record_scan(result1)
        db.record_scan(result2)

        stats = db.get_workspace_stats(days=7)
        assert stats["total_scans"] == 2
        assert stats["scans_with_drift"] == 1