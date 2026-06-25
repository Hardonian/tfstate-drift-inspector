-- D1 Database Schema for tfstate-drift-inspector
-- Free tier: 5GB storage, 50K reads/day, 100K writes/day

-- Workspaces
CREATE TABLE IF NOT EXISTS workspaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    repo_full_name TEXT,
    repo_url TEXT,
    branch TEXT DEFAULT 'main',
    path TEXT,
    installation_id INTEGER,
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_workspace_name ON workspaces(name);
CREATE INDEX IF NOT EXISTS idx_workspace_active ON workspaces(is_active);

-- Drift Scans
CREATE TABLE IF NOT EXISTS drift_scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    workspace_name TEXT NOT NULL,
    scanned_at TEXT NOT NULL,
    has_drift INTEGER DEFAULT 0,
    total_items INTEGER DEFAULT 0,
    critical_count INTEGER DEFAULT 0,
    high_count INTEGER DEFAULT 0,
    medium_count INTEGER DEFAULT 0,
    low_count INTEGER DEFAULT 0,
    error TEXT,
    terraform_version TEXT,
    plan_exit_code INTEGER,
    duration_ms INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_scan_workspace ON drift_scans(workspace_id);
CREATE INDEX IF NOT EXISTS idx_scan_date ON drift_scans(scanned_at);
CREATE INDEX IF NOT EXISTS idx_scan_drift ON drift_scans(has_drift);

-- Drift Items
CREATE TABLE IF NOT EXISTS drift_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL,
    address TEXT NOT NULL,
    drift_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    planned_action TEXT NOT NULL,
    detail TEXT,  -- JSON blob
    raw_change TEXT,  -- JSON blob
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_item_scan ON drift_items(scan_id);
CREATE INDEX IF NOT EXISTS idx_item_severity ON drift_items(severity);

-- Remediation PRs
CREATE TABLE IF NOT EXISTS remediation_prs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL,
    workspace_name TEXT NOT NULL,
    repo_full_name TEXT,
    pr_number INTEGER,
    pr_url TEXT,
    branch_name TEXT,
    status TEXT DEFAULT 'open',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_pr_scan ON remediation_prs(scan_id);
CREATE INDEX IF NOT EXISTS idx_pr_status ON remediation_prs(status);

-- Subscriptions (for SaaS billing)
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    plan TEXT DEFAULT 'free',  -- free, team, business
    status TEXT DEFAULT 'active',
    current_period_start TEXT,
    current_period_end TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);