# tfstate-drift-inspector

**Status: Experimental / Proof-of-concept (v0.1.0)**

Nightly Terraform drift detection with a CLI, Slack alerts, and GitHub remediation PRs.

## Problem

Terraform state drifts from reality — manual cloud changes, abandoned resources, team members applying fixes outside the pipeline. You only find out during the next `terraform plan`, which often happens at the worst possible time.

## What It Does

1. **Scans** Terraform workspaces by running `terraform plan` with `-detailed-exitcode`
2. **Parses** plan JSON output to detect resources added, removed, or changed outside IaC
3. **Classifies** severity — security groups/IAM/databases → CRITICAL, compute/network → HIGH, tags → MEDIUM, metadata → LOW (filtered by default)
4. **Alerts** via Slack with structured Block Kit messages showing severity breakdown and top drift items
5. **Creates** GitHub remediation PRs with full drift analysis, plan output, and a remediation checklist
6. **Stores** scan history in SQLite (or PostgreSQL via SQLAlchemy connection string)

## Tech Stack

- **Python 3.11+** — core language
- **Typer** — CLI framework (Click-based)
- **FastAPI + uvicorn** — web API server
- **SQLAlchemy** — database ORM
- **python-terraform** — terraform plan execution
- **Slack SDK** — drift alert formatting and delivery
- **PyGithub** — GitHub App integration for PRs
- **Rich** — terminal output formatting
- **Structlog** — structured logging
- **Docker** — containerized deployment
- **Fly.io** — production deployment target

## Quick Start

### Local Dev

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Initialize database
drift-inspector init-db

# Scan a workspace
drift-inspector scan /path/to/terraform/workspace --name my-workspace

# Scan with JSON output
drift-inspector scan /path/to/terraform/workspace --output json

# Scan multiple workspaces from a config file
drift-inspector scan-all workspace_config.json

# Scan and send Slack alert if drift found
drift-inspector alert /path/to/terraform/workspace --channel #infra-alerts

# Scan and create a GitHub remediation PR
drift-inspector pr /path/to/terraform/workspace --repo org/repo --installation-id 12345

# View scan history
drift-inspector history --days 7

# Start the API server
drift-inspector serve

# Show version
drift-inspector version
```

### Deploy to Fly.io

```bash
fly launch --copy-config
fly deploy
```

See `fly.toml` and `Dockerfile` for the production configuration. The Fly.io setup provisions:
- 256MB RAM app (~$2/mo)
- Scheduled nightly scan via Fly Machines (runs at 02:00 UTC)
- Auto-stops the scanner machine between runs

## CLI Commands

| Command | Description |
|---------|-------------|
| `scan PATH` | Scan a single workspace for drift |
| `scan-all FILE` | Scan multiple workspaces from a JSON config file |
| `alert PATH` | Scan + send Slack alert if drift found |
| `pr PATH --repo X --installation-id Y` | Scan + create a GitHub remediation PR |
| `history` | View scan history from the database |
| `serve` | Start the FastAPI web server |
| `init-db` | Initialize the database tables |
| `version` | Show version |

## API Endpoints

The FastAPI server (started via `serve`) exposes:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/api/v1/scan` | Trigger a single workspace scan |
| POST | `/api/v1/scan-all` | Trigger batch scan across multiple workspaces |
| GET | `/api/v1/history` | View scan history |
| GET | `/api/v1/stats` | Aggregate statistics |
| POST | `/api/v1/webhook/github` | GitHub webhook receiver |
| GET | `/api/v1/installations` | List GitHub App installations |
| POST | `/api/v1/pr` | Create a remediation PR for a previous scan |

## Configuration

Settings are loaded from environment variables or `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./drift_inspector.db` | SQLAlchemy database URL |
| `GITHUB_APP_ID` | — | GitHub App ID |
| `GITHUB_APP_PRIVATE_KEY` | — | GitHub App PEM private key |
| `GITHUB_WEBHOOK_SECRET` | — | GitHub webhook secret for signature validation |
| `SLACK_BOT_TOKEN` | — | Slack Bot User OAuth Token (xoxb-) |
| `SLACK_DEFAULT_CHANNEL` | `#devops-alerts` | Default Slack channel for alerts |
| `TERRAFORM_PATH` | `terraform` | Path to terraform binary |
| `SCAN_CRON` | `0 2 * * *` | Cron schedule for nightly scan (UTC) |
| `LOG_LEVEL` | `INFO` | Logging level |

## Cloudflare Workers Deployment (Experimental)

The `deploy/` directory contains an **experimental, partial** Cloudflare Workers implementation:

- `deploy/workers/` — Cloudflare Worker (via wrangler) that mirrors the API endpoints using D1 database
- `deploy/frontend/` — Frontend dashboard for Cloudflare Pages
- `deploy/landing/` — Marketing landing page

These are a separate deployment path and are **not yet production-ready**. The primary API server is the Python FastAPI application.

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check src/

# Type check
mypy src/

# Format
ruff format src/
```

## Project Structure

```
src/drift_inspector/
├── __init__.py          # Package init, exports
├── cli.py               # Typer CLI (scan, scan-all, alert, pr, history, serve, init-db, version)
├── engine.py            # DriftEngine — terraform plan execution and drift parsing
├── config.py            # Pydantic-settings configuration
├── models.py            # SQLAlchemy models + Database class
├── api.py               # FastAPI web server
├── slack_integration.py # Slack alert formatting and delivery
└── github_integration.py# GitHub App auth, PR creation, webhook handling
```

## License

MIT
