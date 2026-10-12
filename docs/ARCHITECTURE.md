# Architecture

## Overview

Cyber Minecraft AI is a single-process FastAPI application (Python 3.9+) with an optional
Telegram bot, a deterministic mod-build engine and a Minecraft server hosting manager.
State is durable in SQLite (default) or PostgreSQL via SQLAlchemy; large binaries (worlds,
backups, artifacts) live on the filesystem under `DATA_DIR`.

```
┌────────────────────────── FastAPI app (app.py) ─────────────────────────┐
│  lifespan: init_db → bootstrap_admin → build workers                    │
│            → server_manager.startup → scheduler.startup → telegram bot  │
├────────────────────┬───────────────────────┬────────────────────────────┤
│ web/routes.py      │ web/routes_servers.py │ bot/ (aiogram 3)           │
│ pages + auth + AI  │ hosting API + SSE     │ handlers, keyboards        │
├────────────────────┴───────────────────────┴────────────────────────────┤
│ core/auth.py (sessions, PBKDF2, ACL, audit)  core/tokens.py (downloads) │
│ core/security.py (path safety, zip-slip, zip bombs)                     │
├──────────────────────────────────────────────────────────────────────────┤
│ servers/manager.py — lifecycle state machine, queue, backups, files      │
│ servers/runtime.py — EmbeddedRuntime | JavaProcessRuntime | Bedrock     │
│ servers/scheduler.py — durable DB-backed task runner                    │
│ servers/networking.py — real DNS/TCP/bind diagnostics                   │
├──────────────────────────────────────────────────────────────────────────┤
│ ai/ (planner, model_manager, repair) builders/ (bedrock, fabric)        │
│ assets/ (textures, audio) jobs/ (queue, runner)                         │
├──────────────────────────────────────────────────────────────────────────┤
│ storage/ — SQLAlchemy models, additive migrations, sessions             │
└──────────────────────────────────────────────────────────────────────────┘
```

## Server lifecycle state machine

States: `offline → queued → preparing → starting → online`, `online → stopping → offline`,
failures land in `error`, `queued` can be cancelled. Transitions persist in the `servers`
table; on startup the manager resets stale non-offline rows ("reconcile after restart") and
never reports ONLINE before the runtime passes its readiness check (Java: `Done (` marker
in process output; Bedrock: `Server started`; embedded: lifecycle completed).

## Runtime adapters

- **EmbeddedRuntime** — in-process implementation of the vanilla server directory layout
  and the documented console command set against real files (world folder, ops/whitelist/
  bans JSON, server.properties). It does **not** speak the Minecraft protocol; the UI
  labels it clearly and asks for a real jar for actual hosting.
- **JavaProcessRuntime** — spawns `java -Xmx… -jar server.jar nogui` inside the server
  directory, streams stdout to the console buffer and log file, writes commands to stdin,
  stops gracefully (`stop` → SIGTERM → SIGKILL ladder).
- **BedrockProcessRuntime** — same contract for the official `bedrock_server` binary
  extracted from the official BDS zip.

## Authorization model

- Sessions: opaque 32-byte tokens in an HttpOnly cookie (`cyber_session`), stored
  server-side (`user_sessions`) with expiry.
- Passwords: PBKDF2-HMAC-SHA256, 120k iterations, per-user salt.
- Roles: platform `admin` vs `user`; per-server roles `owner > admin > moderator > viewer`
  via `server_shares`. All checks happen in `core/auth.py` and are enforced on every
  server API route (404, not 403, to avoid resource enumeration).
- CLI: `X-Admin-Token` header compared against `ADMIN_TOKEN` in constant time.
- Audit: security-relevant actions land in `audit_events`.

## Scheduler

`servers/scheduler.py` polls the `schedules` table every 30 s. Schedules are interval- or
daily-based, run through the ServerManager (so they inherit authorization semantics), keep
per-schedule in-flight markers to prevent overlap, write run history to `schedule_runs`,
and reschedule the next run from the persisted last-run time (restart-safe).

## Persistence & migrations

`storage/database.py` creates all tables and applies a small additive migration list
(`ALTER TABLE ADD COLUMN` for columns added after the initial schema). It never drops or
rewrites columns; destructive schema changes are avoided by design. Binary data stays on
disk — the database holds metadata and references only.

## Real-time events

Console output streams to authorized clients via SSE
(`/api/servers/{id}/console/stream`): a 1 s poll of the in-memory bounded ring buffer
(500 lines) plus a log-file copy on disk (`logs/latest.log`). SSE was chosen over
WebSockets for zero extra dependencies and simple cookie-authenticated browser use.

## Frontend

Server-rendered Jinja templates with a shared layout (collapsible sidebar, persistent
server actions, dark/light theme in localStorage) and vanilla-JS islands that call the
same JSON APIs the CLI and tests use. No build step, no framework lock-in.

## Build engine (mods)

`ai/planner.py` converts natural language to a Pydantic-validated spec; `builders/`
produces Bedrock `.mcaddon` or Fabric `.jar` artifacts through deterministic templates;
`jobs/queue.py` bounds concurrency (`MAX_CONCURRENT_BUILDS`); `ai/repair_agent.py`
performs up to `MAX_REPAIR_ATTEMPTS` self-repair cycles. Version history is immutable.
