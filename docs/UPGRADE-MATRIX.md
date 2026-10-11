# Cyber Minecraft AI — Upgrade Objective Matrix

Machine-readable registry: `docs/upgrade-objectives.json` (UPG-0001 … UPG-5000).
Regenerate with `python3 scripts/generate_objectives.py`.

**Honest status summary:**

| Status | Count |
|---|---|
| VERIFIED | 433 |
| IMPLEMENTED | 61 |
| NOT_STARTED | 4470 |
| BLOCKED | 36 |

> VERIFIED = covered by the automated test suite in `tests/`.
> IMPLEMENTED = working in this codebase, verified manually or in live flows.
> NOT_STARTED = specified but not built in this repository — the platform is
> honest about what it does not do. BLOCKED = requires external infrastructure
> or credentials (documented per-area).

## Progress by area

| Area | Done | Total |
|---|---|---|
| Architecture and maintainability | 33 | 100 |
| Frontend design and navigation | 25 | 100 |
| Dashboard and server cards | 32 | 100 |
| Authentication and user accounts | 36 | 100 |
| Server ownership and permissions | 46 | 100 |
| Operating-system compatibility | 2 | 100 |
| Linux installers | 5 | 100 |
| Windows installers | 4 | 100 |
| Docker deployment | 4 | 100 |
| CLI and diagnostics | 6 | 100 |
| Java runtime management | 2 | 100 |
| Bedrock runtime management | 21 | 100 |
| Server software catalog | 3 | 100 |
| Server lifecycle | 17 | 100 |
| Console and command execution | 21 | 100 |
| Player management | 26 | 100 |
| World management | 31 | 100 |
| File management | 1 | 100 |
| Mods and loaders | 0 | 100 |
| Plugins | 0 | 100 |
| Modpacks | 0 | 100 |
| Resource packs | 16 | 100 |
| Backups and restoration | 26 | 100 |
| Scheduled tasks | 30 | 100 |
| Public networking | 0 | 100 |
| Domains and DNS integrations | 0 | 100 |
| TCP and UDP connectivity | 0 | 100 |
| Tunnel providers | 0 | 100 |
| MGROCK/Piggy adapter framework | 0 | 100 |
| Queue and resource scheduling | 0 | 100 |
| AI mod planning | 0 | 100 |
| Deterministic build engine | 0 | 100 |
| Conversational editing | 0 | 100 |
| Java build validation | 0 | 100 |
| Bedrock add-on validation | 0 | 100 |
| Asset Studio | 0 | 100 |
| AI model management | 0 | 100 |
| Provider routing | 0 | 100 |
| Telegram integration | 0 | 100 |
| Admin dashboard | 0 | 100 |
| Database and migrations | 26 | 100 |
| Artifact and object storage | 20 | 100 |
| API contracts | 16 | 100 |
| Real-time events | 10 | 100 |
| Observability | 0 | 100 |
| Security hardening | 4 | 100 |
| Performance and resource limits | 2 | 100 |
| CI/CD and automated testing | 21 | 100 |
| Documentation and troubleshooting | 5 | 100 |
| Recovery, reliability and release management | 3 | 100 |

## Verification evidence

- Automated: `pytest tests/` (see `deploy/workflows/ci.yml`).
- CLI: `python3 scripts/cyber-minecraft-ai doctor`.
- Manual flows: documented in `docs/DEPLOYMENT.md` and the final report.

The registry is generated from 50 areas × 20 requirement topics × 5 quality
dimensions (functional, edge-case, authorization, durability, observability),
giving every objective a distinct requirement, acceptance criterion and
verification method. Statuses reflect the actual repository state.
