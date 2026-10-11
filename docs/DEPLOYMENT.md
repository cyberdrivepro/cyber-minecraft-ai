# Deployment

## Requirements

- Python 3.9+ (3.11 recommended), 2 GB RAM minimum (4 GB+ comfortable)
- Java 21 (17 for some older versions) for real Java server hosting and Fabric mod builds
- Open inbound port for the dashboard (default 7860) and a plan for game traffic (below)

## Linux VPS (systemd)

```bash
./scripts/install.sh            # interactive; installs deps, Java (optional), .env, DB
# choose the systemd option when prompted, then:
sudo systemctl status cyber-minecraft-ai
```

The service restarts on failure (`Restart=on-failure`), caps memory (`MemoryMax=2G`) and
logs to journald: `journalctl -u cyber-minecraft-ai -f`.

### TLS / reverse proxy (recommended)

```
server {
    server_name panel.example.com;
    location / {
        proxy_pass http://127.0.0.1:7860;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 3600s;            # keep SSE console streams alive
        proxy_buffering off;                 # required for SSE
    }
}
# + certbot --nginx for HTTPS
```

## Docker

```bash
cp .env.example .env     # configure tokens first
docker compose up -d --build
```

Data persists in the `cyber_data` named volume. For production on ephemeral hosts, mount
durable storage: `volumes: ["/mnt/nfs/cyber:/data"]`.

## Hugging Face Spaces

Push the repository to a Docker SDK Space. Set secrets in the Space settings
(`TELEGRAM_BOT_TOKEN`, `HF_TOKEN`, optional `ADMIN_TOKEN`). The Space health check is
`/health`. **Ephemeral disk warning:** anything written under `/data` may be lost on
rebuild — do not treat Spaces as durable hosting for worlds.

## Public Minecraft connectivity

A dashboard HTTPS URL does **not** accept game traffic. Java uses TCP, Bedrock UDP.
Options, in order of simplicity:

1. **Direct public IP** — the VPS has a public IP; open the port range
   (`SERVER_PORT_MIN..MAX`, default 25565–25600) in the firewall/security group and set
   `SERVER_PUBLIC_HOST=<your-ip-or-domain>`. The Networking tab diagnostics then verify
   DNS, port binding and TCP reachability for real.
2. **Domain** — point an `A` record at the host and use it as `SERVER_PUBLIC_HOST`.
3. **TCP/UDP tunnel** — when the host has no open inbound ports (home network, some
   clouds), run a tunnel that forwards raw TCP (Java) or UDP (Bedrock), e.g.
   [playit.gg](https://playit.gg), ngrok TCP (paid), or a self-hosted tunnel such as
   WireGuard/frp with a public relay. Configure the tunnel to target the allocated
   server port, then set the tunnel's public address as `SERVER_PUBLIC_HOST`.
4. **LAN play** — no public host needed; use the host's LAN IP shown in the Networking tab.

> The platform never opens firewall ports or changes system network config on its own;
> network changes always require explicit administrator action on the host.

## Provider adapters (MGROCK / Piggy & similar)

No public, documented API could be identified for providers referred to as "MG Rock" or
"Piggy". The platform therefore ships a **generic provider adapter** contract rather than
guessing endpoints. To activate a real integration you need, from the provider:

1. An official API base URL and authentication mechanism (API token / key)
2. Documented endpoints for: server create/start/stop/restart, console or log access,
   file/backup access, and address discovery
3. Their terms permitting API use

Implement the adapter in a new module under `servers/` following the runtime/manager
interfaces, register credentials only through environment variables, and expose a
connection-test action that must succeed before any provider resource is shown as
usable. Never scrape undocumented private APIs.

## Upgrade & rollback

```bash
./scripts/install.sh                      # re-run: upgrade-safe, preserves .env + data
python3 scripts/cyber-minecraft-ai backup <server_id>   # before major upgrades
git checkout <previous-tag-or-sha>        # rollback code
./scripts/uninstall.sh                    # removal without data loss
```

Database migrations are additive (`ALTER TABLE ADD COLUMN`) and applied automatically at
boot; rolling back code does not need a down-migration because columns are never dropped.
