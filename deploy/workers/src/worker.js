/**
 * Cloudflare Workers API for tfstate-drift-inspector
 * Free tier: 100K requests/day, 10ms CPU per request
 */

import { Router } from 'itty-router';

const router = Router();

// ─── Helpers ──────────────────────────────────────────────────────

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function error(message, status = 400) {
  return json({ error: message }, status);
}

// ─── Health Check ─────────────────────────────────────────────────

router.get('/health', () => {
  return json({
    status: 'ok',
    version: '0.1.0',
    timestamp: new Date().toISOString(),
  });
});

// ─── Scan Endpoints ───────────────────────────────────────────────

// POST /api/v1/scan — Trigger a single workspace scan
router.post('/api/v1/scan', async (request, env) => {
  const body = await request.json();
  const { workspace_name, workspace_path } = body;

  if (!workspace_name || !workspace_path) {
    return error('workspace_name and workspace_path are required');
  }

  // In a real implementation, this would:
  // 1. Clone/pull the terraform repo
  // 2. Run terraform plan
  // 3. Parse the output
  // 4. Store results in D1
  // 5. Send alerts if drift detected

  // For now, record the scan request
  const stmt = env.DB.prepare(
    `INSERT INTO drift_scans (workspace_name, scanned_at, has_drift, total_items)
     VALUES (?, datetime('now'), 0, 0)`
  ).bind(workspace_name);
  const result = await stmt.run();

  return json({
    scan_id: result.meta.last_row_id,
    workspace_name,
    status: 'queued',
    message: 'Scan queued. Results will be available shortly.',
  });
});

// GET /api/v1/scan/:id — Get scan results
router.get('/api/v1/scan/:id', async (request, env) => {
  const scanId = parseInt(request.params.id);

  const scan = await env.DB.prepare(
    'SELECT * FROM drift_scans WHERE id = ?'
  ).bind(scanId).first();

  if (!scan) {
    return error('Scan not found', 404);
  }

  const items = await env.DB.prepare(
    'SELECT address, drift_type, severity, planned_action, detail FROM drift_items WHERE scan_id = ?'
  ).bind(scanId).all();

  return json({
    scan,
    items: items.results,
  });
});

// ─── History & Stats ──────────────────────────────────────────────

// GET /api/v1/history — Get scan history
router.get('/api/v1/history', async (request, env) => {
  const url = new URL(request.url);
  const workspace = url.searchParams.get('workspace');
  const limit = parseInt(url.searchParams.get('limit') || '20');

  let query, params;
  if (workspace) {
    query = 'SELECT * FROM drift_scans WHERE workspace_name = ? ORDER BY scanned_at DESC LIMIT ?';
    params = [workspace, limit];
  } else {
    query = 'SELECT * FROM drift_scans ORDER BY scanned_at DESC LIMIT ?';
    params = [limit];
  }

  const scans = await env.DB.prepare(query).bind(...params).all();
  return json({ scans: scans.results });
});

// GET /api/v1/stats — Get aggregate stats
router.get('/api/v1/stats', async (request, env) => {
  const url = new URL(request.url);
  const days = parseInt(url.searchParams.get('days') || '7');
  const since = new Date(Date.now() - days * 86400000).toISOString();

  const stats = await env.DB.prepare(`
    SELECT
      COUNT(*) as total_scans,
      SUM(CASE WHEN has_drift = 1 THEN 1 ELSE 0 END) as scans_with_drift,
      SUM(total_items) as total_items,
      SUM(critical_count) as total_critical,
      ROUND(AVG(total_items), 1) as avg_items_per_scan
    FROM drift_scans
    WHERE scanned_at >= ?
  `).bind(since).first();

  return json({    period_days: days,
    ...stats,
  });
});

// ─── Webhook Endpoints ────────────────────────────────────────────

// POST /api/v1/webhook/github — GitHub webhook receiver
router.post('/api/v1/webhook/github', async (request, env) => {
  const signature = request.headers.get('x-hub-signature-256');
  const event = request.headers.get('x-github-event');
  const body = await request.text();

  // Verify signature (if secret is configured)
  if (env.GITHUB_WEBHOOK_SECRET && signature) {
    const encoder = new TextEncoder();
    const key = await crypto.subtle.importKey(
      'raw',
      encoder.encode(env.GITHUB_WEBHOOK_SECRET),
      { name: 'HMAC', hash: 'SHA-256' },
      false,
      ['verify']
    );
    const sigBytes = Uint8Array.from(
      signature.replace('sha256=', '').match(/.{1,2}/g).map(byte => parseInt(byte, 16))
    );
    const dataBytes = encoder.encode(body);
    const valid = await crypto.subtle.verify('HMAC', key, sigBytes, dataBytes);
    if (!valid) {
      return error('Invalid signature', 403);
    }
  }

  const payload = JSON.parse(body);

  // Handle events
  if (event === 'installation' && payload.action === 'created') {
    return json({ status: 'installed', installation_id: payload.installation?.id });
  }
  if (event === 'push') {
    return json({ status: 'received', repo: payload.repository?.full_name });
  }

  return json({ status: 'ignored', event });
});

// ─── Cron Trigger ─────────────────────────────────────────────────

// This runs on the schedule defined in wrangler.toml
async function handleCron(event, env) {
  // 1. Get all active workspaces
  const workspaces = await env.DB.prepare(
    'SELECT * FROM workspaces WHERE is_active = 1'
  ).all();

  // 2. For each workspace, run terraform plan and check for drift
  for (const ws of workspaces.results) {
    // In production: clone repo, run terraform plan, parse output
    // For now, log the scan
    console.log(`Scanning workspace: ${ws.name} at ${ws.path}`);
  }

  return json({ status: 'ok', scanned: workspaces.results.length });
}

// ─── 404 ──────────────────────────────────────────────────────────

router.all('*', () => error('Not found', 404));

// ─── Exports ──────────────────────────────────────────────────────

export default {
  async fetch(request, env, ctx) {
    return router.fetch(request, env, ctx);
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(handleCron(event, env));
  },
};