# Feature Specification: tabrunner — Tabbed PWA + Server for Parallel Claude Code Sessions

**Feature Branch**: `001-tabbed-pwa`
**Created**: 2026-05-23
**Status**: Draft
**Input**: User description: "Tabbed PWA + server for parallel Claude Code sessions, mTLS-TOFU auth, read-only meta agent over Tailscale"

## Overview

tabrunner is a Tailscale-bound TypeScript server that exposes a Progressive Web App for managing parallel `claude` CLI sessions. Each browser tab maps to one sandboxed `claude` session. A pinned **meta agent** tab gives the operator a read-only Claude session with MCP tools that can query the history database, tail live stdout from running sessions, and read files inside the watched project. Auth is mutual TLS with Trust-On-First-Use device pairing via a one-shot QR code.

## Clarifications

### Session 2026-05-23
- Q: How is `claude` CLI version pinned? → A: Pin in flake.nix; server checks `claude --version` at startup, refuses to run on major.minor mismatch.
- Q: PWA composer send-key behavior? → A: Enter sends; Shift+Enter inserts newline; Cmd/Ctrl+Enter also sends (mobile parity).
- Q: How are streaming tool_call events rendered? → A: Collapsed by default with one-line summary (e.g. `Bash: ls -la`); click to expand args and result.
- Q: Server CA private key protection at rest? → A: chmod 600 only; README warns that `data/` backups must be treated as secrets.
- Q: First-run UX when `tabrunner serve` runs without config or data dir? → A: Fail fast with instructions to run `tabrunner init` first; init scaffolds config.toml (prompting for project path), creates data dir, and generates the CA.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Pair a New Device (Priority: P1)

The operator runs `tabrunner pair` in a terminal on the server host. The CLI prints a QR code and a short-TTL URL. The operator opens the PWA URL on a phone or laptop on the same Tailnet for the first time, scans the QR, and the browser generates a client keypair and submits a CSR. The server signs the CSR, stores the client cert, and the PWA installs the cert in its local store. From that point on, the device's PWA can connect to the server with no further auth steps. The pairing URL becomes invalid after 5 minutes or after a successful pairing.

**Why this priority**: Without pairing, the PWA cannot connect at all. This is the prerequisite for everything else.

**Independent Test**: Run `tabrunner serve` on a host, run `tabrunner pair`, open the printed URL on a second device on the same Tailnet, scan the QR, verify the device receives a client cert and subsequent unauthenticated curl requests are rejected at the TLS layer.

**Workflows**: W-OP-1 (happy path), W-SYS-3 (CLI side), W-OP-8 (adversarial rejection)

---

### User Story 2 — Open a New Tab and Drive a Claude Session (Priority: P1)

The operator clicks "New Tab" in the PWA. The server allocates a new session UUID, spawns `claude --session-id <uuid>` inside a bwrap sandbox rooted at the configured project directory, and starts streaming stdout to the PWA over WebSocket. The operator types a prompt in the composer; the PWA sends it over WS; the server writes it to claude's stdin via PTY. Tool calls, assistant text, and progress events render in the tab as parsed chat bubbles, with raw bytes available for copy.

**Why this priority**: Single-tab usage is the minimum viable product. Everything else is enhancement.

**Independent Test**: Pair a device, click New Tab, type "hello", verify the assistant response appears and the underlying `claude` session UUID matches `~/.claude/projects/<encoded-project>/<uuid>.jsonl`.

**Workflows**: W-OP-2 (happy path), W-OP-11 (tool-call render), W-OP-12 (composer keys), W-OP-13 (raw toggle), W-OP-15 (crashed session)

---

### User Story 3 — Run Multiple Tabs in Parallel (Priority: P1)

The operator opens 5 tabs and starts 5 separate Claude sessions, each pursuing a different task. The PWA shows all 5 simultaneously in the tab bar with live status indicators (idle / streaming / awaiting input / completed). The operator switches between tabs without losing message stream cursors. Each session has its own bwrap sandbox and PID.

**Why this priority**: Parallel work is the whole point of tabs versus a single CLI terminal.

**Independent Test**: Open 5 tabs in the PWA, start a long-running prompt in each, switch tabs back and forth, verify each session's output is independent and complete.

**Workflows**: W-OP-3 (parallel sessions, including 30-min soak)

---

### User Story 4 — Close and Reopen a Tab via History (Priority: P1)

The operator closes a tab. The session UUID, tab title, project, and message metadata remain in the history database. The closed tab disappears from the tab bar. Later, the operator opens the History view, searches for the session by title or content, and reopens it. A new tab spawns running `claude --resume <uuid>` in the same project directory. If the original `claude` process is still alive (e.g., the tab was closed but `serve` kept it running), reattach to it instead.

**Why this priority**: Without reopen, closed tabs are lost work. History without reopen is a museum, not a tool.

**Independent Test**: Start a tab, send 3 messages, close the tab, open History, reopen the session, verify message history is replayed and the operator can continue the conversation.

**Workflows**: W-OP-4 (close + reopen via History; covers `claude --resume`)

---

### User Story 5 — Ask the Meta Agent a Cross-Session Question (Priority: P1)

The operator opens the pinned **Meta** tab. This is a special Claude session running in the PWA with the tabrunner MCP server attached (read-only tools only). The operator types: *"Which session is stuck waiting for input right now? Show me the last 30 lines."* The meta agent calls `list_running()`, identifies the waiting session, calls `tail_live(session_id, 30)`, and shows the answer with the snippet. The meta agent cannot spawn, kill, or edit anything in v1.

**Why this priority**: Cross-session observability is the killer feature that distinguishes tabrunner from running 5 terminals in tmux.

**Independent Test**: Start 3 tabs, deliberately stall one mid-prompt (e.g., a prompt that asks the agent a question), open the Meta tab, ask "which session is waiting?", verify the meta agent correctly identifies the stalled tab and reports its last lines.

**Workflows**: W-OP-5 (meta agent observability query, including forbidden-tool + path-traversal edges)

---

### User Story 6 — Search Across All Sessions (Priority: P2)

The operator types in the History view's search box: *"FTS index"*. The PWA queries the server's full-text-search endpoint, which returns matching messages from any past session, with session metadata and the matching snippet. Clicking a result opens that session in a new tab (replay only — does not resume the underlying claude process unless still alive).

**Why this priority**: Once you have many sessions, search is how you find that thing you discussed last Tuesday. Less critical than reopen but high-value.

**Independent Test**: Run 3 sessions with distinct content, ingest them into the FTS index, search a unique phrase, verify the correct session and message snippet appear.

**Workflows**: W-OP-6 (FTS search; covers 0-match, FTS5 parse error, indexer-lag edges)

---

### User Story 7 — Admin CLI for Recovery (Priority: P2)

The PWA is broken or the operator is at the host terminal. They run:
- `tabrunner init` — interactive first-time setup (config, data dir, CA, server cert, DB).
- `tabrunner sessions list` — see all running sessions and their PIDs.
- `tabrunner sessions kill <session_id>` — terminate one.
- `tabrunner clients list` — see paired devices.
- `tabrunner clients revoke <fingerprint>` — drop a paired device.

**Why this priority**: When the PWA is unavailable, the operator still needs control. Critical for a tool that runs on their own machine.

**Independent Test**: Pair a device, run `tabrunner clients list` → see the fingerprint; run `tabrunner clients revoke <fp>`; from the revoked device, try to connect → TLS handshake fails.

**Workflows**: W-SYS-4 (list + revoke), W-SYS-9 (sessions list + kill), W-SYS-5 (systemd unit), W-SYS-1 (init)

---

### User Story 8 — PWA Survives Server Restart (Priority: P2)

The operator restarts `tabrunner serve` (e.g., `systemctl --user restart tabrunner`). On shutdown, the server gracefully SIGTERMs every running `claude` session (10s grace, then SIGKILL). The PWA sees the WS disconnect and shows a "reconnecting" banner. On reconnect, the PWA fetches the new server state (no running sessions) and the operator can reopen sessions from History via `claude --resume`.

**Why this priority**: Restart correctness is foundational for a long-lived tool. Not P1 only because the most common path is "server stays up".

**Independent Test**: Open 3 tabs, restart the server, verify (a) all 3 claude processes exit cleanly within 10s, (b) PWA shows reconnecting then reconnects, (c) all 3 sessions appear in History and can be reopened with `--resume`.

**Workflows**: W-OP-7 (operator side: reconnecting banner + reopen), W-SYS-6 (sysadmin side: graceful shutdown), W-OP-14 (WS replay buffer)

---

### Edge Cases & Failure Modes

**Pairing**
- Pairing URL is requested after TTL expiry → return 410 Gone with a clear message; admin must re-run `tabrunner pair`.
- Pairing URL is requested a second time after successful pairing → return 410 Gone.
- Pairing fails mid-CSR (browser crashes) → token remains valid until TTL; operator can retry.
- Two devices race to pair with the same token → first wins, second gets 409 Conflict.
- Browser does not support WebCrypto (e.g., HTTP-only context) → pairing page shows an explicit error referencing required HTTPS context.

**TLS / connection**
- Client cert is missing → TCP-level rejection (`require_client_cert: true`), no application-level handler runs.
- Client cert is expired (past 1-year TTL) → TLS handshake fails; PWA shows "device expired, please re-pair" and links to pairing instructions.
- Client cert is revoked → server keeps a revocation set in memory + DB; TLS handshake post-revocation fails. Revocation effective immediately on the next handshake (no need to restart connections).
- Tailscale is down at server startup → fail fast with `error: tailscale not running or no IPv4 assigned`. Do NOT bind to 0.0.0.0 as a fallback.
- Tailscale IP changes mid-run (rare) → server logs and exits; systemd restarts and rebinds.

**Session lifecycle**
- `claude` binary not on PATH → tab creation fails with a clear error pointing to the flake.nix.
- `bwrap` rejects the spawn (sandbox config error) → tab creation fails; PWA shows the bwrap stderr.
- `claude` exits with non-zero code mid-session → session marked `crashed`, exit code captured, tab shows red banner with last 50 lines and exit code.
- Project directory is deleted while a session is running → bwrap mounts fail on next operation; session marked `crashed`.
- PTY write fails (claude process gone) → mark session crashed, broadcast `session.exit` to all WS clients viewing it.
- Tab closed while claude is mid-stream → SIGTERM, 10s grace, SIGKILL. Persist final state. WS clients viewing the tab get `session.exit`.

**WebSocket**
- WS client disconnects → server buffers per-session events for 60s; on reconnect, client requests `since: <seq>` and receives missed events.
- WS client reconnects after 60s buffer drop → client must re-fetch state via REST (`GET /api/sessions/<id>?since=<seq>`).
- Two WS clients view the same session → both receive identical event streams.
- Server crashes mid-stream → on restart, the buffer is empty; clients see disconnect and re-fetch.

**Meta agent**
- Meta agent calls `read_project_file` with a path outside the watched project → 403, recorded in audit log.
- Meta agent calls `tail_live` on a session that has just exited → returns final buffer + an `exited: true` flag.
- Meta agent calls `search_messages` before FTS has indexed a new session → returns partial results with a `pending_index: true` flag.

**FTS indexing**
- New session's jsonl file appears in `~/.claude/projects/` → file watcher reads it, parses messages, inserts into FTS5 table. Latency target: < 5s.
- jsonl file is partially written (claude crashed) → parser skips malformed lines, indexes what's valid, marks session `partial_index: true`.
- jsonl file is renamed or moved → re-index on the next watcher event.

**Disk / DB**
- SQLite DB locked (concurrent writer) → retry with exponential backoff up to 5s, then surface the error.
- Disk full → log fail-fast, exit; systemd restart on disk reclamation.
- DB schema version older than expected → run migrations in order, fail-fast on any migration error.
- DB schema version NEWER than expected (downgrade) → refuse to start, exit with clear message.

**Operational**
- `tabrunner pair` run twice concurrently → both succeed; both QR codes are independently valid until their TTLs expire or used.
- `tabrunner sessions kill <id>` on a session already exited → no-op, return success.
- `tabrunner clients revoke <fp>` for unknown fingerprint → return success (idempotent), warn the operator.

---

## Requirements *(mandatory)*

### Functional Requirements

**Network & TLS (FR-001 — FR-015)**

- **FR-001**: Server MUST resolve the host's Tailscale IPv4 at startup by shelling out to `tailscale ip -4`. Refuse to start with exit code 78 (config error) if the command fails or returns no IPv4.
- **FR-002**: Server MUST bind exclusively to the resolved Tailscale IPv4. Binding to `0.0.0.0`, `127.0.0.1`, or any non-Tailscale interface is forbidden.
- **FR-003**: Server MUST use a self-signed root CA stored at `data/ca.pem` (cert) and `data/ca-key.pem` (chmod 600 private key). Generated on first startup if absent.
- **FR-004**: Server MUST present a TLS server certificate signed by the local CA at all HTTPS and WebSocket connection points. Server cert is regenerated on startup if missing or within 30 days of expiry.
- **FR-005**: Server MUST require a valid client certificate signed by the local CA for ALL endpoints except `/pair/*` (which uses one-shot pairing tokens). Unauthenticated TLS handshake terminates the connection.
- **FR-006**: Server MUST maintain an in-memory + on-disk revocation set keyed by client cert fingerprint (SHA-256). Revoked certs MUST fail handshake on the next attempt with no further requests passing through.
- **FR-007**: `tabrunner pair` MUST generate a 32-byte cryptographically random pairing token, encode it in a URL of shape `https://<tailscale-ip>:<port>/pair/<token>`, and print both the URL and a QR-code rendering of it to stdout.
- **FR-008**: A pairing token MUST be valid for exactly 5 minutes from generation OR until a successful pairing completes, whichever comes first.
- **FR-009**: The pairing page MUST instruct the browser to generate an ECDSA P-256 keypair via WebCrypto, build a CSR for the public key, and POST it to `/pair/<token>/csr`.
- **FR-010**: Server MUST verify the pairing token is unused and unexpired, sign the CSR with the local CA producing a 1-year client cert, return the cert + CA cert to the browser, and mark the token used.
- **FR-011**: The PWA MUST install the returned cert into the browser's certificate store (via Web Authentication / client-cert install flow — see Assumptions).
- **FR-012**: Server MUST log every pairing attempt (token, source IP, outcome) to the pino audit log channel.
- **FR-013**: Client cert TTL MUST default to 365 days. The cert MUST embed the device fingerprint as a subject CN.
- **FR-014**: `tabrunner clients list` MUST output a table of (fingerprint, common name, issued_at, expires_at, last_seen, revoked). Output supports `--json` for scripting.
- **FR-015**: `tabrunner clients revoke <fingerprint>` MUST add the fingerprint to the revocation set, persist it to the DB, and take effect on the next TLS handshake.

**Tab and session lifecycle (FR-016 — FR-035)**

- **FR-016**: A tab MUST correspond 1:1 with a claude session UUID. Server allocates a new UUID via `crypto.randomUUID()` on tab creation.
- **FR-017**: Server MUST spawn each claude session via `bwrap` with: (a) the configured project directory writable, (b) a per-session scratch directory `data/sessions/<uuid>/` writable, (c) DNS restricted to the allowlist (`api.anthropic.com`, `registry.npmjs.org`, `pypi.org`, `files.pythonhosted.org`, `cache.nixos.org`, `github.com`), (d) `--unshare-pid`, (e) no access to `~/.ssh`, `~/.aws`, or other credential dirs.
- **FR-018**: Server MUST attach a PTY (via `node-pty`) to the claude subprocess so interactive features (slash commands, mid-stream interrupt, multi-line input) work.
- **FR-019**: When the operator types in the PWA composer, the server MUST write the input to the claude PTY's stdin, optionally terminated with a newline depending on the message type.
- **FR-020**: Server MUST capture every byte from the claude PTY's stdout and emit both: (a) `session.stdout` WS events containing raw bytes (base64-encoded), and (b) parsed `session.message` WS events derived from the session jsonl file at `~/.claude/projects/<encoded-project>/<uuid>.jsonl`.
- **FR-021**: Tab close (PWA initiated) MUST send SIGTERM to the claude process. If the process is still alive after 10 seconds, send SIGKILL. Session row is updated with the exit code and exit reason.
- **FR-022**: Tab close MUST NOT delete the session row, jsonl file, or scratch directory. History persistence (FR-038) preserves them.
- **FR-023**: Server MUST support reopening a closed session via `POST /api/sessions/<uuid>/reopen`. If the session's underlying claude process is still alive (server tracks PIDs), attach a new WS client to it. Otherwise, spawn `claude --resume <uuid>` in the project directory and stream as a new tab.
  Example: closed session `abc-123` with no live PID → server runs `claude --resume abc-123` inside bwrap → WS clients see the replayed session jsonl as a stream of `session.message` events followed by live events.
- **FR-024**: There is NO concurrency cap on running sessions. The server spawns as many as requested.
- **FR-025**: The PWA tab bar MUST display a "running count" badge whenever ≥ 2 sessions are active.
- **FR-026**: Closed tabs MUST disappear from the active tab bar immediately. They remain accessible via the History view.
- **FR-027**: Server MUST track session status: `pending` (spawning) → `running` (PID alive) → one of {`exited` (clean), `crashed` (non-zero exit or signal), `terminated` (operator-initiated SIGTERM/SIGKILL)}.
- **FR-028**: `tabrunner sessions list` MUST output (session_id, project, status, started_at, last_activity, PID-if-running). Supports `--json`.
- **FR-029**: `tabrunner sessions kill <session_id>` MUST send SIGTERM, wait 10s, then SIGKILL. Idempotent: killing an already-exited session returns success.
- **FR-030**: Server MUST handle graceful shutdown on SIGTERM/SIGINT: stop accepting new WS connections, SIGTERM all running claude sessions, wait up to 10s per session, SIGKILL stragglers, flush DB, close FDs, exit.
- **FR-031**: WS clients MUST receive `session.exit` events when their session ends, with `{ code, signal, reason }` payload.
- **FR-032**: Server MUST tolerate WS client disconnect: per-session events buffered in memory for 60s, indexed by sequence number. On reconnect, client requests `since: <seq>` and receives missed events. Buffer overflow (>60s gap) → client must re-fetch via REST.
- **FR-033**: Multiple WS clients viewing the same session MUST receive identical event streams.
- **FR-034**: When the project directory is missing or unreadable at server startup, refuse to start with a clear error.
- **FR-035**: When a tab's project directory becomes invalid mid-session (deleted), the session is marked `crashed` and the operator is notified.

**Storage & history (FR-036 — FR-050)**

- **FR-036**: Server MUST use a single SQLite database at `data/tabrunner.db`. WAL mode enabled. Single writer via `better-sqlite3` synchronous API guarded by an in-process mutex.
- **FR-037**: Database MUST have versioned, forward-only migrations applied at startup. Schema version stored in `_meta` table. Newer schema than expected → exit 1 with downgrade message.
- **FR-038**: `sessions` table columns: `id` (UUID PK), `project_path` (text), `title` (text, default = first user message truncated), `status` (enum), `started_at`, `last_activity_at`, `exited_at`, `exit_code`, `exit_signal`, `pid` (int, nullable), `pinned` (bool — meta agent is pinned).
- **FR-039**: `messages_fts` table is an FTS5 virtual table over claude jsonl-derived messages. Columns: `session_id`, `message_id`, `role` (user|assistant|tool), `content` (indexed text), `timestamp`. Populated by the JSONL watcher (FR-044).
- **FR-040**: `clients` table columns: `fingerprint` (PK), `common_name`, `issued_at`, `expires_at`, `revoked_at` (nullable), `last_seen_at`.
- **FR-041**: `pairing_tokens` table columns: `token` (PK), `created_at`, `expires_at`, `used_at` (nullable), `client_fingerprint` (nullable, set on success).
- **FR-042**: `_meta` table tracks schema version (`schema_version`), CA serial counter (`ca_next_serial`), and other singletons.
- **FR-043**: All write paths MUST go through a single migration-aware connection. Reads MAY use additional read-only connections in WAL mode.
- **FR-044**: A filesystem watcher MUST observe `~/.claude/projects/<encoded-project>/` for new and modified jsonl files. On change, parse the jsonl tail, derive message rows, and upsert into `messages_fts`. Indexing latency target: < 5 seconds from claude write to FTS query availability.
- **FR-045**: Malformed jsonl lines MUST be skipped (with a warn log) without aborting the indexer. The session row is flagged `partial_index: true` if any lines were skipped.
- **FR-046**: History API endpoints: `GET /api/v1/sessions?project=...&since=...&limit=...&search=...` returns paginated session list; `GET /api/v1/sessions/<id>` returns session metadata; `GET /api/v1/sessions/<id>/messages?since=<seq>&limit=...` returns parsed messages. `limit` MUST default to 50 and MUST be clamped to a maximum of 200. Responses MUST include a `next_cursor` field when more results exist.
- **FR-047**: History retention default: keep forever. No background pruning. Operator can prune via `tabrunner admin prune --older-than <duration>` (admin CLI, not a v1 P1).
- **FR-048**: Session deletion (via prune or explicit admin command) MUST remove the row, FTS entries, and `data/sessions/<uuid>/` directory. Claude's jsonl file is NOT deleted (it's claude's data, not ours).
- **FR-049**: All timestamps MUST be UTC, ISO-8601 with millisecond precision, stored as text in SQLite.
- **FR-050**: DB backup MUST be possible by stopping the server, copying `data/`, and restarting. Online backup via `sqlite3 .backup` is supported but not required for v1.

**Meta agent (FR-051 — FR-065)**

- **FR-051**: A "meta" session MUST be auto-created on first server startup with `pinned: true` and `title: "Meta"`. Always appears as the first tab in the PWA bar.
- **FR-052**: The meta session MUST be spawned with `claude --session-id <meta-uuid>` in the project directory, with a `.mcp.json` that exposes the tabrunner MCP server on stdio with the read-only tool surface defined below.
- **FR-053**: tabrunner MCP server tool: `query_sessions(filter)` — `filter: { project?, status?, since?, limit? }`. Returns array of session metadata rows.
- **FR-054**: tabrunner MCP server tool: `read_session(session_id, since?)` — returns parsed messages for one session, optionally tailing from a sequence cursor.
- **FR-055**: tabrunner MCP server tool: `tail_live(session_id, lines?)` — returns the last N (default 50) raw stdout bytes from a running session. Returns `{ buffer, exited: bool, exit_code? }`.
- **FR-056**: tabrunner MCP server tool: `list_running()` — returns array of `{ session_id, pid, project, started_at, last_activity_at, title }` for all currently-running sessions.
- **FR-057**: tabrunner MCP server tool: `search_messages(query, scope?)` — `scope: { session_id?, project?, since? }`. Returns FTS5-matched message rows with snippets.
- **FR-058**: tabrunner MCP server tool: `search_sessions(query)` — FTS over session titles, first user messages, and project paths.
- **FR-059**: tabrunner MCP server tool: `read_project_file(path)` — reads a file inside the configured project directory. Path is normalized; any path resolving outside the project root returns 403 ERROR and is logged.
- **FR-060**: tabrunner MCP server tool: `list_project_files(glob?)` — globs over the project directory. Same path-traversal guard as `read_project_file`.
- **FR-061**: tabrunner MCP server tool: `get_session_summary(session_id)` — returns `{ first_user_message, last_assistant_message, tool_call_count, message_count, started_at, last_activity_at }`. Computed on-the-fly; cached for 60s per session.
- **FR-062**: The meta agent MUST NOT have access to any tool that spawns processes, sends signals, writes files, or runs shell commands. The MCP server enforces this — there are no such tools defined.
- **FR-063**: Meta agent tool invocations MUST be logged to the audit log channel with `{ tool, args, session_id (meta), timestamp, result_size }`.
- **FR-064**: Meta agent UI MUST visually distinguish itself (e.g., different tab icon, header banner) so the operator can't confuse it with a regular session.
- **FR-065**: Meta agent session is reopenable like any other; on server restart it gets a new claude process via `--resume`.

**PWA (FR-066 — FR-080)**

- **FR-066**: PWA MUST be a service-worker-enabled web app at the root path (`/`). Static assets served from `public/`.
- **FR-067**: PWA MUST be mobile-first responsive. Tab bar collapses into a drawer at viewport widths < 768px. All interactive elements have touch targets ≥ 44px.
- **FR-068**: PWA MUST be installable to home screen (manifest.webmanifest with name, icons, theme color, display: standalone).
- **FR-069**: PWA MUST work offline for shell rendering: HTML/JS/CSS cached via service worker. When offline, the tab bar shows last-known state; a "reconnecting" banner is visible.
- **FR-070**: PWA MUST NOT cache session content in IndexedDB in v1. Session data fetched live; reload on reconnect.
- **FR-071**: PWA MUST use Preact + signals for reactivity, esbuild for bundling, TypeScript strict for source.
- **FR-072**: PWA tab UI MUST render parsed `session.message` events as chat bubbles (user / assistant / tool_call / tool_result). Raw `session.stdout` is available via a "Show raw" toggle per tab.
- **FR-073**: Tab close (X button) MUST prompt with "Close tab? (Session keeps running in History view until you reopen it)" when the session is still streaming, with a "don't ask again" checkbox.
- **FR-074**: New Tab button MUST be a single click; no modal. Default title is "New session"; rename inline.
- **FR-075**: History view MUST be reachable from a sidebar/drawer item. Lists sessions in reverse-chronological order with: title, project, started_at, last_activity_at, status, message count.
- **FR-076**: History view search box MUST hit `GET /api/sessions?search=<q>` which queries FTS over messages, titles, and project paths. Results show matching snippet.
- **FR-077**: PWA MUST display the running count badge on the tab bar whenever there are ≥ 2 running sessions. Click reveals a list of running session titles.
- **FR-078**: PWA MUST handle WS disconnect: show "reconnecting" banner, retry with exponential backoff (1s, 2s, 4s, 8s, 30s max), resume from last sequence number per session.
- **FR-079**: PWA MUST handle TLS handshake failure on initial connect by showing: "Device not paired. Please run `tabrunner pair` and scan the QR code on this device."
- **FR-080**: PWA MUST display the Tailscale IP and port the server is bound to in a footer/about panel for debugging.

**Process & DX (FR-081 — FR-090)**

- **FR-081**: A systemd user unit file MUST ship in the repo at `etc/systemd/tabrunner.service`. `make install` (or equivalent) installs it to `~/.config/systemd/user/`.
- **FR-082**: Server MUST read configuration from `~/.config/tabrunner/config.toml` at startup. Required keys: `project` (path). Optional keys: `tailscale_interface` (default: auto-discover via `tailscale ip -4`), `port` (default: 8443), `data_dir` (default: `~/.local/share/tabrunner`). The config file MUST be created by `tabrunner init` (FR-096), not auto-created on `serve` (FR-095).
- **FR-083**: Server MUST emit pino structured JSON logs to stderr. Log levels: trace, debug, info, warn, error. Default level: info. Override via `TABRUNNER_LOG_LEVEL` env var.
- **FR-084**: Pino dev mode (`TABRUNNER_LOG_DEV=1`) pretty-prints logs via pino-pretty.
- **FR-085**: Logs MUST include correlation IDs for: per-WS-connection requests (`connection_id`), per-session events (`session_id`), per-meta-agent-tool-call (`audit_id`).
- **FR-086**: All operational scripts MUST be in `package.json`: `dev`, `build`, `start`, `test`, `test:unit`, `test:integration`, `test:contract`, `test:e2e`, `lint`, `typecheck`, `clean`. Plus `db:migrate` and `db:reset`.
- **FR-087**: A `.env.example` MUST document all env vars (TABRUNNER_LOG_LEVEL, TABRUNNER_LOG_DEV, TABRUNNER_CONFIG (override config path)).
- **FR-088**: VS Code `launch.json` MUST configure debug profiles for: server, tests, single test file.
- **FR-089**: `nix develop` MUST be the canonical dev environment. All tools (node, ts, uv, tailscale, bwrap, openssl, sqlite) come from the flake.
- **FR-090**: A pre-commit hook MUST block commits containing files matching `*.pem` or `*.key` (excluding `*.example`).
- **FR-091**: `claude` CLI MUST be pinned in `flake.nix` to a specific version. The server MUST shell out to `claude --version` at startup and refuse to start (exit code 78) if the parsed `major.minor` does not match an expected value baked into the binary (`TABRUNNER_EXPECTED_CLAUDE_MAJOR_MINOR`). The expected value is updated whenever the flake's claude pin is bumped, paired with a test run that exercises the JSONL parser and `--resume` flow against the new version.
  Example: flake pins `claude` to 1.0.42, server expects `1.0`. Running with `claude 1.1.x` → exit 78 with message `unexpected claude version 1.1.x; expected 1.0.x. Update tabrunner or pin claude back.`
- **FR-092**: PWA composer MUST support these key bindings: `Enter` → send the current draft; `Shift+Enter` → insert newline; `Cmd+Enter` and `Ctrl+Enter` → also send (for parity with mobile keyboards that don't easily produce Shift+Enter and for users who want the editor-style send shortcut). A visible "Send" button MUST also be present for mouse/touch use.
- **FR-093**: Tool-call events in the chat rendering MUST be collapsed by default, displayed as a single-line summary of shape `<tool_name>: <one-line preview of args>` (e.g. `Bash: ls -la`, `Read: /path/to/file`). Clicking the summary MUST expand to show full arguments and the tool result. Tool results MUST also be collapsible. Long results (>50 lines) MUST be truncated in the expanded view with a "show full" affordance.
- **FR-094**: The server's CA private key (`data/ca-key.pem`) MUST be created with file mode 0600 and owned by the user running `tabrunner serve`. No additional encryption-at-rest is required in v1. The project's README MUST contain a "Backup" section explicitly warning that any backup of `data/` includes the CA private key and MUST be stored with the same protection (encrypted volume, restricted access).
- **FR-095**: `tabrunner serve` MUST refuse to start (exit code 78) when any of the following are missing at startup:
  - `~/.config/tabrunner/config.toml`
  - The directory referenced by `config.project`
  - `<data_dir>/ca.pem` and `<data_dir>/ca-key.pem`
  - The expected SQLite database file (`<data_dir>/tabrunner.db`)
  When refusing, the error MUST instruct the operator to run `tabrunner init` and indicate which specific artifact was missing.
  Example: missing config → `error: no config at /home/max/.config/tabrunner/config.toml. Run 'tabrunner init' to create one.`
- **FR-096**: `tabrunner init` MUST be an interactive setup command. It MUST:
  - Prompt for the watched project absolute path; validate that the path exists and is a directory.
  - Create `~/.config/tabrunner/config.toml` (or refuse to overwrite if present unless `--force` passed).
  - Create `<data_dir>/` (default: `~/.local/share/tabrunner`).
  - Generate the CA (ECDSA P-256, 10-year validity for the root CA cert, 1-year for end-entity client certs).
  - Generate the server's TLS cert signed by the CA.
  - Initialize the SQLite database and run all migrations.
  - Print a final summary including the Tailscale IP+port the server will bind to, and a one-line next step (`Now run: tabrunner serve`).
  `tabrunner init` MUST be idempotent for already-present artifacts: re-running with everything in place is a no-op that prints the current state.
- **FR-097**: All HTTP responses (including WS upgrade responses) MUST include the following security headers: `Strict-Transport-Security: max-age=63072000` (HSTS, 2 years), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' wss://*; frame-ancestors 'none'` (the `'unsafe-inline'` style-src is required for inline tab-color styles; remove it if all styles are hashed/nonced).
- **FR-098**: Server MUST expose `GET /api/v1/health` (liveness) and `GET /api/v1/ready` (readiness), both requiring a valid client certificate per FR-005. `/health` returns `{ ok: true, version: <string>, tailscale_ip: <string>, uptime_s: <number>, sessions_running: <number> }`. `/ready` returns 200 only after DB migrations are applied AND the FTS indexer has completed its initial scan; otherwise returns 503 with `{ ok: false, reason: <string> }`.
- **FR-099**: The PWA service worker MUST embed a build-time version string. On every page load, the SW MUST `fetch('/api/v1/sw-version')` and, when the server-reported version differs, trigger `skipWaiting()` and notify clients (via `MessageChannel`) so the PWA can prompt the operator to reload. The server endpoint `GET /api/v1/sw-version` returns the build version. SW MUST cache only static assets (HTML/JS/CSS/manifest/icons); MUST NEVER cache `/api/v1/*` responses.
- **FR-100**: Across the plan, tasks, and code, the canonical term for the directory tabrunner operates on is **"watched project"** (or "watched project directory"). Synonyms (`configured project`, `target project`, `project directory`) MUST be normalized to the canonical term in plan/tasks/code; existing spec uses are grandfathered.

### Key Entities

- **Session**: A running or historical `claude` CLI invocation. Identified by UUID. Has status, project, title, exit info, optional live PID. One session = one tab (when open). Pinned sessions (meta agent) are always shown first.
- **Message**: A parsed unit of conversation derived from claude's session jsonl: user input, assistant response, tool call, or tool result. Indexed by FTS5 for cross-session search.
- **Client**: A device that has paired with the server. Identified by certificate SHA-256 fingerprint. Has issued_at, expires_at, optional revoked_at, last_seen_at.
- **PairingToken**: A one-shot, time-limited token allowing exactly one device to pair. Has TTL of 5 minutes from issuance.
- **WS event**: A typed envelope `{ type, session_id, seq, payload }` carrying session/state changes from server to PWA. Discriminated union types: `session.created`, `session.stdout`, `session.message`, `session.status`, `session.exit`, `pair.complete`, `meta.tool_call`, `meta.tool_result`.

---

## Non-Goals

Things this system deliberately does NOT do in v1, with rationale:

- **No multi-user model**. Single operator, multiple devices. Rationale: scope, Principle I. Multi-user is a v2 redesign.
- **No multi-project switching at runtime**. The configured project is fixed at server startup; changing projects requires editing config.toml and restarting. Rationale: simplicity in v1; many projects = run multiple `tabrunner serve` instances on different ports.
- **No meta agent operator mode**. Meta agent is read-only (Principle VI). Rationale: writing operations need confirmation UI, audit, kill switch — out of scope for v1.
- **No concurrency cap or admission control**. Rationale: operator's explicit preference. Trade-off: high API spend bursts possible.
- **No cloud sync of sessions**. Sessions live in claude's local jsonl + our local SQLite. Rationale: this is a local tool over Tailscale, not a cloud service.
- **No Windows or macOS support**. Linux only (bwrap, systemd, tailscale). Rationale: target stack matches the operator's host.
- **No browser-extension or VS Code integration**. PWA only. Rationale: focus.
- **No conversation editing or branching**. Sessions are append-only via claude's own behavior. Rationale: claude's session model is the source of truth.
- **No automatic cert rotation**. Client certs are 1-year, manual revoke via admin CLI. Rationale: operator preference; simpler in v1.
- **No background prune of history**. Sessions kept forever unless operator runs prune manually. Rationale: storage is cheap; conversations are valuable.
- **No PWA-side IndexedDB cache of session content**. Rationale: server is authoritative; reload on reconnect is acceptable for v1.
- **No xterm.js-style terminal in PWA**. Chat bubble UI only, raw bytes available on toggle. Rationale: chat UX is the primary interaction model.
- **No GitHub/GitLab integration, no CI/CD inside tabrunner**. Rationale: tabrunner runs claude; CI/CD is what claude does on its own.
- **No telemetry beyond local logs**. No analytics, no crash reporting to remote services. Rationale: single-user local tool.

---

## Operational Workflows

### Day-1 setup (~10 minutes)

1. Clone the project's parent repo and `cd` to `.claude/skills/spec-kit/runner-ts/`.
2. `nix develop` — enters the devshell, builds tools (including the pinned `claude`), starts the code-review-graph watcher.
3. `npm install --ignore-scripts && npm rebuild better-sqlite3 node-pty`
4. `npm run build`
5. `tabrunner init` — interactive: prompts for the watched project path, creates `~/.config/tabrunner/config.toml`, creates `~/.local/share/tabrunner/`, generates CA + server cert, initializes the SQLite database.
6. `npm run start` (or install the systemd unit and `systemctl --user start tabrunner`).
7. Observe stderr: `tabrunner listening on https://<tailscale-ip>:8443`.
8. In another terminal: `tabrunner pair`. Scan the printed QR with the PWA-target device.
9. On the device: browser opens, prompts to install client cert, then redirects to `/`. The PWA loads.
10. Click New Tab, type "hello", verify response streams in.

### Day-2 operations

| Task | Command |
|------|---------|
| Pair another device | `tabrunner pair` (run on host, scan from device) |
| Revoke a device | `tabrunner clients list` → find fingerprint → `tabrunner clients revoke <fp>` |
| List all sessions | `tabrunner sessions list` |
| Kill a runaway session | `tabrunner sessions kill <id>` |
| Restart server | `systemctl --user restart tabrunner` |
| Inspect logs | `journalctl --user -u tabrunner -f` |
| Rotate server cert | Delete `data/server-cert.pem`, restart. Auto-regenerated. CA stays. |
| Change project | Edit `config.toml` → restart |

### Failure recovery

| Symptom | First step | Then |
|---------|-----------|------|
| PWA can't connect | Check `tailscale status` on device | If OK, check `journalctl --user -u tabrunner -f` for TLS errors |
| TLS handshake fails on a previously-paired device | Cert may have expired or been revoked | Re-pair: `tabrunner pair` |
| `tabrunner serve` won't start | Read stderr | Common: tailscale not running, port in use, malformed config.toml, missing project dir |
| Session stuck | `tabrunner sessions kill <id>` | Reopen from History |
| Meta agent returns stale data | Check FTS indexer lag in logs | `tabrunner admin reindex` (future command) |
| DB corruption | Stop server | Restore from backup of `data/` |

---

## Enterprise Infrastructure Decisions

| Topic | Decision | Notes |
|-------|----------|-------|
| Logging | pino (JSON to stderr) | Pretty-print via pino-pretty in dev mode |
| Error handling | Typed AppError hierarchy with exit codes for CLI, structured WS error events for protocol | Categories: ValidationError, AuthError, NotFoundError, ConflictError, BackpressureError, InternalError |
| Configuration | TOML at `~/.config/tabrunner/config.toml`, env overrides via `TABRUNNER_*`, fail-fast on startup | Minimal v1 keys: project, tailscale_interface (opt), port (opt), data_dir (opt) |
| Auth | mTLS-TOFU with QR pairing | Constitution Principle II — overrides local preset's "no auth" default |
| CORS | N/A | Same-origin PWA + WS, no third-party origins |
| Security headers | HSTS, X-Content-Type-Options, X-Frame-Options: DENY, CSP (no inline scripts, strict-dynamic), Referrer-Policy: no-referrer | |
| Security scanning | Tier 1: Trivy (containers/files), Semgrep (TS), Gitleaks (secrets), `npm audit` | Run in CI on every push |
| Observability | [DEFERRED] No metrics/tracing infra in v1. Structured pino logs sufficient for single-operator debugging. | Add OpenTelemetry if multi-host or fleet usage emerges |
| Migration | Forward-only versioned SQLite migrations, auto-run on startup | Migration runner in `src/db/migrate.ts`; numbered SQL files under `migrations/` |
| API versioning | URL prefix `/api/v1/` | One consumer (own PWA); no backward-compat promise across v1 → v2 |
| Branching | Direct-to-main per `local` preset; conventional commits | Co-Author trailer per repo policy |
| CI/CD | GitHub Actions: lint, typecheck, unit, integration, contract, e2e (mcp-browser), Tier 1 security | No deploy stage — operator manually `git pull && npm run build && systemctl restart` |
| Rate limiting | [DEFERRED — recommendation: token-bucket per client fingerprint] | Not needed for single operator; revisit if shared tooling emerges |
| Graceful shutdown | 10s grace per session, then SIGKILL; flush DB on exit | SIGTERM handler in `src/server.ts` orchestrates shutdown |
| Health checks | `GET /health` (liveness, no auth required from localhost-only path) — returns `{ ok: true, version, tailscale_ip, sessions_running, uptime_s }` | `/ready` returns 200 only after DB migrations + FTS indexer initial sync |
| DX tooling | npm scripts (full inventory in FR-086), nix flake devshell, VS Code launch.json, pino-pretty in dev | One-command dev: `nix develop` then `npm run dev` |

---

## Testing

### Test tiers

- **Unit** (`tests/unit/`): pure functions, no I/O. Examples: config parser, cert generator (with stub random), FTS query builder, message parser. Stub-friendly inputs only.
- **Integration** (`tests/integration/`): real SQLite file, real bwrap, real `claude` (or a real stub binary `tests/helpers/fake-claude.ts` that exhibits the same I/O contract — reads stdin, writes JSONL to `~/.claude/projects/`). One test = one fresh SQLite file in `test-logs/`. **No mocks at this layer.**
- **Contract** (`tests/contract/`): WebSocket frame schema validation (zod), MCP tool schema validation, HTTP endpoint shape validation. Test that the wire format matches the documented contract.
- **E2E** (`tests/e2e/`): real PWA in headless Chromium via `mcp-browser`, real test server (with self-signed test CA), fake-claude binary. Agents drive the PWA to pair, open tabs, send messages, search history, ask the meta agent. Follows the spec-kit explore-fix-verify loop per `reference/mcp-e2e-web.md`.

### Testing functional requirements

- **FR-T1**: `npm run test` MUST run all four tiers and exit non-zero on any failure.
- **FR-T2**: `npm run test:unit` MUST run in < 10s. `test:integration` MUST run in < 2min. `test:contract` MUST run in < 30s. `test:e2e` MUST run in < 10min.
- **FR-T3**: Every test MUST output structured pino-parseable lines via the spec-kit test reporter (`tests/helpers/test-reporter.ts`) so the fix-validate loop can parse failures.
- **FR-T4**: Integration tests MUST NOT mock SQLite, bwrap, child_process, or filesystem operations. The whole point is to catch real-subprocess and real-DB bugs.
- **FR-T5**: E2E tests MUST cover: pair flow (US-1), single-tab session (US-2), multi-tab parallelism (US-3), close+reopen via history (US-4), meta agent observability query (US-5), search across sessions (US-6), admin CLI revoke (US-7), server restart resilience (US-8).
- **FR-T6**: Contract tests MUST cover: every WS event type, every REST endpoint, every MCP tool input/output schema.
- **FR-T7**: Per-story Independent Test (FR text in each user story) MUST be the named test in `tests/e2e/` for that story.

---

## Success Criteria

### Measurable outcomes

- **SC-001**: Pair-to-first-message latency ≤ 60 seconds on a Pixel/iPhone on the same Tailnet. [validates FR-007 through FR-011]
- **SC-002**: New-tab-to-first-token latency ≤ 3 seconds (with claude warm). [validates FR-016 through FR-020]
- **SC-003**: PWA bundle gzipped size ≤ 100 KB. [validates FR-066, FR-071]
- **SC-004**: 10 parallel sessions sustained for 30 min with no PTY/process leaks (PID count stable after `tabrunner sessions kill --all`). [validates FR-024, FR-027, FR-030]
- **SC-005**: WS disconnect-reconnect round-trip resumes stream within 1 second for buffered gaps. [validates FR-032]
- **SC-006**: FTS index lag ≤ 5 seconds between claude jsonl write and `search_messages` returning the row. [validates FR-044]
- **SC-007**: Server startup-to-listening latency ≤ 2 seconds on cold start (DB present). [validates FR-001 through FR-005]
- **SC-008**: Zero critical vulnerabilities reported by Tier 1 security scan (Trivy + Semgrep + Gitleaks + npm audit) in CI. [validates security scanning decision above]
- **SC-009**: All eight user stories pass their Independent Test in E2E. [validates SC for every US]
- **SC-010**: Meta agent's `tail_live` returns within 200ms p95 on a session with 10K stdout lines. [validates FR-055]
- **SC-011**: Path-traversal attempt via `read_project_file("../../etc/passwd")` returns 403 and logs the attempt. [validates FR-059]
- **SC-012**: Revoked client cert is rejected on the very next handshake (< 5s of revoke command). [validates FR-006, FR-015]
- **SC-013**: Running `tabrunner serve` against a `claude` binary whose `major.minor` differs from the expected pin exits with code 78 within 1 second of startup. [validates FR-091]
- **SC-014**: `tabrunner init` against a clean home directory completes successfully in under 10 seconds and produces a runnable installation (subsequent `serve` listens within 2s per SC-007). [validates FR-095, FR-096]
- **SC-015**: PWA chat-bubble rendering shows tool calls collapsed by default; clicking a summary line expands within 100ms. [validates FR-093]
- **SC-016**: Mobile keyboard sends a message via Cmd/Ctrl+Enter without inserting a newline. [validates FR-092]
- **SC-017**: All HTTP responses include the five mandated security headers; `curl -k -I https://<ip>:<port>/health --cert ... --key ...` confirms presence. [validates FR-097]
- **SC-018**: `/api/v1/ready` returns 503 during the initial FTS scan and 200 within 5s of scan completion on a 100-session corpus. [validates FR-098]
- **SC-019**: After a server build version bump, a connected PWA prompts the operator to reload within 60s of the next page navigation. [validates FR-099]

---

## Assumptions

- The operator's host runs a Linux distribution with systemd, bwrap, and tailscale available.
- The operator runs Tailscale and the PWA-target devices are on the same tailnet.
- The browser supports WebCrypto (ECDSA P-256 keygen) — this requires HTTPS context, which mTLS provides.
- The browser supports client certificate selection — this is the standard "user picks a cert from the OS store" dialog when the server requests a client cert. Mobile browsers (Safari iOS, Chrome Android) handle this differently than desktop; the pairing flow accommodates both.
- `claude` CLI is available on PATH inside the bwrap sandbox (mounted from the host's nix profile).
- The configured project directory exists, is readable by the server, and is the target of all sessions.
- Tailscale IP is stable enough that the server doesn't need to rebind mid-run.
- The host has enough RAM/CPU for the operator's concurrency choices (no admission control to enforce this).
- The operator backs up `data/` periodically (no auto-backup in v1).
- `tabrunner serve` is the only writer to `data/`.
- The watched project's `~/.claude/projects/<encoded>/` directory is writable by claude and readable by tabrunner (standard claude install).
