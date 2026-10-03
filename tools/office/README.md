# Motio Office

A 3D office at **https://office.flowitup.com** where each thread of the Motio project (Claude → Code → Projects) is an employee. Click one to read its live log. Without a view key the page shows demo data.

| Thread state | In the office |
|---|---|
| Working | Seated and typing, green desk ring |
| Waiting on you | Hand up, "Needs you" bubble |
| Ready for review / Landing | Queues at the coordinator desk with a folder |
| Idle | Coffee corner |
| Resolved | Desk hidden ("Show resolved desks" brings it back) |
| Subagents | Small figures next to the desk |

## How the data gets there

`.claude/hooks/office_hook.py` runs on every thread's hook events (next to `thread_log.py`). It posts the event to `POST /api/event` and the new transcript lines to `POST /api/log/<session>`. It does nothing unless `OFFICE_URL` is set, uses only the standard library, and always exits 0.

The coordinator conversation doesn't run repo hooks, so its desk has no log.

## Cloud environment (Project settings → Environment)

- **Environment variable:** `OFFICE_URL=https://office.flowitup.com`
- **API credential:** `Bearer <OFFICE_TOKEN>` for `office.flowitup.com` (same mechanism as the Slack bot token, so sessions never see it)
- **Network access:** allow `office.flowitup.com`

New threads pick this up; running threads keep their old settings. For local threads, export `OFFICE_URL` and `OFFICE_TOKEN` where `claude remote-control` runs.

## Server

Runs on `folio-prod-1` (Hetzner) in `/opt/motio-office`, bound to `127.0.0.1:8787`. The Cloudflare tunnel `flowitup-folio-prod` routes `office.flowitup.com` to it (ingress rule in `/etc/cloudflared/config.yml`, before the catch-all).

Tokens live in `/opt/motio-office/.env` (mode 600): `OFFICE_TOKEN` (hook, write-only), `VIEW_TOKEN` (browser: `https://office.flowitup.com/?key=<VIEW_TOKEN>`), optional `GITHUB_WEBHOOK_SECRET`.

Update after a change in `tools/office/`:

```bash
rsync -a --delete --exclude .env --exclude node_modules tools/office/ folio-prod:/opt/motio-office/
ssh folio-prod 'cd /opt/motio-office && docker compose up -d --build'
```

### Pull request states (optional)

GitHub → flowitup/motio → Settings → Webhooks: payload URL `https://office.flowitup.com/api/github`, content type JSON, secret = `GITHUB_WEBHOOK_SECRET`, events **Pull requests** and **Pull request reviews**. PRs are matched to threads by branch.

## API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/event` | `Bearer OFFICE_TOKEN` | Hook event |
| POST | `/api/log/:session?offset=N[&reset=1]` | `Bearer OFFICE_TOKEN` | Transcript bytes, idempotent by offset |
| POST | `/api/github` | GitHub signature | PR webhooks |
| GET | `/api/state?key=` | `VIEW_TOKEN` | All threads |
| GET | `/api/log/:session?key=&tail=400` | `VIEW_TOKEN` | Parsed log |
| POST | `/api/session/:session/resolve?key=` | `VIEW_TOKEN` | `{ "resolved": true \| false }` |
| WS | `/ws?key=` | `VIEW_TOKEN` | `snapshot`, `session`, `log`, `logreset` |

Transcripts contain code and command output, so keep `VIEW_TOKEN` private.
