// Motio Office — event server.
// Ingests hook events + transcripts from Claude Code threads, GitHub PR webhooks,
// derives an Overview-style state per thread and streams it to the 3D office over WebSocket.

import express from 'express';
import { WebSocketServer } from 'ws';
import { createServer } from 'node:http';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseLine, titleFrom } from './transcript.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 8787);
const INGEST_TOKEN = process.env.OFFICE_TOKEN || '';        // used by the hook
const VIEW_TOKEN = process.env.VIEW_TOKEN || '';            // used by the browser
const GH_SECRET = process.env.GITHUB_WEBHOOK_SECRET || '';  // optional
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, 'data');
const WEB_DIR = process.env.WEB_DIR || path.join(__dirname, '..', 'web');
const STALE_WORKING_MS = 20 * 60e3;  // "working" with no news for 20 min → idle
const RESOLVE_AFTER_MS = 7 * 24 * 3600e3;

if (!INGEST_TOKEN || !VIEW_TOKEN) {
  console.error('Set OFFICE_TOKEN (for the hook) and VIEW_TOKEN (for the browser).');
  process.exit(1);
}
fs.mkdirSync(path.join(DATA_DIR, 'logs'), { recursive: true });

// ---------- state ----------
const STATE_FILE = path.join(DATA_DIR, 'sessions.json');
/** @type {Record<string, any>} */
let sessions = {};
try { sessions = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')); } catch {}
let saveTimer = null;
const save = () => {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => fs.writeFile(STATE_FILE, JSON.stringify(sessions), () => {}), 500);
};

function effectiveState(s, now = Date.now()) {
  const pr = s.pr;
  if (pr?.state === 'merged' || pr?.state === 'closed' || s.resolved) return 'resolved';
  if (now - s.lastEventAt > RESOLVE_AFTER_MS) return 'resolved';
  if (s.raw === 'waiting') return 'waiting';
  if (s.raw === 'working' && now - s.lastEventAt < STALE_WORKING_MS) return 'working';
  if (pr?.state === 'open' && (pr.approved || pr.autoMerge)) return 'landing';
  if (pr?.state === 'open') return 'review';
  return 'idle';
}
const view = (s) => ({ ...s, state: effectiveState(s) });
// Titles saved before envelope unwrapping existed start with '<'; let them be replaced.
const needsTitle = (s) => !s.title || s.title.startsWith('<');

function upsert(sid, project) {
  if (!sessions[sid]) {
    sessions[sid] = {
      id: sid, project: project || 'Motio', title: null, raw: 'idle', where: null, branch: null,
      host: null, lastTool: null, lastDetail: null, lastMessage: null, toolCount: 0, subagents: 0,
      startedAt: Date.now(), lastEventAt: Date.now(), logBytes: 0, logEntries: 0, pr: null, resolved: false,
    };
  }
  return sessions[sid];
}

// ---------- websocket ----------
const app = express();
const server = createServer(app);
const wss = new WebSocketServer({ noServer: true });
const broadcast = (msg) => {
  const data = JSON.stringify(msg);
  for (const c of wss.clients) if (c.readyState === 1) c.send(data);
};
server.on('upgrade', (req, socket, head) => {
  const url = new URL(req.url, 'http://x');
  if (url.pathname !== '/ws' || url.searchParams.get('key') !== VIEW_TOKEN) return socket.destroy();
  wss.handleUpgrade(req, socket, head, (ws) => {
    ws.send(JSON.stringify({ type: 'snapshot', sessions: Object.values(sessions).map(view) }));
  });
});
// Re-evaluate time-based states (stale → idle, old → resolved) once a minute.
setInterval(() => broadcast({ type: 'snapshot', sessions: Object.values(sessions).map(view) }), 60e3);

// ---------- auth helpers ----------
const safeEq = (a, b) => a.length === b.length && crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b));
const ingestAuth = (req, res, next) =>
  safeEq(req.get('authorization') || '', `Bearer ${INGEST_TOKEN}`) ? next() : res.sendStatus(401);
const viewAuth = (req, res, next) =>
  safeEq(String(req.query.key || req.get('x-office-key') || ''), VIEW_TOKEN) ? next() : res.sendStatus(401);
const validSid = (sid) => /^[A-Za-z0-9_-]{6,128}$/.test(sid);

// ---------- ingest: hook events ----------
app.post('/api/event', ingestAuth, express.json({ limit: '64kb' }), (req, res) => {
  const e = req.body || {};
  if (!validSid(e.session_id || '')) return res.sendStatus(400);
  const s = upsert(e.session_id, e.project);
  s.lastEventAt = Date.now();
  s.where = e.where || s.where;
  s.host = e.host || s.host;
  if (e.branch) s.branch = e.branch;
  switch (e.event) {
    case 'SessionStart':
      s.raw = 'working'; s.resolved = false; break;
    case 'UserPromptSubmit':
      s.raw = 'working';
      if (needsTitle(s)) s.title = titleFrom(e.prompt) || s.title;
      s.lastMessage = e.prompt; break;
    case 'PreToolUse':
      s.raw = 'working'; s.lastTool = e.tool; s.lastDetail = e.detail; s.toolCount++;
      if (e.tool === 'Task' || e.tool === 'Agent') s.subagents++;
      break;
    case 'PostToolUse':
      s.raw = 'working'; // also clears 'waiting' once an approval went through
      break;
    case 'SubagentStop':
      s.subagents = Math.max(0, s.subagents - 1); break;
    case 'Notification': {
      const m = (e.message || '').toLowerCase();
      const perm = e.notification_type === 'permission_prompt' || m.includes('permission') || m.includes('approv');
      s.raw = perm ? 'waiting' : 'idle';
      s.lastMessage = e.message; break;
    }
    case 'Stop':
      s.raw = 'idle'; s.subagents = 0; break;
    case 'SessionEnd':
      s.raw = 'idle'; s.subagents = 0; break;
  }
  save();
  broadcast({ type: 'session', session: view(s), event: { name: e.event, tool: e.tool, detail: e.detail } });
  res.sendStatus(204);
});

// ---------- ingest: transcript chunks ----------
app.post('/api/log/:sid', ingestAuth, express.raw({ type: '*/*', limit: '4mb' }), (req, res) => {
  const sid = req.params.sid;
  if (!validSid(sid)) return res.sendStatus(400);
  const s = upsert(sid);
  let buf = Buffer.isBuffer(req.body) ? req.body : Buffer.alloc(0);
  const offset = Number(req.query.offset || 0);
  if (req.query.reset === '1' && s.logBytes > 0) {
    // The transcript file shrank on the thread's side (rewritten): keep the old copy, start fresh.
    try { fs.renameSync(logPath(sid), logPath(sid) + `.${Date.now()}.old`); } catch {}
    s.logBytes = 0; s.logEntries = 0;
    broadcast({ type: 'logreset', sid });
  } else if (offset < s.logBytes) {
    // Idempotency: the hook re-sent bytes we already have (e.g. lost its offset file) — drop the overlap.
    const overlap = s.logBytes - offset;
    if (overlap >= buf.length) return res.sendStatus(204);
    buf = buf.subarray(overlap);
  }
  fs.appendFileSync(logPath(sid), buf);
  s.logBytes += buf.length;
  const entries = buf.toString('utf8').split('\n').filter(Boolean).flatMap(parseLine);
  const start = s.logEntries;
  s.logEntries += entries.length;
  if (needsTitle(s)) {
    const firstUser = entries.find((x) => x.kind === 'user');
    if (firstUser) s.title = titleFrom(firstUser.text) || s.title;
  }
  save();
  if (entries.length) broadcast({ type: 'log', sid, start, entries });
  res.sendStatus(204);
});
const logPath = (sid) => path.join(DATA_DIR, 'logs', `${sid}.jsonl`);

// ---------- ingest: GitHub pull request webhooks ----------
app.post('/api/github', express.raw({ type: '*/*', limit: '2mb' }), (req, res) => {
  if (GH_SECRET) {
    const sig = req.get('x-hub-signature-256') || '';
    const want = 'sha256=' + crypto.createHmac('sha256', GH_SECRET).update(req.body).digest('hex');
    if (!safeEq(sig, want)) return res.sendStatus(401);
  }
  let p;
  try { p = JSON.parse(req.body.toString('utf8')); } catch { return res.sendStatus(400); }
  const kind = req.get('x-github-event');
  const pr = p.pull_request;
  if (!pr || !['pull_request', 'pull_request_review'].includes(kind)) return res.sendStatus(204);
  const matches = Object.values(sessions).filter((s) => s.branch && s.branch === pr.head?.ref);
  for (const s of matches) {
    const prev = s.pr || {};
    s.pr = {
      number: pr.number, url: pr.html_url, title: pr.title,
      state: pr.merged ? 'merged' : pr.state, // open | closed | merged
      approved: kind === 'pull_request_review' ? (p.review?.state === 'approved' || prev.approved) : !!prev.approved,
      autoMerge: !!pr.auto_merge,
    };
    if (kind === 'pull_request_review' && p.review?.state === 'changes_requested') s.pr.approved = false;
    save();
    broadcast({ type: 'session', session: view(s), event: { name: 'PullRequest', detail: `#${pr.number} ${s.pr.state}` } });
  }
  res.sendStatus(204);
});

// ---------- read API for the browser ----------
app.get('/api/state', viewAuth, (_req, res) => res.json(Object.values(sessions).map(view)));

app.get('/api/log/:sid', viewAuth, (req, res) => {
  const sid = req.params.sid;
  if (!validSid(sid) || !fs.existsSync(logPath(sid))) return res.json({ start: 0, entries: [] });
  const all = fs.readFileSync(logPath(sid), 'utf8').split('\n').filter(Boolean).flatMap(parseLine);
  const tail = Math.min(Number(req.query.tail || 400), 2000);
  const start = Math.max(0, all.length - tail);
  res.json({ start, total: all.length, entries: all.slice(start) });
});

// Mark a thread resolved / reopen it by hand from the office.
app.post('/api/session/:sid/resolve', viewAuth, express.json(), (req, res) => {
  const s = sessions[req.params.sid];
  if (!s) return res.sendStatus(404);
  s.resolved = req.body?.resolved !== false;
  if (!s.resolved) {
    s.lastEventAt = Date.now();
    if (s.pr && s.pr.state !== 'open') s.pr = null; // a merged/closed PR would otherwise keep it resolved
  }
  save();
  broadcast({ type: 'session', session: view(s) });
  res.sendStatus(204);
});

// The page is authored as a body fragment (so the same file also publishes as a Claude artifact);
// wrap it in a document here.
app.get(['/', '/index.html'], (_req, res) => {
  const page = fs.readFileSync(path.join(WEB_DIR, 'index.html'), 'utf8');
  res.type('html').send(`<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>*{box-sizing:border-box}body{margin:0}[hidden]{display:none!important}:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}</style>
</head><body>${page}</body></html>`);
});
app.use(express.static(WEB_DIR));
server.listen(PORT, () => console.log(`Motio Office on http://localhost:${PORT}  (open /?key=VIEW_TOKEN)`));
