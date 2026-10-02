# Interview notes — 001-tabbed-pwa

## Project preset
- **preset: local**
- Override: mTLS-TOFU auth is included (not skipped per preset default). Rationale: multi-device single-user over Tailscale needs endpoint auth as defense in depth. Captured as Principle II in the constitution.

## Nix / system availability
- Nix available: yes
- Tailscale available: yes
- bwrap available: yes
- claude CLI available on host: yes (`/run/current-system/sw/bin/claude`)

## Bootstrap state
- code-review-graph: wired at phase 0, watcher active, CLAUDE.md stanza installed.
- spec-kit: v0.4.1 via uvx, offline assets used.
- Project at: `/home/max/git/agent-framework/skills/spec-kit/runner-ts/`.

## Key decisions (with rationale)

### Architecture
- **TypeScript strict** (Principle V). No mocks at integration boundaries.
- **Node 22** runtime. `tsx` for dev, `tsc` for build, esbuild for PWA bundling.
- **Fastify + @fastify/websocket** for HTTP+WS server. Rationale: plugin ecosystem, built-in JSON schema validation, used by agent-runner.
- **Preact + signals** for PWA. Rationale: 3kb, used by agent-runner, signals fit WS state well.
- **SQLite via better-sqlite3** for history. Single file `data/tabrunner.db`, WAL mode, in-process mutex on writes.
- **FTS5** virtual table over messages for cross-session search.
- **node-pty** for claude subprocess management — required so interactive CLI features (slash commands, mid-stream interrupt, multi-line) work via PTY rather than plain stdin/stdout pipe.
- **pino** for structured JSON logging.

### Auth
- **mTLS-TOFU with QR pairing**. Server-signed client certs via in-browser WebCrypto CSR.
- **QR token TTL: 5 minutes** OR single-use (whichever first).
- **Client cert TTL: 365 days**, manual revoke via `tabrunner clients revoke <fp>`.
- **Revocation effective immediately on next TLS handshake**.

### Tabs & sessions
- **1 tab = 1 claude session** with UUID, per Principle III.
- **No concurrency cap.** Operator explicitly chose this; UI shows a "N running" indicator from N≥2.
- **Lean on `claude --resume`** for session continuation rather than rolling our own replay. tabrunner tracks session UUIDs + metadata; claude owns the conversation jsonl.
- **Tab close**: SIGTERM, 10s grace, SIGKILL.
- **Closed tabs disappear from active bar**, reachable from History view. Reopen via `claude --resume <uuid>` in a fresh bwrap.
- **PTY-based stdin** — operator types in PWA composer, server writes to claude PTY stdin.
- **Stream both raw stdout bytes AND parsed messages** from jsonl over WS.

### Meta agent
- **Read-only observability assistant** (Principle VI).
- **Runtime**: A pinned, dedicated `claude` session with `.mcp.json` exposing the tabrunner MCP server on stdio. Same spawn mechanism as a regular tab; just pinned, pre-configured, visually distinguished.
- **MCP tool surface** (all read-only):
  - `query_sessions(filter)` — list sessions by project/date/status.
  - `read_session(session_id, since?)` — read messages from one session.
  - `tail_live(session_id, lines?)` — last N stdout bytes from a running session.
  - `list_running()` — active session enumeration.
  - `search_messages(query, scope?)` — FTS5 over message text.
  - `search_sessions(query)` — FTS over session titles/first-messages/project paths.
  - `read_project_file(path)` — read file in watched project (path-traversal guard, 403 + audit log).
  - `list_project_files(glob?)` — glob in watched project.
  - `get_session_summary(session_id)` — cached 60s summary.
- **No spawn/kill/edit/shell tools** — promotion to operator mode is a future feature with its own spec.

### Storage
- **One DB**, sessions table, messages_fts virtual table, clients table, pairing_tokens table, _meta table.
- **JSONL watcher** reads `~/.claude/projects/<encoded-path>/<uuid>.jsonl` and upserts into FTS5. Target lag < 5s.
- **History retention: forever**. Manual `tabrunner admin prune --older-than <d>` if needed (admin CLI; not v1 P1).

### Operations
- **Config**: TOML at `~/.config/tabrunner/config.toml`. Required: `project = "<path>"`. Optional: `port`, `tailscale_interface`, `data_dir`.
- **Tailscale binding**: shell out to `tailscale ip -4` at startup, fail fast if unavailable. Bind exclusively to that IP.
- **Process supervision**: systemd user unit shipped in repo.
- **Server restart**: kill all running claude on shutdown; PWA reconnects and re-fetches state. Sessions resume via `claude --resume`.
- **Graceful shutdown**: 10s per-session grace, then SIGKILL; flush DB.

### PWA UX
- **Mobile-first responsive**. Tab bar collapses to drawer at < 768px. Touch targets ≥ 44px.
- **Installable PWA** with service worker. Shell cached offline; session content fetched live.
- **No IndexedDB cache** of session content in v1.
- **Chat-bubble UI** for parsed messages; "Show raw" toggle for ANSI bytes.
- **History view** with FTS search.

### Admin CLI (v1 commands)
- `tabrunner init` — interactive first-time setup; idempotent; refuses to overwrite without `--force`.
- `tabrunner serve` — fail-fast if init artifacts missing (config, data dir, CA, DB).
- `tabrunner pair`
- `tabrunner clients list|revoke <fp>`
- `tabrunner sessions list|kill <id>`

### Clarifications (Phase 3)
- **claude version pinning**: flake.nix pins `claude` to a specific version; server reads `claude --version` at startup and exits 78 if `major.minor` doesn't match `TABRUNNER_EXPECTED_CLAUDE_MAJOR_MINOR`. Upgrades = bump flake + bump constant + run JSONL-parser/`--resume` regression tests.
- **PWA send-key**: Enter sends; Shift+Enter newline; Cmd/Ctrl+Enter also sends for mobile parity. Send button always present.
- **Tool-call UI**: collapsed-by-default single-line summary (`<tool>: <preview>`), click to expand args/result, results >50 lines truncate with "show full".
- **CA key protection**: chmod 600 only, no encryption-at-rest. README has explicit "Backup" section warning that data/ backups carry the CA key and must be protected.
- **First-run UX**: `tabrunner serve` fails fast if config/data dir/CA/DB are missing, instructing operator to run `tabrunner init`. Init is interactive, prompts for project path, generates CA, creates DB, idempotent on re-run.

### Testing
- **Four tiers**: unit, integration, contract, e2e.
- **Integration**: real SQLite, real bwrap, real `claude` (or stub binary with same I/O contract). No mocks.
- **E2E**: `mcp-browser` headless Chromium driving the real PWA against a real test server. Follows spec-kit explore-fix-verify loop.

## Rejected alternatives

- **Anthropic Agent SDK in-process** — rejected: loses slash commands and existing bwrap/auth setup.
- **JSONL append-only logs as primary store** — rejected: harder to query for tab history UI; kept as derived artifact.
- **Postgres** — rejected: overkill for single-user.
- **DB per project** — rejected: cross-project queries planned, simpler ops with one file.
- **Tailscale-only auth without mTLS** — rejected: defense in depth wanted.
- **Pre-shared token in localStorage** — rejected: less device-isolated than mTLS client certs.
- **Meta agent as full operator (v1)** — rejected for scope: needs confirmation UI, audit log, kill switch.
- **POC / Enterprise presets** — rejected: want full local rigor without multi-user scope.
- **Hono / plain node:http** — rejected in favor of Fastify for mTLS+WS specifics and plugin ecosystem.
- **Vanilla TS / React / SolidJS** — rejected in favor of Preact+signals for tab/streaming UX.
- **`claude -p` per message** — rejected: loses interactive features like slash commands and mid-stream interrupt.
- **xterm.js in PWA** — rejected: chat UX is the primary interaction model.
- **Roll our own conversation replay** — rejected once `claude --resume` was confirmed available.
- **Mirror messages into our DB and FTS over that** — rejected in favor of indexing claude's authoritative jsonl directly via a watcher.
- **Always start a fresh session on reopen** — rejected in favor of `--resume` for true continuation.
- **Rich config file** — rejected for v1; minimal config keeps surface small.
- **Auto-prune history** — rejected; storage cheap, conversations valuable.
- **5s / 30s tab-close grace** — rejected in favor of 10s as the responsiveness/cleanliness balance.
- **0.0.0.0 binding** — rejected as constitutional violation.
- **Direct Anthropic API for meta agent** — rejected; meta = pinned claude session for UX consistency.

## Things to push back on if downstream agents try them
- **Do not** add admission control / queueing — operator explicitly chose no cap.
- **Do not** add a TypeScript Agent SDK dependency — we shell out to `claude` CLI.
- **Do not** expose any write/spawn/kill MCP tool to the meta agent in v1.
- **Do not** bind to `0.0.0.0` or `127.0.0.1` even for "easier local testing" — fail fast if tailscale is down.
- **Do not** mock SQLite, bwrap, or child_process at the integration tier.
- **Do not** add a per-message Anthropic API call for the meta agent — it's a claude session like any other.
- **Do not** introduce React, Tailwind, or large UI libraries — Preact + minimal CSS keeps bundle ≤ 100 KB gzip.

## Enterprise infrastructure decisions summary
Captured in spec.md "Enterprise Infrastructure Decisions" table. Accepted everywhere; only deferred items: observability infrastructure (metrics/tracing — not needed at single-operator scale) and rate limiting (not needed; recommendation captured).

## Stripe integration
- Payment integration: none (no commerce keywords in description).

## Platform Runtime & E2E
- mcp-browser — PWA (headless Chromium on Linux). Always on.
- mcp-android — NOT applicable (no native mobile app; PWA from mobile Safari/Chrome is fine).
- mcp-ios — NOT applicable.

## Project description (1-2 sentences)
A Tailscale-bound TypeScript server and Progressive Web App that lets a single operator run multiple sandboxed `claude` CLI sessions in parallel browser tabs, with a pinned read-only "meta agent" tab that uses MCP tools to query history and tail live output across every session. Auth is mutual TLS with QR-pairing TOFU.
