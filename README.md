# CYBER MINECRAFT AI

**Build Mods. Host Worlds. Control Everything.**

Cyber Minecraft AI is a self-hostable platform that combines:

- **AI Mod Studio** — natural-language generation of Minecraft Bedrock add-ons (`.mcaddon`)
  and Java Fabric mods (`.jar`), with procedural textures, strict validation, automatic
  repair, immutable version history and conversational editing.
- **Real Minecraft server hosting** — create servers, upload real server software
  (server.jar / official Bedrock Dedicated Server), control the actual process with a live
  console, players, worlds, files, backups, schedules and networking diagnostics.
- **Aternos-style start queue** — resource-aware scheduling with per-user limits and honest
  runtime states (no fake "online" servers).
- **Multi-user accounts** — registration, sessions, roles, per-server sharing, audit log,
  admin control center.
- **Telegram bot** — mod building, server management and notifications from chat.

The platform is honest by design: features that need external infrastructure (a public IP,
a tunnel provider, an AI provider key) report exactly what is missing instead of pretending.

---

## Feature & support matrix

| Capability | Status | Notes |
|---|---|---|
| Bedrock add-on generation (`.mcaddon`) | ✅ | Deterministic build engine + validation |
| Fabric mod generation (`.jar`) | ✅ | Requires JDK 21 + Gradle on the host for real compilation |
| Conversational mod editing (v1, v2, v3…) | ✅ | Immutable versions, targeted edits |
| Procedural texture / asset generation | ✅ | 16×16 / 32×32 PNG, palettes |
| AI providers | ✅ | Local HF model, HF Inference, Groq, OpenRouter, custom OpenAI-compatible |
| Web dashboard (dark/light, mobile) | ✅ | Overview, servers, AI studio, system, admin, docs |
| Multi-user accounts & sessions | ✅ | PBKDF2 passwords, server-side sessions, admin bootstrap |
| Per-server sharing & roles | ✅ | viewer / moderator / admin; enforced server-side |
| Server lifecycle (create/start/stop/restart/delete) | ✅ | State machine + durable state |
| Real Java server runtime | ✅ | Launches uploaded `server.jar`, streams real console |
| Real Bedrock runtime | ✅ | Runs uploaded official `bedrock_server` binary (UDP) |
| Embedded console runtime (no jar uploaded) | ✅ | Real files/state; **cannot** accept game clients — clearly labelled |
| Console streaming | ✅ | Server-Sent Events, authenticated per server |
| Players (ops / whitelist / bans) | ✅ | Console-driven online, state-file driven offline |
| Worlds (import/export/activate/delete) | ✅ | Java & Bedrock folders; no format conversion claims |
| File manager (browse/edit/upload/delete) | ✅ | Path-traversal-safe, .bak backups on sensitive writes |
| Backups & restore | ✅ | Manual, auto-on-stop, retention limit, checksummed zips |
| Schedules | ✅ | Durable DB-backed (backup/restart/stop/start/save/command) |
| Networking diagnostics | ✅ | Real DNS, TCP, port-bind checks; honest "unavailable" states |
| Secure download links | ✅ | Random tokens, expiry, download limits, revocation |
| Telegram bot | ✅ | Hosting + mod commands; account identity = Telegram ID |
| Admin center | ✅ | Users, inventory, audit log, role management |
| Public game networking (port forwarding/tunnels) | ⚠️ | Diagnostics + guidance only; needs your public IP/tunnel (see docs/DEPLOYMENT.md) |
| DNS provider integrations | ❌ | Requires provider credentials; not bundled |
| MGROCK / Piggy hosting adapters | ❌→⚠️ | No public API could be identified; generic adapter documented in docs/DEPLOYMENT.md |
| Forge/NeoForge/Quilt/Spigot/Purpur servers | ⚠️ | Catalogued with requirements; run via uploaded jar like other Java servers |

---

## Quick start

### Linux (Ubuntu / Debian and compatible)

```bash
git clone https://github.com/cyberdrivepro/cyber-minecraft-ai.git
cd cyber-minecraft-ai
chmod +x scripts/install.sh
./scripts/install.sh
```

The installer creates `.env`, a virtualenv, installs dependencies (optionally Java 21),
initializes the database and can install a systemd service. It is safe to re-run for upgrades.

### Windows (PowerShell)

```powershell
git clone https://github.com/cyberdrivepro/cyber-minecraft-ai.git
cd cyber-minecraft-ai
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install.ps1
```

### Docker

```bash
docker compose up -d --build
```

> **Hugging Face Spaces note:** the Space builds with the provided `Dockerfile`.
> Container-local disk does not survive rebuilds on ephemeral hosts — mount durable
> storage for production worlds and backups.

### First login

On first boot the platform creates an **admin** account. If `ADMIN_PASSWORD` is not set,
generated credentials are written to `data/admin_credentials.txt` (permissions 0600).
Sign in at `http://127.0.0.1:7860`, then change the password pattern by recreating the
account or setting `ADMIN_PASSWORD` before first boot. Registration is open by default
(`ALLOW_REGISTRATION=true`); disable it for private installs.

---

## CLI

```bash
python3 scripts/cyber-minecraft-ai doctor        # environment validation
python3 scripts/cyber-minecraft-ai start         # background start (PID file)
python3 scripts/cyber-minecraft-ai status        # app health + server list
python3 scripts/cyber-minecraft-ai logs <srv_id> # server console tail
python3 scripts/cyber-minecraft-ai backup <srv_id>
python3 scripts/cyber-minecraft-ai restore <srv_id> <backup_id>
python3 scripts/cyber-minecraft-ai diagnose <srv_id>
python3 scripts/cyber-minecraft-ai stop
python3 scripts/cyber-minecraft-ai update
```

API-based commands require `ADMIN_TOKEN` to be set in `.env` (they authenticate with the
`X-Admin-Token` header over localhost).

---

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — modules, data flow, state machine
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — VPS, Docker, HF Spaces, public networking, tunnels
- [`docs/SECURITY.md`](docs/SECURITY.md) — auth model, threat mitigations, secrets handling
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) — common failures and fixes
- [`docs/UPGRADE-MATRIX.md`](docs/UPGRADE-MATRIX.md) — the 5,000-objective upgrade registry with honest statuses
- [`docs/upgrade-objectives.json`](docs/upgrade-objectives.json) — machine-readable registry

## Configuration reference

All configuration lives in `.env` (see `.env.example` with placeholder values only):

| Variable | Default | Purpose |
|---|---|---|
| `PORT` / `HOST` | 7860 / 0.0.0.0 | HTTP bind |
| `TELEGRAM_BOT_TOKEN` | empty | Enables the Telegram bot (polling) |
| `AI_PROVIDER` | `local` | `local`, `huggingface_inference`, `groq`, `openrouter`, `custom_openai` |
| `LOCAL_MODEL_ID` | Qwen2.5-Coder-1.5B | Local HF model (loads on demand) |
| `GROQ_API_KEY` / `OPENROUTER_API_KEY` / `OPENAI_API_KEY` | empty | External provider keys (server-side only) |
| `AUTH_REQUIRED` | `true` | Web session enforcement (keep `true` for anything public) |
| `ALLOW_REGISTRATION` | `true` | Open account registration |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | admin / generated | Bootstrap admin credentials |
| `ADMIN_TOKEN` | generated | CLI / API management token (X-Admin-Token) |
| `MAX_SERVERS_PER_OWNER` | 10 | Per-user server quota |
| `MAX_CONCURRENT_SERVERS` | 2 | Start-queue concurrency slots |
| `SERVER_PORT_MIN/MAX` | 25565–25600 | Port allocation range |
| `SERVER_RAM_MB` | 1024 | Default RAM per server |
| `MAX_BACKUPS_PER_SERVER` | 5 | Backup retention |
| `SERVER_IDLE_SHUTDOWN_MINUTES` | 0 (off) | Idle auto-shutdown |
| `SERVER_PUBLIC_HOST` | hostname | Public hostname players connect to |
| `DATA_DIR` | ./data | All durable state (database, worlds, backups, artifacts) |
| `DOWNLOAD_TOKEN_TTL_HOURS` | 24 | Download link expiry |

## Testing

```bash
pip install -r requirements-dev.txt   # skips heavy torch extras if you trim them
pytest tests/ -v
flake8 . --select=E9,F63,F7,F82       # critical gate
python3 scripts/generate_objectives.py --check
```

CI (`.github/workflows/ci.yml`) runs lint, the full test matrix (3.9/3.11/3.12), shell and
PowerShell installer syntax checks, the CLI doctor, the objective-registry integrity check
and the Docker build.

## Uninstall

```bash
./scripts/uninstall.sh            # keep your data (worlds, backups, db)
./scripts/uninstall.sh --purge    # delete everything (asks for confirmation)
```

## Known limitations

- Without an uploaded `server.jar` (or the official Bedrock zip), a server runs the
  **embedded console runtime**: it manages real world/state files and the documented
  console commands, but Minecraft clients cannot join. The dashboard says so explicitly.
- A website URL (HTTPS) is not a Minecraft connection. Public play needs a real host:port
  or a TCP/UDP tunnel — see `docs/DEPLOYMENT.md`.
- Java worlds and Bedrock worlds are separate formats; the platform never claims conversion.
- On ephemeral hosting (HF Spaces), local disk is not durable without external storage.
