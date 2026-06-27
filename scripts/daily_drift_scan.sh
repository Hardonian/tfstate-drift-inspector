#!/bin/bash
set -Eeuo pipefail
cd /home/scott/ai-workspace/repos/tfstate-drift-inspector
/home/scott/ai-workspace/repos/tfstate-drift-inspector/.venv/bin/python3 scripts/daily_drift_scan.py