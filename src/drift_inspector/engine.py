"""Core drift detection engine."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import structlog
from python_terraform import Terraform
from pydantic import BaseModel, Field

from drift_inspector.config import get_settings

logger = structlog.get_logger(__name__)


class DriftType(str):
    """Types of drift we can detect."""
    RESOURCE_ADDED = "resource_added"
    RESOURCE_REMOVED = "resource_removed"
    RESOURCE_CHANGED = "resource_changed"
    OUTPUT_CHANGED = "output_changed"
    METADATA_ONLY = "metadata_only"  # Ignored by default


class Severity(str):
    """Drift severity levels."""
    CRITICAL = "critical"    # Security group changes, IAM, data loss risk
    HIGH = "high"            # Compute changes, network config
    MEDIUM = "medium"        # Tags, labels, non-functional changes
    LOW = "low"              # Metadata, descriptions, output values


@dataclass
class DriftItem:
    """A single drift finding."""
    address: str
    drift_type: DriftType
    severity: Severity
    planned_action: str  # create, update, delete, replace
    detail: dict[str, Any] = field(default_factory=dict)
    raw_change: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "drift_type": self.drift_type,
            "severity": self.severity,
            "planned_action": self.planned_action,
            "detail": self.detail,
            "raw_change": self.raw_change,
        }


@dataclass
class DriftResult:
    """Result of a drift scan for one workspace."""
    workspace_name: str
    workspace_id: str
    scanned_at: datetime
    has_drift: bool
    drift_items: list[DriftItem] = field(default_factory=list)
    error: Optional[str] = None
    terraform_version: str = ""
    plan_exit_code: int = 0
    plan_output: str = ""

    @property
    def critical_count(self) -> int:
        return sum(1 for d in self.drift_items if d.severity == Severity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for d in self.drift_items if d.severity == Severity.HIGH)

    @property
    def summary(self) -> dict[str, int]:
        return {
            "critical": self.critical_count,
            "high": self.high_count,
            "medium": sum(1 for d in self.drift_items if d.severity == Severity.MEDIUM),
            "low": sum(1 for d in self.drift_items if d.severity == Severity.LOW),
            "total": len(self.drift_items),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_name": self.workspace_name,
            "workspace_id": self.workspace_id,
            "scanned_at": self.scanned_at.isoformat(),
            "has_drift": self.has_drift,
            "drift_items": [d.to_dict() for d in self.drift_items],
            "error": self.error,
            "terraform_version": self.terraform_version,
            "plan_exit_code": self.plan_exit_code,
            "summary": self.summary,
        }


class DriftEngine:
    """Main drift detection engine."""

    # Resource types that are security-critical
    CRITICAL_TYPES = {
        "aws_security_group",
        "aws_security_group_rule",
        "aws_iam_role",
        "aws_iam_policy",
        "aws_iam_role_policy_attachment",
        "aws_kms_key",
        "aws_s3_bucket_policy",
        "aws_db_instance",
        "aws_rds_cluster",
        "google_compute_firewall",
        "google_project_iam_binding",
        "google_service_account",
        "azurerm_network_security_group",
        "azurerm_role_assignment",
    }

    HIGH_TYPES = {
        "aws_instance",
        "aws_launch_template",
        "aws_autoscaling_group",
        "aws_lb",
        "aws_lb_target_group",
        "aws_route_table",
        "aws_vpc",
        "aws_subnet",
        "google_compute_instance",
        "google_compute_network",
        "google_compute_subnetwork",
        "azurerm_virtual_machine",
        "azurerm_virtual_network",
    }

    IGNORED_METADATA_FIELDS = {
        "last_updated",
        "timestamp",
        "id",
        "arn",
        "owner_id",
    }

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.working_dir = Path(self.settings.terraform_working_dir)
        self.working_dir.mkdir(parents=True, exist_ok=True)

    def _get_terraform(self, workspace_dir: Path) -> Terraform:
        """Create a Terraform instance for a workspace."""
        return Terraform(
            working_dir=str(workspace_dir),
            terraform_bin_path=self.settings.terraform_path,
            variables={},
            environment=os.environ.copy(),
        )

    def _run_terraform_version(self) -> str:
        """Get Terraform version."""
        try:
            result = subprocess.run(
                [self.settings.terraform_path, "version", "-json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return data.get("terraform_version", "unknown")
        except Exception as e:
            logger.warning("Failed to get terraform version", error=str(e))
        return "unknown"

    def _classify_severity(self, address: str, change: dict[str, Any]) -> Severity:
        """Classify drift severity based on resource type and change nature."""
        # Extract resource type from address (e.g., "aws_security_group.sg" -> "aws_security_group")
        parts = address.split(".")
        if len(parts) >= 2:
            resource_type = parts[0] + "_" + parts[1] if parts[0] in ("aws", "google", "azurerm") else parts[0]
        else:
            resource_type = address

        # Check critical types
        if resource_type in self.CRITICAL_TYPES:
            return Severity.CRITICAL
        if resource_type in self.HIGH_TYPES:
            return Severity.HIGH

        # Check if it's a replacement (destroy + create)
        actions = change.get("change", {}).get("actions", [])
        if "delete" in actions and "create" in actions:
            return Severity.HIGH

        return Severity.MEDIUM

    def _is_metadata_only(self, change: dict[str, Any]) -> bool:
        """Check if change is only metadata (tags, timestamps, etc.)."""
        after = change.get("change", {}).get("after", {})
        before = change.get("change", {}).get("before", {})

        if not isinstance(after, dict) or not isinstance(before, dict):
            return False

        # Get keys that actually changed
        all_keys = set(after.keys()) | set(before.keys())
        changed_keys = {k for k in all_keys if after.get(k) != before.get(k)}

        # If only metadata fields changed, it's metadata-only
        return changed_keys.issubset(self.IGNORED_METADATA_FIELDS)

    def _parse_plan_json(self, plan_json: dict[str, Any]) -> list[DriftItem]:
        """Parse Terraform plan JSON output into drift items."""
        drift_items = []

        resource_changes = plan_json.get("resource_changes", [])
        for change in resource_changes:
            address = change.get("address", "")
            change_type = change.get("change", {}).get("actions", ["no-op"])[0]

            if change_type == "no-op":
                continue

            # Skip metadata-only changes
            if self._is_metadata_only(change):
                drift_items.append(DriftItem(
                    address=address,
                    drift_type=DriftType.METADATA_ONLY,
                    severity=Severity.LOW,
                    planned_action="metadata_update",
                    detail={"note": "Only metadata fields changed (tags, timestamps)"},
                    raw_change=change,
                ))
                continue

            # Determine drift type
            if change_type == "create":
                drift_type = DriftType.RESOURCE_ADDED
            elif change_type == "delete":
                drift_type = DriftType.RESOURCE_REMOVED
            elif change_type == "update":
                drift_type = DriftType.RESOURCE_CHANGED
            elif change_type == "replace":
                drift_type = DriftType.RESOURCE_CHANGED
            else:
                drift_type = DriftType.RESOURCE_CHANGED

            severity = self._classify_severity(address, change)

            # Build detail
            before = change.get("change", {}).get("before", {})
            after = change.get("change", {}).get("after", {})
            detail = {
                "before_keys": list(before.keys()) if isinstance(before, dict) else [],
                "after_keys": list(after.keys()) if isinstance(after, dict) else [],
                "actions": change.get("change", {}).get("actions", []),
            }

            drift_items.append(DriftItem(
                address=address,
                drift_type=drift_type,
                severity=severity,
                planned_action=change_type,
                detail=detail,
                raw_change=change,
            ))

        return drift_items

    def scan_workspace(self, workspace_name: str, workspace_path: Path) -> DriftResult:
        """Scan a single Terraform workspace for drift."""
        start_time = time.time()
        scanned_at = datetime.now(timezone.utc)

        logger.info("Starting drift scan", workspace=workspace_name, path=str(workspace_path))

        if not workspace_path.exists():
            return DriftResult(
                workspace_name=workspace_name,
                workspace_id="",
                scanned_at=scanned_at,
                has_drift=False,
                error=f"Workspace path does not exist: {workspace_path}",
            )

        tf = self._get_terraform(workspace_path)

        # Get terraform version
        terraform_version = self._run_terraform_version()

        try:
            # Initialize if needed
            init_result = tf.init(capture_output=True)
            if init_result[0] != 0:
                return DriftResult(
                    workspace_name=workspace_name,
                    workspace_id="",
                    scanned_at=scanned_at,
                    has_drift=False,
                    error=f"Terraform init failed: {init_result[1]}",
                    terraform_version=terraform_version,
                )

            # Run plan with detailed exit code and JSON output
            # -detailed-exitcode: 0=no changes, 1=error, 2=changes present
            # -out=tfplan: save binary plan
            # -lock=false: don't wait for state lock (we're read-only)
            plan_result = tf.plan(
                no_color=True,
                detailed_exitcode=True,
                lock=False,
                capture_output=True,
                out="tfplan",
            )

            plan_exit_code = plan_result[0]
            plan_output = plan_result[1]

            # Also get JSON output for parsing
            show_result = tf.show("tfplan", json=True, capture_output=True)
            if show_result[0] != 0:
                logger.warning("terraform show -json failed", output=show_result[1])
                plan_json = {}
            else:
                try:
                    plan_json = json.loads(show_result[1])
                except json.JSONDecodeError as e:
                    logger.warning("Failed to parse terraform show JSON", error=str(e))
                    plan_json = {}

            # Parse drift
            drift_items = self._parse_plan_json(plan_json)

            # Filter out metadata-only by default
            significant_drift = [d for d in drift_items if d.drift_type != DriftType.METADATA_ONLY]
            has_drift = len(significant_drift) > 0

            logger.info(
                "Drift scan completed",
                workspace=workspace_name,
                has_drift=has_drift,
                drift_count=len(significant_drift),
                duration_ms=int((time.time() - start_time) * 1000),
            )

            return DriftResult(
                workspace_name=workspace_name,
                workspace_id=workspace_name,  # Could be enhanced with actual workspace ID
                scanned_at=scanned_at,
                has_drift=has_drift,
                drift_items=significant_drift,
                terraform_version=terraform_version,
                plan_exit_code=plan_exit_code,
                plan_output=plan_output,
            )

        except Exception as e:
            logger.error("Drift scan failed", workspace=workspace_name, error=str(e))
            return DriftResult(
                workspace_name=workspace_name,
                workspace_id="",
                scanned_at=scanned_at,
                has_drift=False,
                error=str(e),
                terraform_version=terraform_version,
            )

    def scan_all_workspaces(self, workspace_configs: list[dict[str, str]]) -> list[DriftResult]:
        """Scan multiple workspaces."""
        results = []
        for config in workspace_configs:
            name = config.get("name", "unknown")
            path = Path(config.get("path", ""))
            if path.exists():
                result = self.scan_workspace(name, path)
                results.append(result)
            else:
                logger.warning("Workspace path not found", name=name, path=str(path))
                results.append(DriftResult(
                    workspace_name=name,
                    workspace_id="",
                    scanned_at=datetime.now(timezone.utc),
                    has_drift=False,
                    error=f"Path not found: {path}",
                ))
        return results