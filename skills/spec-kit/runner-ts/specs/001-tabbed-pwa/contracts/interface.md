# Internal Interface Contracts — IC-001..IC-013

Cross-task shared state. Tasks reference these with `[produces: IC-xxx]` / `[consumes: IC-xxx]` tags in `tasks.md`.

| IC | Name | Producer | Consumer(s) | Specification |
|----|------|----------|-------------|---------------|
| IC-001 | Config file | `tabrunner init` (writer) | `src/config/load.ts` (reader) | Path: `~/.config/tabrunner/config.toml`. Format: TOML. Fields: `project: string (abs path, required)`, `port: int (default 8443)`, `tailscale_interface: string (default empty = auto)`, `data_dir: string (default ~/.local/share/tabrunner)`. Validated by zod on read. Lifecycle: created by init, never auto-modified by serve. |
| IC-002 | CA + server cert files | `tls/ca.ts`, `tls/server-cert.ts` | Fastify https opts; `tls/pairing.ts` (signs with ca-key) | Paths: `<data_dir>/ca.pem` (X.509 PEM ECDSA P-256, perm 0644, 10-year), `<data_dir>/ca-key.pem` (PEM PKCS8 ECDSA P-256, perm 0600), `<data_dir>/server-cert.pem` (perm 0644, signed by ca, SAN includes tailscale IP, 90-day, auto-rotated within 30d of expiry), `<data_dir>/server-key.pem` (perm 0600). Wire format: standard X.509. |
| IC-003 | Pairing token | `tls/pairing.ts:issueToken()` | `api/pair.ts:verifyToken()` | URL: `https://<tailscale-ip>:<port>/pair/<token>`. Token: base64url 32 random bytes. Storage: `pairing_tokens` table. TTL: 5 min. One-shot. |
| IC-004 | Client cert | `tls/pairing.ts:signCsr()` | TLS layer (handshake); `clients` table | X.509 ECDSA P-256 PEM. Subject CN: `tabrunner-client-<short-fp>`. Validity: 365 days. Signed by CA (IC-002). Revocation: `clients.revoked_at` + in-memory set in `tls/revocation.ts`. |
| IC-005 | Session row | `claude/session.ts:create()`, `:update()` | `api/sessions.ts:get|list`, `meta-agent/tools.ts:query_sessions` etc. | Table `sessions`. Columns per `data-model.md`. PK: `id` (UUID). Status enum: pending\|running\|exited\|crashed\|terminated. Writers MUST clear `pid` on terminal transitions. |
| IC-006 | Messages FTS row | `claude/jsonl-watcher.ts` (writer) | `meta-agent/tools.ts:search_messages`, `api/sessions.ts:GET /sessions/:id/messages` | Virtual table `messages_fts(session_id UNINDEXED, message_id UNINDEXED, role UNINDEXED, content, timestamp UNINDEXED) USING fts5(tokenize='porter unicode61')`. Upsert by `(session_id, message_id)`. |
| IC-007 | WS envelope | `ws/multiplexer.ts` (server) ↔ `pwa/state/ws-client.ts` (PWA) | both directions | JSON `{type: string, session_id: string\|null, seq: number, payload: object}`. Types per `contracts/ws.md`. seq monotonic per session_id per direction. Sent over WS subprotocol `tabrunner-v1`. |
| IC-008 | claude session JSONL | claude CLI (external writer) | `claude/jsonl-parser.ts` (reader) | Path: `~/.claude/projects/<encoded-project-path>/<session-uuid>.jsonl`. Encoded path: project absolute path with `/` → `-` (e.g. `/home/max/git/foo` → `-home-max-git-foo`). Format: NDJSON. Schema per FR-091 (pinned major.minor). Parser MUST skip malformed lines and mark session `partial_index=1`. |
| IC-009 | bwrap argv | `claude/spawn.ts:buildArgs()` | `bwrap` (consumer process) | Args (in order): `--die-with-parent --unshare-pid --unshare-uts --unshare-ipc --setenv PATH /nix/store/...:/run/current-system/sw/bin --setenv HOME <scratch>/home --setenv CLAUDE_CODE_OAUTH_TOKEN <pass-through-from-env> --ro-bind /nix /nix --ro-bind /etc/resolv.conf /etc/resolv.conf --ro-bind /etc/ssl /etc/ssl --bind <project> <project> --bind <scratch> <scratch> --dev /dev --proc /proc --chdir <project> -- claude --session-id <uuid>`. DNS allowlist enforced by overlaying `/etc/resolv.conf` to a stub that points at an in-process DNS filter (or by network-namespace + nftables — implementation choice; document in research.md once decided). |
| IC-010 | MCP tool I/O | `meta-agent/tools.ts` (impl) | meta claude session via stdio MCP (consumer) | Schemas in `contracts/mcp.md`. Stdio JSON-RPC. 9 tools registered. All read-only. |
| IC-011 | Audit log line | `security/audit-log.ts` (writer) | pino stderr → journal (consumer) | pino JSON `{channel: "audit", audit_id: string, actor: "meta-agent"\|"admin-cli"\|"pwa", tool?: string, args?: object, outcome: "ok"\|"deny"\|"error", reason?: string, ...correlation_ids}`. |
| IC-012 | Expected claude version | build constant in `src/config/claude-version.ts` | `src/cli/serve.ts` startup check | `export const EXPECTED_CLAUDE_MAJOR_MINOR = "1.0"`. Parser: regex `/^(\d+)\.(\d+)/` against `claude --version` output. Mismatch → exit 78. |
| IC-013 | systemd unit | `etc/systemd/tabrunner.service` (repo file) | `~/.config/systemd/user/tabrunner.service` (after install) | INI. Sections: `[Unit]` Description=, After=tailscaled.service; `[Service]` Type=exec, ExecStart=tabrunner serve, Restart=always, Environment=TABRUNNER_LOG_DEV=0; `[Install]` WantedBy=default.target. |

## Field-level precision rules

**Naming**: All JSON/TOML keys use `snake_case`. All TypeScript field names use `camelCase`. Serialization layer translates between them via zod's `.transform()` or explicit field mapping. The wire format (TOML/JSON) snake_case is the source of truth — TS code adapts to it.

**Nullability**: Where a field is nullable in the wire format, it's explicitly `null` (not absent). zod `.nullable()` produces `field: T | null`. Optional (may be absent) is reserved for forward-compat additions.

**Timestamps**: Always ISO-8601 UTC with millisecond precision (`2026-05-24T14:23:11.456Z`). Never Unix epoch. Never date-only.

**Paths**: Always absolute, always POSIX-style (Linux-only project). Tilde expansion happens at config-load time, not at use time.

**UUIDs**: Always v4 string form (36 chars with hyphens). Lowercase hex.

**Fingerprints**: SHA-256 hex, lowercase, with colons every 2 chars (`ab:cd:ef:...`) for display. Without colons in DB primary key.

## Cross-language serialization contracts

This is a single-language project (TypeScript on both server and PWA), so the standard "Go ↔ Kotlin" multi-language risks don't apply. **However**, the WS envelope IS a serialization boundary that both sides must agree on, and zod schemas defined in `src/types/shared.ts` are the source of truth.

**Rule**: server and PWA both import `src/types/shared.ts`. The same zod schema validates envelope payloads on send (server) and receive (PWA), and vice versa. Round-trip tests in `tests/contract/ws-envelope.test.ts` assert that every defined envelope shape serializes → deserializes losslessly.

**External wire format**: claude's JSONL format (IC-008). This IS cross-tool — we don't control it. The parser MUST be lenient: skip unknown fields, log warnings on unexpected types, NEVER throw on a single malformed line.

## Discovery of producer/consumer mismatches

The pre-PR gate (`make pre-pr`) runs `tests/contract/*` which validate every IC contract. If a producer changes its output shape, the corresponding contract test fails until the consumer is updated. This is the safety net.
