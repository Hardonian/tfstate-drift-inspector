#!/usr/bin/env python3
"""Daily drift scan for configured Terraform workspaces.

Uses workspaces.json for real scans. Falls back to workspaces.example.json only for
schema/demo validation and skips placeholder paths so cron does not create false OKs.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path("/home/scott/ai-workspace/repos/tfstate-drift-inspector")
OUTPUT_DIR = Path("/home/scott/ai-lab/reports/daily-drift")
REAL_CONFIG = REPO_ROOT / "workspaces.json"
EXAMPLE_CONFIG = REPO_ROOT / "workspaces.example.json"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(REPO_ROOT / "src"))

from drift_inspector.engine import DriftEngine  # noqa: E402
from drift_inspector.slack_integration import SlackClient  # noqa: E402


def _load_config() -> tuple[list[dict[str, Any]], str, bool]:
    """Return workspaces, config path label, and whether config is real."""
    config_path = REAL_CONFIG if REAL_CONFIG.exists() else EXAMPLE_CONFIG
    if not config_path.exists():
        return [], "missing", False
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return payload.get("workspaces", []), str(config_path), config_path == REAL_CONFIG


def _write_report(name: str, payload: dict[str, Any], timestamp: str) -> None:
    safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name)[:80]
    report_file = OUTPUT_DIR / f"{safe_name}_{timestamp[:10]}.json"
    report_file.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    engine = DriftEngine()
    workspaces, config_label, is_real_config = _load_config()
    timestamp = datetime.now(UTC).isoformat()

    print(f"Daily drift scan: config={config_label} real_config={is_real_config}")
    if not workspaces:
        _write_report("summary", {"timestamp": timestamp, "status": "no_workspaces", "config": config_label}, timestamp)
        print("No workspaces configured. Create workspaces.json from workspaces.example.json to enable real scans.")
        return 0

    total_drift = 0
    scanned = 0
    skipped = 0
    errors = 0
    summary_rows: list[dict[str, Any]] = []

    for ws in workspaces:
        name = str(ws.get("name") or "unnamed")
        raw_path = str(ws.get("path") or "")
        workspace_path = Path(raw_path)

        if not is_real_config or raw_path.startswith("/path/to/"):
            skipped += 1
            row = {"workspace": name, "path": raw_path, "status": "skipped_placeholder_config"}
            summary_rows.append(row)
            _write_report(name, {"timestamp": timestamp, **row}, timestamp)
            print(f"SKIP: {name} - placeholder/demo config; create workspaces.json with a real path")
            continue

        if not workspace_path.exists():
            errors += 1
            row = {"workspace": name, "path": raw_path, "status": "error", "error": "workspace_path_missing"}
            summary_rows.append(row)
            _write_report(name, {"timestamp": timestamp, **row}, timestamp)
            print(f"ERROR: {name} - missing path {workspace_path}")
            continue

        result = engine.scan_workspace(name, workspace_path)
        scanned += 1
        if result.error:
            errors += 1
            print(f"ERROR: {name} - {result.error}")
        elif result.drift_items:
            try:
                SlackClient().send_drift_alert(result)
            except Exception as exc:  # alerting must not hide scan result
                print(f"WARN: {name} Slack alert failed: {exc}")
            print(f"ALERT: {name} has {len(result.drift_items)} drift items")
        else:
            print(f"OK: {name} - no drift")

        total_drift += int(result.summary.get("total", 0))
        row = {
            "workspace": name,
            "path": raw_path,
            "status": "error" if result.error else "drift" if result.drift_items else "ok",
            "error": result.error,
            "drift_items": len(result.drift_items),
            "summary": result.summary,
        }
        summary_rows.append(row)
        _write_report(name, {"timestamp": timestamp, **row, "items": [i.to_dict() for i in result.drift_items]}, timestamp)

    summary = {
        "timestamp": timestamp,
        "config": config_label,
        "real_config": is_real_config,
        "scanned": scanned,
        "skipped": skipped,
        "errors": errors,
        "total_drift": total_drift,
        "rows": summary_rows,
    }
    _write_report("summary", summary, timestamp)
    print(f"\nSummary: scanned={scanned} skipped={skipped} errors={errors} total_drift={total_drift}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
