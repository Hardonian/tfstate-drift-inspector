#!/usr/bin/env python3
"""Entry point for scan command (used by cron jobs)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add package to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from drift_inspector.cli import scan

if __name__ == "__main__":
    # Load workspace config from file or environment
    config_file = Path(__file__).parent.parent / "workspace_config.json"
    if config_file.exists():
        configs = json.loads(config_file.read_text())
        for config in configs:
            try:
                scan(
                    workspace_path=config["path"],
                    workspace_name=config.get("name"),
                    output="table",
                    metadata=False,
                )
            except Exception as e:
                print(f"ERROR: {config.get('name', 'unknown')}: {e}", file=sys.stderr)
                sys.exit(1)
    else:
        # Read from args
        scan()