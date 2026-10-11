# Troubleshooting

## Installation

| Symptom | Cause | Fix |
|---|---|---|
| `python3-venv is missing` | Debian/Ubuntu base image | `sudo apt-get install python3-venv python3-pip` and re-run |
| `pip install` fails on torch | Very small disk / old pip | The platform works without local AI models (heuristic planner). Trim `torch`, `transformers`, `accelerate` from requirements or upgrade pip first |
| `Java not found` in doctor | JDK missing | Install Temurin 21 (`apt install openjdk-21-jdk-headless`, winget, or adoptium.net) and re-run `doctor` |
| Service not active after install | App error at boot | `journalctl -u cyber-minecraft-ai -n 50` |

## Startup & runtime

| Symptom | Cause | Fix |
|---|---|---|
| Dashboard shows "embedded console runtime" in console | No `server.jar` uploaded | Upload real server software on the server page (Java `.jar` or Bedrock official `.zip`); the console banner also explains this |
| Start fails with "Java runtime not found" | Java missing / `JAVA_HOME` wrong | Install Java or set `JAVA_HOME` in `.env`, restart the app |
| "Server did not reach online state within 150s" | Jar incompatible with Java version | Use the Java version required by your Minecraft version (catalog shows it) |
| `Address field empty` after start | Server failed or was stopped | Check console output and `status_detail` on the server page |
| Port conflict at boot | Port range exhausted / reserved | Widen `SERVER_PORT_MIN..MAX` or free ports |

## Networking

| Symptom | Cause | Fix |
|---|---|---|
| Friends cannot connect, diagnostics show "DNS resolution failed" | `SERVER_PUBLIC_HOST` unset or DNS not pointing here | Set the real public hostname/IP in `.env`, create the DNS record |
| TCP reachability "Connection refused" | Server offline or firewall rejects | Start the server; open the port in the firewall/security group |
| TCP reachability "Timed out" | Port filtered (cloud security group, NAT) | Open the port range; consider a TCP tunnel (docs/DEPLOYMENT.md) |
| Web works but game does not | HTTPS URL used as game address | Use the `host:port` from the Networking tab — Minecraft does not connect to websites |
| Bedrock friends cannot connect | Bedrock needs UDP | Forward UDP (not TCP) for the Bedrock port, or use a UDP-capable tunnel |

## Console & players

| Symptom | Cause | Fix |
|---|---|---|
| `list` always shows 0 players with embedded runtime | No real protocol server | Expected without an uploaded jar — the console is command-compatible, not a game server |
| Ops added offline don't appear online | Offline edits write state files consumed at next boot | Expected; changes apply on next start |
| SSE console stops updating | Reverse proxy buffering | Set `proxy_buffering off;` (see DEPLOYMENT.md) |

## Backups & data

| Symptom | Cause | Fix |
|---|---|---|
| Restore refuses | Server is online | Stop the server first (restore replaces the live world) |
| Backup file missing on disk | Data directory moved/deleted | Backups live under `DATA_DIR/servers/<id>/backups`; keep `DATA_DIR` durable |
| World import rejected | Not a world archive (no `level.dat`/`db`/`levelname.txt`) | Zip the world folder itself, not loose files; Java and Bedrock worlds must be imported separately |

## Telegram

| Symptom | Cause | Fix |
|---|---|---|
| Bot silent | Token missing/wrong | Set `TELEGRAM_BOT_TOKEN` from @BotFather, restart |
| Bot commands 404-ish errors | App behind proxy without polling access | Polling needs outbound HTTPS to api.telegram.org; allow it |

## Diagnostics tooling

```bash
python3 scripts/cyber-minecraft-ai doctor            # environment
python3 scripts/cyber-minecraft-ai status            # app + servers
python3 scripts/cyber-minecraft-ai diagnose <srv_id> # network checks
curl -s localhost:7860/health | python3 -m json.tool
```
