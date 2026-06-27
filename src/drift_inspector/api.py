"""FastAPI web server for drift-inspector."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import structlog
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from drift_inspector.config import get_settings
from drift_inspector.engine import DriftEngine
from drift_inspector.github_integration import GitHubClient, WebhookHandler
from drift_inspector.models import Database

logger = structlog.get_logger(__name__)

app = FastAPI(
    title="tfstate-drift-inspector",
    description="Terraform drift detection API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Request/Response Models ---

class ScanRequest(BaseModel):
    workspace_name: str
    workspace_path: str
    installation_id: int | None = None

class WorkspaceConfig(BaseModel):
    name: str
    path: str
    repo_full_name: str | None = None
    installation_id: int | None = None

class WorkspaceList(BaseModel):
    workspaces: list[WorkspaceConfig]

class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: str

# --- Dependencies ---

def get_db():
    settings = get_settings()
    db = Database(settings)
    db.create_tables()
    return db

def get_engine():
    settings = get_settings()
    return DriftEngine(settings)

def get_github():
    settings = get_settings()
    return GitHubClient(settings)

# --- Endpoints ---

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        version="0.1.0",
        timestamp=datetime.now(UTC).isoformat(),
    )

@app.post("/api/v1/scan")
async def trigger_scan(
    request: ScanRequest,
    db: Database = Depends(get_db),
    engine: DriftEngine = Depends(get_engine),
):
    """Trigger a drift scan for a workspace."""
    path = Path(request.workspace_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {request.workspace_path}")

    result = engine.scan_workspace(request.workspace_name, path)
    scan_id = db.record_scan(result)

    return {
        "scan_id": scan_id,
        "workspace_name": result.workspace_name,
        "has_drift": result.has_drift,
        "summary": result.summary,
        "items": [item.to_dict() for item in result.drift_items],
    }

@app.post("/api/v1/scan-all")
async def scan_all(
    request: WorkspaceList,
    db: Database = Depends(get_db),
    engine: DriftEngine = Depends(get_engine),
):
    """Scan multiple workspaces."""
    configs = [{"name": w.name, "path": w.path} for w in request.workspaces]
    results = engine.scan_all_workspaces(configs)

    scan_ids = []
    for result in results:
        scan_id = db.record_scan(result)
        scan_ids.append(scan_id)

    return {
        "scan_ids": scan_ids,
        "total_workspaces": len(results),
        "workspaces_with_drift": sum(1 for r in results if r.has_drift),
        "total_items": sum(r.summary["total"] for r in results),
        "results": [
            {
                "workspace_name": r.workspace_name,
                "has_drift": r.has_drift,
                "summary": r.summary,
            }
            for r in results
        ],
    }

@app.get("/api/v1/history")
async def get_history(
    workspace: str | None = None,
    limit: int = 20,
    db: Database = Depends(get_db),
):
    """Get scan history."""
    scans = db.get_recent_scans(limit=limit, workspace_name=workspace)
    return {"scans": scans}

@app.get("/api/v1/stats")
async def get_stats(
    days: int = 7,
    db: Database = Depends(get_db),
):
    """Get aggregate statistics."""
    return db.get_workspace_stats(days=days)

@app.post("/api/v1/webhook/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
    github: GitHubClient = Depends(get_github),
):
    """Handle GitHub webhook events."""
    body = await request.body()

    # Verify signature
    if x_hub_signature_256 and not github.verify_webhook_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = json.loads(body)
    handler = WebhookHandler(github)

    event_handlers = {
        "installation": handler.handle_installation,
        "push": handler.handle_push,
        "workflow_run": handler.handle_workflow_run,
    }

    handler_fn = event_handlers.get(x_github_event)
    if handler_fn:
        result = handler_fn(payload)
        return JSONResponse(content=result)

    return {"status": "ignored", "event": x_github_event}

@app.get("/api/v1/installations")
async def list_installations(
    github: GitHubClient = Depends(get_github),
):
    """List GitHub App installations."""
    try:
        installations = github.get_installations()
        return {
            "installations": [
                {
                    "id": inst.installation_id,
                    "account_login": inst.account_login,
                    "account_type": inst.account_type,
                    "repositories": inst.repositories,
                }
                for inst in installations
            ]
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/v1/pr")
async def create_pr(
    scan_id: int,
    repo: str,
    installation_id: int,
    github: GitHubClient = Depends(get_github),
    db: Database = Depends(get_db),
):
    """Create a remediation PR for a scan."""
    # Get scan items
    items = db.get_scan_items(scan_id)
    if not items:
        raise HTTPException(status_code=404, detail="Scan not found or has no items")

    # Reconstruct result (simplified)
    from drift_inspector.engine import DriftResult
    result = DriftResult(
        workspace_name=items[0].get("workspace_name", "unknown"),
        workspace_id="",
        scanned_at=datetime.now(UTC),
        has_drift=True,
        drift_items=[],
    )

    try:
        return github.create_remediation_pr(installation_id, repo, result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
