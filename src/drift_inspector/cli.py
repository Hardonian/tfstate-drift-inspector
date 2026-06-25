"""CLI interface for tfstate-drift-inspector."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax

from drift_inspector.config import get_settings, Settings
from drift_inspector.engine import DriftEngine, DriftResult, Severity
from drift_inspector.models import Database

app = typer.Typer(
    name="drift-inspector",
    help="Terraform drift detection — scan workspaces, alert on changes, create remediation PRs",
    add_completion=False,
)
console = Console()
logger = structlog.get_logger(__name__)


def setup_logging(level: str = "INFO"):
    """Configure structured logging."""
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


@app.command()
def scan(
    workspace_path: str = typer.Argument(..., help="Path to Terraform workspace"),
    workspace_name: Optional[str] = typer.Option(None, "--name", "-n", help="Workspace name (defaults to directory name)"),
    output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, markdown"),
    severity_filter: Optional[str] = typer.Option(None, "--severity", "-s", help="Filter: critical, high, medium, low"),
    metadata: bool = typer.Option(False, "--metadata", "-m", help="Include metadata-only changes"),
):
    """Scan a Terraform workspace for drift."""
    settings = get_settings()
    engine = DriftEngine(settings)

    path = Path(workspace_path)
    name = workspace_name or path.name

    console.print(f"[bold]Scanning[/bold] [cyan]{name}[/cyan] at [dim]{path}[/dim]...")

    result = engine.scan_workspace(name, path)

    if result.error:
        console.print(f"[bold red]Error:[/bold red] {result.error}")
        raise typer.Exit(1)

    if severity_filter:
        result.drift_items = [d for d in result.drift_items if d.severity == severity_filter]

    if not metadata:
        from drift_inspector.engine import DriftType
        result.drift_items = [d for d in result.drift_items if d.drift_type != DriftType.METADATA_ONLY]

    if output == "json":
        console.print(json.dumps(result.to_dict(), indent=2, default=str))
    elif output == "markdown":
        console.print(_format_markdown(result))
    else:
        _print_table(result)


@app.command()
def scan_all(
    config_file: str = typer.Argument(..., help="Path to workspace config JSON"),
    output: str = typer.Option("table", "--output", "-o", help="Output format"),
):
    """Scan multiple workspaces from a config file."""
    settings = get_settings()
    engine = DriftEngine(settings)

    config_path = Path(config_file)
    if not config_path.exists():
        console.print(f"[bold red]Config file not found:[/bold red] {config_file}")
        raise typer.Exit(1)

    configs = json.loads(config_path.read_text())
    console.print(f"[bold]Scanning {len(configs)} workspaces...[/bold]\n")

    results = engine.scan_all_workspaces(configs)

    if output == "json":
        console.print(json.dumps([r.to_dict() for r in results], indent=2, default=str))
    else:
        for result in results:
            _print_table(result)
            console.print()

    # Summary
    total_drift = sum(r.summary["total"] for r in results)
    total_critical = sum(r.critical_count for r in results)
    workspaces_with_drift = sum(1 for r in results if r.has_drift)

    console.print(Panel(
        f"[bold]Summary:[/bold] {workspaces_with_drift}/{len(results)} workspaces with drift, "
        f"{total_critical} critical, {total_drift} total changes",
        title="Scan Complete",
        border_style="green" if total_critical == 0 else "red",
    ))


@app.command()
def alert(
    workspace_path: str = typer.Argument(..., help="Path to Terraform workspace"),
    channel: Optional[str] = typer.Option(None, "--channel", "-c", help="Slack channel override"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be sent without sending"),
):
    """Scan and send Slack alert if drift detected."""
    settings = get_settings()
    engine = DriftEngine(settings)

    path = Path(workspace_path)
    result = engine.scan_workspace(path.name, path)

    if not result.has_drift:
        console.print("[green]✓ No drift detected. No alert needed.[/green]")
        return

    if dry_run:
        console.print(f"[yellow]DRY RUN:[/yellow] Would send alert to {channel or settings.slack_default_channel}")
        console.print(f"  - {result.summary['total']} drift items ({result.critical_count} critical)")
        for item in result.drift_items[:5]:
            console.print(f"  - [{item.severity}] {item.address}: {item.planned_action}")
        return

    from drift_inspector.slack_integration import SlackClient
    slack = SlackClient(settings)
    response = slack.send_drift_alert(result, channel)

    if response.get("ok"):
        console.print(f"[green]✓ Alert sent to Slack[/green] (ts: {response.get('ts')})")
    else:
        console.print(f"[red]✗ Failed to send Slack alert:[/red] {response.get('error')}")
        raise typer.Exit(1)


@app.command()
def pr(
    workspace_path: str = typer.Argument(..., help="Path to Terraform workspace"),
    repo: str = typer.Option(..., "--repo", "-r", help="GitHub repo (org/name)"),
    installation_id: int = typer.Option(..., "--installation-id", "-i", help="GitHub App installation ID"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Scan without creating PR"),
):
    """Scan and create a remediation PR on GitHub."""
    settings = get_settings()
    engine = DriftEngine(settings)

    path = Path(workspace_path)
    result = engine.scan_workspace(path.name, path)

    if not result.has_drift:
        console.print("[green]✓ No drift detected. No PR needed.[/green]")
        return

    if dry_run:
        console.print(f"[yellow]DRY RUN:[/yellow] Would create PR on {repo}")
        console.print(f"  Branch: drift-remediation/{path.name}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}")
        console.print(f"  Items: {result.summary['total']}")
        return

    from drift_inspector.github_integration import GitHubClient
    github = GitHubClient(settings)
    response = github.create_remediation_pr(installation_id, repo, result)

    console.print(f"[green]✓ PR created:[/green] {response['pr_url']}")
    console.print(f"  Branch: {response['branch_name']}")


@app.command()
def history(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="Filter by workspace"),
    days: int = typer.Option(7, "--days", "-d", help="Days of history"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max results"),
):
    """View drift scan history."""
    settings = get_settings()
    db = Database(settings)
    db.create_table()

    scans = db.get_recent_scans(limit=limit, workspace_name=workspace)

    if not scans:
        console.print("[dim]No scan history found.[/dim]")
        return

    table = Table(title=f"Drift Scan History (last {days} days)")
    table.add_column("Workspace", style="cyan")
    table.add_column("Scanned", style="dim")
    table.add_column("Drift", justify="right")
    table.add_column("🔴", justify="right", style="red")
    table.add_column("🟠", justify="right", style="yellow")
    table.add_column("Status", style="green")

    for scan in scans:
        status = "✓ Clean" if not scan["has_drift"] else "⚠ Drift"
        style = "green" if not scan["has_drift"] else "yellow"
        if scan.get("critical_count", 0) > 0:
            style = "red"
            status = "🚨 Critical"

        table.add_row(
            scan["workspace_name"],
            scan["scanned_at"][:19],
            str(scan["total_items"]),
            str(scan.get("critical_count", 0)),
            str(scan.get("high_count", 0)),
            f"[{style}]{status}[/{style}]",
        )

    console.print(table)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h"),
    port: int = typer.Option(8080, "--port", "-p"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes"),
):
    """Start the web API server."""
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "drift_inspector.api:app",
        host=host,
        port=port,
        reload=reload,
        log_level=settings.log_level.lower(),
    )


@app.command()
def init_db():
    """Initialize the database."""
    settings = get_settings()
    db = Database(settings)
    db.create_tables()
    console.print("[green]✓ Database initialized[/green]")


@app.command()
def version():
    """Show version info."""
    console.print("tfstate-drift-inspector v0.1.0")


def _print_table(result: DriftResult):
    """Print drift result as a rich table."""
    if not result.has_drift:
        console.print(Panel(
            f"[green]✓ No drift detected in [bold]{result.workspace_name}[/bold][/green]\n"
            f"Scanned: {result.scanned_at.strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"Terraform: {result.terraform_version}",
            border_style="green",
        ))
        return

    table = Table(title=f"Drift: {result.workspace_name}")
    table.add_column("Address", style="cyan", max_width=60)
    table.add_column("Type", style="magenta")
    table.add_column("Action", style="yellow")
    table.add_column("Severity", justify="center")

    severity_colors = {
        Severity.CRITICAL: "red bold",
        Severity.HIGH: "red",
        Severity.MEDIUM: "yellow",
        Severity.LOW: "dim",
    }

    for item in result.drift_items:
        color = severity_colors.get(item.severity, "white")
        table.add_row(
            item.address,
            item.drift_type.value,
            item.planned_action,
            f"[{color}]{item.severity.upper()}[/{color}]",
        )

    console.print(table)

    summary = result.summary
    status_color = "red" if summary["critical"] > 0 else "yellow" if summary["high"] > 0 else "green"
    console.print(Panel(
        f"[bold {status_color}]{summary['total']} drift items found[/bold {status_color}]\n"
        f"🔴 Critical: {summary['critical']}  🟠 High: {summary['high']}  "
        f"🟡 Medium: {summary['medium']}  🟢 Low: {summary['low']}\n"
        f"Scanned: {result.scanned_at.strftime('%Y-%m-%d %H:%M UTC')} • Terraform: {result.terraform_version}",
        border_style=status_color,
    ))


def _format_markdown(result: DriftResult) -> str:
    """Format result as markdown."""
    lines = [
        f"# Drift Report: {result.workspace_name}",
        "",
        f"**Scanned:** {result.scanned_at.isoformat()}",
        f"**Terraform:** {result.terraform_version}",
        f"**Total:** {result.summary['total']} drift items",
        "",
        "## Severity",
        f"- 🔴 Critical: {result.summary['critical']}",
        f"- 🟠 High: {result.summary['high']}",
        f"- 🟡 Medium: {result.summary['medium']}",
        f"- 🟢 Low: {result.summary['low']}",
        "",
        "## Drift Items",
        "",
        "| Address | Type | Action | Severity |",
        "|---------|------|--------|----------|",
    ]
    for item in result.drift_items:
        lines.append(f"| `{item.address}` | {item.drift_type.value} | {item.planned_action} | {item.severity} |")
    return "\n".join(lines)


if __name__ == "__main__":
    setup_logging()
    app()