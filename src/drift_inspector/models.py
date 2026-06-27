"""Database models and persistence for drift history."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from drift_inspector.config import get_settings

Base = declarative_base()


class Workspace(Base):
    """Tracked Terraform workspace."""
    __tablename__ = "workspaces"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    repo_full_name = Column(String(512))
    repo_url = Column(String(1024))
    branch = Column(String(255), default="main")
    path = Column(String(1024))
    installation_id = Column(Integer)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    __table_args__ = (
        Index("idx_workspace_name", "name"),
        Index("idx_workspace_active", "is_active"),
    )


class DriftScan(Base):
    """A drift scan run."""
    __tablename__ = "drift_scans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, nullable=False)
    workspace_name = Column(String(255), nullable=False)
    scanned_at = Column(DateTime(timezone=True), nullable=False)
    has_drift = Column(Boolean, default=False)
    total_items = Column(Integer, default=0)
    critical_count = Column(Integer, default=0)
    high_count = Column(Integer, default=0)
    medium_count = Column(Integer, default=0)
    low_count = Column(Integer, default=0)
    error = Column(Text)
    terraform_version = Column(String(50))
    plan_exit_code = Column(Integer)
    duration_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    __table_args__ = (
        Index("idx_scan_workspace", "workspace_id"),
        Index("idx_scan_date", "scanned_at"),
        Index("idx_scan_drift", "has_drift"),
    )


class DriftItemRecord(Base):
    """Individual drift item from a scan."""
    __tablename__ = "drift_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(Integer, nullable=False)
    address = Column(String(512), nullable=False)
    drift_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False)
    planned_action = Column(String(20), nullable=False)
    detail = Column(JSON)
    raw_change = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    __table_args__ = (
        Index("idx_item_scan", "scan_id"),
        Index("idx_item_severity", "severity"),
    )


class RemediationPR(Base):
    """Remediation PR created for drift."""
    __tablename__ = "remediation_prs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(Integer, nullable=False)
    workspace_name = Column(String(255), nullable=False)
    repo_full_name = Column(String(512))
    pr_number = Column(Integer)
    pr_url = Column(String(1024))
    branch_name = Column(String(255))
    status = Column(String(50), default="open")  # open, merged, closed, superseded
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class Database:
    """Database connection and session management."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.engine = create_engine(
            self.settings.database_url,
            echo=False,
            pool_pre_ping=True,
        )
        self.SessionLocal = sessionmaker(bind=self.engine)

    def create_tables(self):
        """Create all tables."""
        Base.metadata.create_all(self.engine)

    def drop_tables(self):
        """Drop all tables."""
        Base.metadata.drop_all(self.engine)

    def get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionLocal()

    def record_scan(self, result, duration_ms: int = 0) -> int:
        """Record a drift scan result. Returns scan ID."""
        session = self.get_session()
        try:
            # Get or create workspace
            workspace = session.query(Workspace).filter(Workspace.name == result.workspace_name).first()
            if not workspace:
                workspace = Workspace(
                    name=result.workspace_name,
                    path=str(getattr(result, 'workspace_path', '')),
                )
                session.add(workspace)
                session.flush()

            scan = DriftScan(
                workspace_id=workspace.id,
                workspace_name=result.workspace_name,
                scanned_at=result.scanned_at,
                has_drift=result.has_drift,
                total_items=result.summary["total"],
                critical_count=result.critical_count,
                high_count=result.high_count,
                medium_count=result.summary["medium"],
                low_count=result.summary["low"],
                error=result.error,
                terraform_version=result.terraform_version,
                plan_exit_code=result.plan_exit_code,
                duration_ms=duration_ms,
            )
            session.add(scan)
            session.flush()

            for item in result.drift_items:
                record = DriftItemRecord(
                    scan_id=scan.id,
                    address=item.address,
                    drift_type=item.drift_type,
                    severity=item.severity,
                    planned_action=item.planned_action,
                    detail=item.detail,
                    raw_change=item.raw_change,
                )
                session.add(record)

            session.commit()
            return scan.id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_recent_scans(self, limit: int = 30, workspace_name: str | None = None) -> list[dict]:
        """Get recent scan results."""
        session = self.get_session()
        try:
            query = session.query(DriftScan).order_by(DriftScan.scanned_at.desc())
            if workspace_name:
                query = query.filter(DriftScan.workspace_name == workspace_name)
            scans = query.limit(limit).all()
            return [
                {
                    "id": s.id,
                    "workspace_name": s.workspace_name,
                    "scanned_at": s.scanned_at.isoformat(),
                    "has_drift": s.has_drift,
                    "total_items": s.total_items,
                    "critical_count": s.critical_count,
                    "high_count": s.high_count,
                    "error": s.error,
                    "duration_ms": s.duration_ms,
                }
                for s in scans
            ]
        finally:
            session.close()

    def get_scan_items(self, scan_id: int) -> list[dict]:
        """Get drift items for a specific scan."""
        session = self.get_session()
        try:
            items = session.query(DriftItemRecord).filter(DriftItemRecord.scan_id == scan_id).all()
            return [
                {
                    "address": i.address,
                    "drift_type": i.drift_type,
                    "severity": i.severity,
                    "planned_action": i.planned_action,
                    "detail": i.detail,
                }
                for i in items
            ]
        finally:
            session.close()

    def get_workspace_stats(self, days: int = 7) -> dict[str, Any]:
        """Get aggregate stats for all workspaces."""
        from datetime import timedelta
        session = self.get_session()
        try:
            cutoff = datetime.now(UTC) - timedelta(days=days)
            scans = session.query(DriftScan).filter(DriftScan.scanned_at >= cutoff).all()

            total_scans = len(scans)
            scans_with_drift = sum(1 for s in scans if s.has_drift)
            total_items = sum(s.total_items for s in scans)
            total_critical = sum(s.critical_count for s in scans)

            return {
                "period_days": days,
                "total_scans": total_scans,
                "scans_with_drift": scans_with_drift,
                "total_items": total_items,
                "total_critical": total_critical,
                "avg_items_per_scan": round(total_items / total_scans, 1) if total_scans else 0,
            }
        finally:
            session.close()
