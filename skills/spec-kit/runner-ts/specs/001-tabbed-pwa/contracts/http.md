# HTTP Contract — tabrunner v1

All endpoints require a valid client certificate signed by the local CA (FR-005), EXCEPT `/pair/<token>/*` which uses pairing tokens. Base URL: `https://<tailscale-ip>:<port>/api/v1` (versioned). All responses include security headers per FR-097.

## Conventions

- **Content-Type**: `application/json; charset=utf-8` for all bodies (request and response).
- **Error response shape**:
  ```json
  { "error": "<error_code>", "message": "<human readable>", "details": <optional object> }
  ```
- **Timestamps**: ISO-8601 UTC with millisecond precision (`2026-05-24T14:23:11.456Z`).
- **Pagination**: `?limit=<n>` (default 50, max 200), `?since=<cursor>` (opaque); responses include `next_cursor` when more rows exist.
- **HTTP status codes** map to error categories: 400 = `validation_error`, 401 = `auth_required` (rare — mTLS handles most), 403 = `forbidden`, 404 = `not_found`, 409 = `conflict`, 410 = `gone`, 422 = `unprocessable`, 500 = `internal_error`, 503 = `not_ready`.

---

## Health & readiness

### `GET /api/v1/health`
Liveness probe.

**Response 200**:
```json
{
  "ok": true,
  "version": "0.1.0",
  "tailscale_ip": "100.x.y.z",
  "uptime_s": 12345,
  "sessions_running": 3
}
```

### `GET /api/v1/ready`
Readiness probe — 200 only when DB migrations done AND FTS initial scan complete.

**Response 200**: same shape as `/health` plus `"ready": true`.

**Response 503**:
```json
{ "ok": false, "ready": false, "reason": "fts_initial_scan_in_progress" }
```

Reasons: `migrations_pending`, `fts_initial_scan_in_progress`, `tailscale_unreachable`, `claude_version_mismatch`.

### `GET /api/v1/sw-version`
Returns the build version string used by the service worker for update detection.

**Response 200**:
```json
{ "version": "0.1.0-abcd1234" }
```

---

## Sessions

### `GET /api/v1/sessions`
List sessions (paginated).

**Query params**:
- `project` (string, optional): filter by `project_path` exact match.
- `status` (string, optional): one of `pending|running|exited|crashed|terminated`.
- `pinned` (bool, optional): if true, return pinned sessions only.
- `search` (string, optional): FTS5 query against titles + first user message + project path.
- `since` (string, optional): opaque cursor from previous response.
- `limit` (int, optional): default 50, max 200.

**Response 200**:
```json
{
  "sessions": [
    {
      "id": "11111111-2222-3333-4444-555555555555",
      "project_path": "/home/max/git/foo",
      "title": "Refactor auth middleware",
      "status": "exited",
      "started_at": "2026-05-22T10:11:12.345Z",
      "last_activity_at": "2026-05-22T10:45:00.000Z",
      "exited_at": "2026-05-22T10:45:00.000Z",
      "exit_code": 0,
      "exit_signal": null,
      "pid": null,
      "pinned": false,
      "message_count": 42
    }
  ],
  "next_cursor": "MjAyNi0wNS0yMlQxMDoxMTox..."
}
```

**Notes**:
- `message_count` is computed from `messages_fts` (subquery or maintained denormalized column — implementation choice).
- If `search` is present, results are ordered by FTS5 rank, not by timestamp.

### `GET /api/v1/sessions/:id`
Get session metadata.

**Response 200**: same row shape as inside `sessions` array above.

**Response 404**: `{"error":"not_found","message":"session <id> not found"}`

### `POST /api/v1/sessions`
Create a new session.

**Request body**:
```json
{
  "title": "Optional title — defaults to 'New session'",
  "resume_id": "Optional UUID — if present, this is a reopen request"
}
```

**Response 201**:
```json
{
  "id": "<new-uuid-or-resume-id>",
  "status": "pending",
  "started_at": "2026-05-24T14:23:11.456Z"
}
```

**Notes**:
- If `resume_id` is provided and references a terminal session, the server spawns `claude --resume <resume_id>` (FR-023).
- If `resume_id` references a session with a live PID, the server returns 200 (not 201) with the existing row — no new spawn.

### `POST /api/v1/sessions/:id/reopen`
Convenience endpoint equivalent to `POST /sessions` with `resume_id` set.

**Response 200|201**: same as `POST /sessions`.

### `DELETE /api/v1/sessions/:id`
Send SIGTERM to the session's PID. 10s grace then SIGKILL. Idempotent — deleting an already-exited session returns 200.

**Response 200**:
```json
{ "id": "<id>", "status": "terminated" }
```

### `GET /api/v1/sessions/:id/messages`
Get parsed messages from a session's JSONL.

**Query params**:
- `since` (int seq, optional): return messages after this sequence number.
- `limit` (int, optional): default 50, max 200.

**Response 200**:
```json
{
  "messages": [
    {
      "session_id": "...",
      "message_id": "...",
      "seq": 1,
      "role": "user",
      "content": "hello",
      "timestamp": "2026-05-22T10:11:12.345Z"
    },
    {
      "session_id": "...",
      "message_id": "...",
      "seq": 2,
      "role": "assistant",
      "content": "Hi! How can I help?",
      "timestamp": "2026-05-22T10:11:14.000Z"
    },
    {
      "session_id": "...",
      "message_id": "...",
      "seq": 3,
      "role": "tool_call",
      "content": "{\"tool\":\"Bash\",\"args\":{\"command\":\"ls -la\"}}",
      "timestamp": "2026-05-22T10:11:20.000Z"
    }
  ],
  "next_cursor": null
}
```

**Notes**: `seq` is monotonic per session, derived from JSONL line order.

---

## Pairing

These endpoints DO NOT require a client cert. The pairing token is the auth.

### `GET /pair/:token`
Returns the pairing HTML page (the only HTML served outside `/`).

**Response 200**: HTML page with embedded JS that does WebCrypto keygen + CSR.
**Response 410**: pairing token expired or already used.

### `POST /pair/:token/csr`
Submit a CSR; receive signed client cert + CA cert.

**Request body**:
```json
{
  "csr_pem": "-----BEGIN CERTIFICATE REQUEST-----\n..."
}
```

**Response 200**:
```json
{
  "client_cert_pem": "-----BEGIN CERTIFICATE-----\n...",
  "ca_cert_pem": "-----BEGIN CERTIFICATE-----\n...",
  "fingerprint": "ab:cd:ef:...",
  "expires_at": "2027-05-24T14:23:11.456Z"
}
```

**Response 410**: token expired or already used.
**Response 422**: CSR malformed or rejected (e.g. RSA instead of ECDSA P-256).
**Response 409**: race — two clients posted CSRs concurrently; only the first won.

### `GET /pair/:token/status`
Poll for token state. Used by the pairing page to recover from network blips.

**Response 200**: `{ "state": "issued"|"used"|"expired" }`

---

## Admin (CLI-only — these endpoints back the admin CLI subcommands)

### `GET /api/v1/admin/clients`
List paired clients.

**Response 200**:
```json
{
  "clients": [
    {
      "fingerprint": "ab:cd:ef:...",
      "common_name": "tabrunner-client-abcd1234",
      "issued_at": "2026-05-01T...",
      "expires_at": "2027-05-01T...",
      "revoked_at": null,
      "last_seen_at": "2026-05-24T..."
    }
  ]
}
```

### `POST /api/v1/admin/clients/:fingerprint/revoke`
Revoke a client cert.

**Response 200**: `{ "fingerprint": "...", "revoked_at": "2026-05-24T..." }`
**Response 404**: unknown fingerprint.

(The admin CLI uses these endpoints over loopback with a built-in admin cert. Alternative: CLI talks directly to SQLite. Implementation choice — recommend HTTP-via-loopback so the same auth model applies everywhere.)

---

## Audit log entries

Every request that mutates state OR comes from the meta agent produces an audit log line via pino's audit channel (FR-085):

```json
{
  "channel": "audit",
  "audit_id": "uuid",
  "actor": "pwa" | "meta-agent" | "admin-cli",
  "client_fingerprint": "ab:cd:ef:...",
  "method": "POST",
  "path": "/api/v1/sessions",
  "outcome": "ok" | "deny" | "error",
  "reason": "optional explanation"
}
```
