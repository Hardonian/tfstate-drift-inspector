#!/bin/bash
set -Eeuo pipefail

cd "$(dirname "$0")/.."

echo "=== tfstate-drift-inspector Smoke Test ==="

echo "1. Checking Python syntax..."
.venv/bin/python3 -m py_compile src/drift_inspector/__init__.py
.venv/bin/python3 -m py_compile src/drift_inspector/config.py
.venv/bin/python3 -m py_compile src/drift_inspector/engine.py
.venv/bin/python3 -m py_compile src/drift_inspector/models.py
.venv/bin/python3 -m py_compile src/drift_inspector/cli.py
echo "   Python syntax OK"

echo "2. Running tests..."
.venv/bin/pytest tests/ -q --tb=short
echo "   Tests passed"

echo "3. Checking CLI..."
.venv/bin/drift-inspector --help > /dev/null
echo "   CLI OK"

echo "4. Checking API import..."
.venv/bin/python3 -c "from drift_inspector.api import app; print('   API OK')"

echo "5. Checking frontend..."
test -f deploy/frontend/index.html && echo "   Frontend exists OK"

echo "6. Checking landing..."
test -f deploy/landing/index.html && echo "   Landing exists OK"

echo "7. Checking workers..."
test -f deploy/workers/src/worker.js && echo "   Workers OK"

echo ""
echo "=== All smoke tests passed ==="