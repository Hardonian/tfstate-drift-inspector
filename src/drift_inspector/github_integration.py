"""GitHub integration for remediation PRs and webhook handling."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from github import Github, GithubIntegration
from github.Repository import Repository

from drift_inspector.config import get_settings
from drift_inspector.engine import DriftResult, Severity

logger = structlog.get_logger(__name__)


@dataclass
class GitHubInstallation:
    """GitHub App installation info."""
    installation_id: int
    account_login: str
    account_type: str  # User or Organization
    repositories: list[str]


class GitHubClient:
    """GitHub API client using App authentication."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self._integration: GithubIntegration | None = None
        self._app_client: Github | None = None

    @property
    def integration(self) -> GithubIntegration:
        if self._integration is None:
            if not self.settings.github_app_id or not self.settings.github_app_private_key:
                raise ValueError("GitHub App credentials not configured")
            self._integration = GithubIntegration(
                self.settings.github_app_id,
                self.settings.github_app_private_key,
            )
        return self._integration

    def get_installation_client(self, installation_id: int) -> Github:
        """Get authenticated GitHub client for an installation."""
        token = self.integration.get_access_token(installation_id).token
        return Github(token)

    def get_installations(self) -> list[GitHubInstallation]:
        """List all installations of the GitHub App."""
        installations = []
        for inst in self.integration.get_installations():
            repos = [repo.full_name for repo in inst.get_repos()]
            installations.append(GitHubInstallation(
                installation_id=inst.id,
                account_login=inst.account.login,
                account_type=inst.account.type,
                repositories=repos,
            ))
        return installations

    def create_remediation_pr(
        self,
        installation_id: int,
        repo_full_name: str,
        drift_result: DriftResult,
        branch_name: str | None = None,
    ) -> dict[str, Any]:
        """Create a remediation PR for drift findings."""
        client = self.get_installation_client(installation_id)
        repo: Repository = client.get_repo(repo_full_name)

        # Generate branch name
        if branch_name is None:
            timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            branch_name = f"drift-remediation/{drift_result.workspace_name}-{timestamp}"

        # Get default branch
        default_branch = repo.default_branch
        base_ref = repo.get_git_ref(f"heads/{default_branch}")
        base_sha = base_ref.object.sha

        # Create new branch
        new_ref = repo.create_git_ref(f"refs/heads/{branch_name}", base_sha)

        # Generate remediation files
        files = self._generate_remediation_files(drift_result)

        # Commit files
        tree_elements = []
        for file_path, content in files.items():
            blob = repo.create_git_blob(content, "utf-8")
            tree_elements.append({
                "path": file_path,
                "mode": "100644",
                "type": "blob",
                "sha": blob.sha,
            })

        tree = repo.create_git_tree(tree_elements, base_tree=repo.get_git_tree(base_sha))
        commit = repo.create_git_commit(
            f"chore: drift remediation for {drift_result.workspace_name}",
            tree,
            [repo.get_git_commit(base_sha)],
        )
        new_ref.edit(commit.sha)

        # Create PR
        pr = repo.create_pull(
            title=f"🔧 Drift Remediation: {drift_result.workspace_name}",
            body=self._generate_pr_body(drift_result),
            head=branch_name,
            base=default_branch,
            draft=False,
        )

        # Add labels
        try:
            pr.add_to_labels("drift-remediation", "automated", "terraform")
        except Exception:
            pass  # Labels might not exist

        return {
            "pr_number": pr.number,
            "pr_url": pr.html_url,
            "branch_name": branch_name,
            "repo": repo_full_name,
        }

    def _generate_remediation_files(self, result: DriftResult) -> dict[str, str]:
        """Generate remediation files for the PR."""
        files = {}

        # 1. Summary markdown
        files["DRIFT_REMEDIATION_SUMMARY.md"] = self._generate_summary_md(result)

        # 2. Terraform plan output (for reference)
        if result.plan_output:
            files[f"terraform-plan-{result.workspace_name}.txt"] = result.plan_output

        # 3. Drift items as JSON for programmatic consumption
        files[f"drift-items-{result.workspace_name}.json"] = json.dumps(
            [item.to_dict() for item in result.drift_items],
            indent=2,
        )

        return files

    def _generate_summary_md(self, result: DriftResult) -> str:
        """Generate markdown summary for the PR."""
        lines = [
            f"# Drift Remediation: {result.workspace_name}",
            "",
            f"**Scanned:** {result.scanned_at.isoformat()}",
            f"**Terraform Version:** {result.terraform_version}",
            f"**Total Drift Items:** {result.summary['total']}",
            "",
            "## Severity Breakdown",
            f"- 🔴 Critical: {result.summary['critical']}",
            f"- 🟠 High: {result.summary['high']}",
            f"- 🟡 Medium: {result.summary['medium']}",
            f"- 🟢 Low: {result.summary['low']}",
            "",
            "## Drift Items",
            "",
        ]

        for item in result.drift_items:
            severity_emoji = {
                Severity.CRITICAL: "🔴",
                Severity.HIGH: "🟠",
                Severity.MEDIUM: "🟡",
                Severity.LOW: "🟢",
            }.get(item.severity, "⚪")

            action_emoji = {
                "create": "➕",
                "update": "🔄",
                "delete": "🗑️",
                "replace": "🔁",
            }.get(item.planned_action, "❓")

            lines.extend([
                f"### {severity_emoji} {item.address}",
                f"- **Type:** {item.drift_type}",
                f"- **Action:** {action_emoji} {item.planned_action}",
                f"- **Severity:** {item.severity}",
                f"- **Detail:** {json.dumps(item.detail, indent=2)}",
                "",
            ])

        lines.extend([
            "---",
            "",
            "## Next Steps",
            "",
            "1. Review the drift items above",
            "2. Determine if changes are intentional (update Terraform config) or unintentional (revert in cloud)",
            "3. For intentional changes: update your Terraform configuration and apply",
            "4. For unintentional changes: use cloud console/CLI to revert to Terraform-managed state",
            "5. Close this PR once resolved",
            "",
            "*Generated by tfstate-drift-inspector*",
        ])

        return "\n".join(lines)

    def _generate_pr_body(self, result: DriftResult) -> str:
        """Generate PR description."""
        critical_high = result.critical_count + result.high_count

        return f"""## 🔍 Terraform Drift Detected

**Workspace:** `{result.workspace_name}`
**Scan Time:** {result.scanned_at.strftime('%Y-%m-%d %H:%M UTC')}
**Total Changes:** {result.summary['total']} ({critical_high} critical/high)

### Severity Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | {result.summary['critical']} |
| 🟠 High | {result.summary['high']} |
| 🟡 Medium | {result.summary['medium']} |
| 🟢 Low | {result.summary['low']} |

### Quick Actions
- [ ] Review `DRIFT_REMEDIATION_SUMMARY.md` for details
- [ ] Check `terraform-plan-{result.workspace_name}.txt` for full plan output
- [ ] Decide: update Terraform config or revert cloud changes
- [ ] Apply fixes and close this PR

### Automated Remediation
This PR was created automatically by **tfstate-drift-inspector**.
See the attached files for complete drift analysis.

> **Note:** Critical/High severity items should be addressed
> immediately as they may indicate security or compliance risks.
"""

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """Verify GitHub webhook signature."""
        if not self.settings.github_webhook_secret:
            return True  # Skip verification if not configured

        expected = "sha256=" + hmac.new(
            self.settings.github_webhook_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)


class WebhookHandler:
    """Handle GitHub webhook events."""

    def __init__(self, github_client: GitHubClient):
        self.github = github_client

    def handle_installation(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle installation created/deleted events."""
        action = payload.get("action")
        installation = payload.get("installation", {})

        if action == "created":
            logger.info("GitHub App installed", installation_id=installation.get("id"))
            return {"status": "installed", "installation_id": installation.get("id")}
        if action == "deleted":
            logger.info("GitHub App uninstalled", installation_id=installation.get("id"))
            return {"status": "uninstalled", "installation_id": installation.get("id")}

        return {"status": "ignored", "action": action}

    def handle_push(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle push events - could trigger immediate scan."""
        repo = payload.get("repository", {})
        ref = payload.get("ref", "")
        logger.info("Push event received", repo=repo.get("full_name"), ref=ref)
        return {"status": "received", "repo": repo.get("full_name"), "ref": ref}

    def handle_workflow_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle workflow run completion - could trigger post-deploy drift check."""
        workflow = payload.get("workflow_run", {})
        conclusion = workflow.get("conclusion")
        repo = workflow.get("repository", {})

        if conclusion == "success":
            logger.info("Workflow succeeded, drift check could be triggered",
                       repo=repo.get("full_name"), workflow=workflow.get("name"))

        return {"status": "received", "conclusion": conclusion}
