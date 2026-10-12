# Security

## Authentication

- **Passwords** — PBKDF2-HMAC-SHA256 with 120,000 iterations and a 16-byte random salt
  per user (`core/auth.py::hash_password`). Verification is constant-time (`hmac.compare_digest`).
- **Sessions** — 32-byte URL-safe random tokens, HttpOnly + SameSite=Lax cookies, stored
  server-side with a 7-day expiry; logout deletes the row. Session tokens never appear in
  logs or API responses.
- **Bootstrap admin** — created on first boot from `ADMIN_USERNAME`/`ADMIN_PASSWORD` or
  generated and written once to `data/admin_credentials.txt` (chmod 600). The file is
  documented for removal after first login.
- **Login rate limiting** — 10 failed attempts per client IP per 15 minutes (in-memory),
  plus failed-login audit events.
- **CLI trust path** — the `X-Admin-Token` header is compared against `ADMIN_TOKEN` in
  constant time; it grants the same platform-admin power as an admin session and is meant
  for localhost tooling. Keep `ADMIN_TOKEN` secret.

## Authorization

- Every `/api/servers/*` route resolves the caller's effective role
  (`owner > admin > moderator > viewer`) through `core/auth.py::server_role`, which is
  enforced server-side — hiding buttons in the UI is not the security boundary.
- Unauthorized object access returns **404** (not 403) so IDs cannot be enumerated.
- Cross-user isolation is covered by `tests/test_auth_acl.py` (list, read, console,
  start, delete, backups, artifact downloads).

## Input safety

- **Path traversal** — all filesystem operations funnel through
  `core/security.py::validate_safe_path` (canonical `resolve()` + `relative_to`).
- **Zip Slip / zip bombs** — `safe_extract_zip` rejects absolute/escaping member paths,
  caps member count (2000) and total uncompressed size (100 MB).
- **Command injection** — user commands go only to the Minecraft server stdin; the
  platform never passes user input to an OS shell. Uploaded jars run as child processes
  of the app with the operator's explicit consent (they uploaded the jar).
- **Upload limits** — server software and world archives are capped
  (`SERVER_JAR_MAX_MB`), streamed in 1 MB chunks; only `.jar` (Java) or `.zip` (Bedrock)
  are accepted by type.
- **Text editor** — only whitelisted text suffixes, ≤512 KB, UTF-8 validated; previous
  versions are backed up as `.bak` before overwriting.

## Download links

Private artifacts (backups, worlds) are shared through opaque tokens
(`core/tokens.py`): random 24-byte URL-safe strings, server-side expiry, optional
download-count limits, revocation restricted to the link owner (audited). Public URLs
never embed user IDs, filesystem paths or credentials. Token misuse is bounded by expiry.

## Secrets handling

- Secrets (bot token, provider API keys, `ADMIN_TOKEN`, `ADMIN_PASSWORD`) come from the
  environment / `.env` only; they are never returned by any API route (provider status
  endpoints expose booleans only) and never logged.
- `.env.example` contains placeholders only.
- The database stores password hashes and session tokens, never raw passwords or
  provider keys.

## Transport & headers

Deployments behind a reverse proxy should terminate TLS and add standard headers
(HSTS, CSP). See `docs/DEPLOYMENT.md` for a reference nginx configuration. Session
cookies are `SameSite=Lax`, mitigating CSRF for state-changing JSON endpoints; for
fully hardened public deployments add an CSRF token layer at the proxy or run with
`SameSite=Strict` by editing `core/auth.py::SESSION_COOKIE` settings.

## Known restrictions (honest scope)

- The embedded console runtime implements only the documented command set; it is not a
  game protocol server and cannot be reached by Minecraft clients.
- The platform does not scan uploaded jars for malware; only upload server software from
  sources you trust (official download pages listed in the software catalog).
- Rate limiting is per-process memory; for multi-worker deployments put a rate-limiter
  in front (nginx `limit_req`).
