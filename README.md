# tfstate-drift-inspector

**Nightly Terraform drift detection with Slack alerts and remediation PRs.**

## Problem

Terraform state drifts from reality — manual cloud changes, abandoned resources, team members applying fixes outside the pipeline. You only find out during the next `terraform plan`, which often happens at the worst possible time.

## Solution

A lightweight, self-hosted service that:

1. **Scans** all your Terraform workspaces nightly
2. **Detects** drift (resources added, removed, changed outside IaC)
3. **Classifies** severity (security-critical = 🔴, compute/network = 🟠, tags = 🟡)
4. **Alerts** you in Slack with a structured summary
5. **Creates** remediation PRs with full context when you want auto-fix

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

# Scan multiple workspaces
drift-inspector scan-all workspace_config.json

# View history
drift-inspector history --days 7

# Start API server
drift-inspector serve
```

### Deploy to Fly.io (Production)

The infrastructure is fully defined in `infra/terraform/`:

```bash
cd infra/terraform
terraform init
terraform plan
terraform apply
```

This provisions:
- Fly.io app with 256MB RAM (~$2/mo)
- PostgreSQL database (free tier, 1GB)
- Scheduled nightly scan via Fly machines
- GitHub App webhook for real-time scanning

### Deploy to AWS (Alternative)

```bash
cd infra/terraform/aws
terraform init
terraform plan
terraform apply
```

This provisions:
- Lambda function (256MB, <1s per scan)
- EventBridge schedule (cron 0 2 * * *)
- S3 for state persistence
- SES for email alerts
- RDS PostgreSQL (free tier)

## Architecture

```
                    GitHub Webhook (optional)
                           │
                           ▼
┌─────────────────────────────────────────────────────┐
│                   FastAPI Server                     │
│              (drift_inspector.api)                   │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────┐  │
│  │  /scan      │  │  /scan-all   │  │  /history │  │
│  │  (single)   │  │  (batch)     │  │  (query)  │  │
│  └──────┬──────┘  └──────┬───────┘  └─────┬─────┘  │
│         │                │                 │        │
│         ▼                ▼                 │        │
│  ┌──────────────────────────────┐          │        │
│  │      DriftEngine             │          │        │
│  │  (terraform plan + parse)    │          │        │
│  └──────────────┬───────────────┘          │        │
│                 │                          │        │
│    ┌────────────┼────────────┐             │        │
│    ▼            ▼            ▼             │        │
│ ┌──────┐  ┌────────┐  ┌─────────┐         │        │
│ │Slack │  │GitHub  │  │Database │◀────────┘        │
│ │Alert │  │PR      │  │History  │                   │
│ └──────┘  └────────┘  └─────────┘                   │
└─────────────────────────────────────────────────────┘
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `scan PATH` | Scan a single workspace for drift |
| `scan-all FILE` | Scan multiple workspaces from config |
| `alert PATH` | Scan + send Slack alert if drift found |
| `pr PATH --repo X --installation-id Y` | Scan + create GitHub PR |
| `history` | View scan history |
| `stats` | View aggregate statistics |
| `serve` | Start the API server |
| `init-db` | Initialize the database |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/api/v1/scan` | Trigger single workspace scan |
| POST | `/api/v1/scan-all` | Trigger batch scan |
| GET | `/api/v1/history` | View scan history |
| GET | `/api/v1/stats` | Aggregate statistics |
| POST | `/api/v1/webhook/github` | GitHub webhook receiver |
| GET | `/api/v1/installations` | List GitHub App installations |
| POST | `/api/v1/pr` | Create remediation PR |

## Configuration

All settings are loaded from environment variables or `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./drift_inspector.db` | Database URL |
| `GITHUB_APP_ID` | — | GitHub App ID |
| `GITHUB_APP_PRIVATE_KEY` | — | GitHub App PEM key |
| `SLACK_BOT_TOKEN` | — | Slack Bot token |
| `SLACK_DEFAULT_CHANNEL` | `#devops-alerts` | Default Slack channel |
| `TERRAFORM_PATH` | `terraform` | Path to terraform binary |
| `SCAN_CRON` | `0 2 * * *` | Cron schedule (UTC) |
| `STRIPE_SECRET_KEY` | — | Stripe secret (for web dashboard) |
| `STRIPE_PRICE_ID_MONTHLY` | — | Stripe price ID for subscription |

## Pricing (SaaS)

| Plan | Price | Features |
|------|-------|----------|
| Free | $0 | 3 workspaces, weekly scans, email alerts |
| Team | $299/mo | 20 workspaces, nightly scans, Slack, auto-PR |
| Business | $499/mo | Unlimited workspaces, webhooks, API access, SSO |

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check src/
mypy src/

# Format
ruff format src/
```

## License

MIT