# tfstate-drift-inspector v0.1.0 — Release Notes

## Status: READY FOR DEPLOY

All core functionality implemented and tested:

### Core Engine (src/drift_inspector/engine.py)
- DriftItem dataclass for tracking individual drift items
- DriftResult with summary counts (critical, high, medium, low)
- DriftType enum (create, delete, update, destroy, metadata_only)
- Severity enum with classification logic
- DriftEngine.scan_workspace() for terraform plan detection

### Database (src/drift_inspector/models.py)
- SQLAlchemy models: Workspace, DriftScan, DriftItem, RemediationPR
- Database.record_scan() for persistence
- Database.get_recent_scans() for history view

### Integrations
- Slack webhook alerts with Block Kit formatting
- GitHub PR creation with auto-generated remediation
- Webhook signature verification (hmac-sha256)

### CLI (src/drift_inspector/cli.py)
- `scan PATH` — Scan single workspace
- `alert PATH` — Scan + Slack alert
- `pr PATH --repo X --installation-id Y` — Create remediation PR
- `history` — View scan history
- `serve` — Start FastAPI server (uvicorn)

### API (src/drift_inspector/api.py)
- FastAPI server with CORS middleware
- `/health` endpoint
- `/api/v1/scan` — Trigger drift scan
- `/api/v1/history` — Get scan history
- `/api/v1/webhook/github` — GitHub webhook receiver

### Deploy Stack
- `deploy/workers/src/worker.js` — Cloudflare Workers API
- `deploy/d1/schema.sql` — D1 database schema
- `deploy/frontend/index.html` — Dashboard SPA
- `deploy/landing/index.html` — Landing page
- `.github/workflows/deploy.yml` — CI/CD for all deploy targets

### Test Coverage
- 33 tests passing
- Config, engine, models, slack integration tested

## Missing for Production Deploy

1. **Cloudflare API token** — Add `CF_API_TOKEN` and `CF_ACCOUNT_ID` secrets
2. **GitHub App credentials** — Add `GITHUB_APP_ID` and `GITHUB_APP_PRIVATE_KEY`
3. **Slack token** — Add `SLACK_BOT_TOKEN`
4. **Custom domain** — Set `DOMAIN` variable in GitHub

## Next Steps

```bash
# 1. Add secrets to GitHub
gh secret set CF_API_TOKEN
gh secret set CF_ACCOUNT_ID

# 2. Deploy
git push origin main

# 3. Or test locally
./scripts/smoke_test.sh
```