# Research — tabrunner 001-tabbed-pwa

This document captures every architecture / technology / pattern decision with rationale and rejected alternatives. Implementing and fix-validate agents consult this file *before* changing an architectural choice to fix a problem.

## How to read this file

- **Decision**: what was chosen.
- **Rationale**: why, in terms of constitution principles + spec requirements + user pushbacks.
- **Alternatives rejected**: what was considered and why not.
- **Apply when**: when this decision should bind agent behavior (i.e., when to consult).

User-delegated decisions are annotated `[delegated]`. User-chosen decisions are annotated `[user]`. Anything else is agent judgment from constitution + spec.

---

## D-001 Runtime: TypeScript strict on Node 22 [user]

**Decision**: Node 22 LTS, TypeScript with `"strict": true`, ESM modules, target ES2023.

**Rationale**: Node 22 is current LTS with stable `node:test`, `crypto.randomUUID`, native fetch, `Promise.withResolvers`. Strict TS catches the typo-class bugs that matter at our boundary (WS payload shapes, DB row shapes, MCP tool schemas).

**Alternatives rejected**:
- **Bun**: faster runtime, but `node-pty` and `better-sqlite3` native bindings are flaky; Tailnet tool over operator's machine needs reliability over benchmarks.
- **Deno**: clean TS-first, but requires more `npm:` adapter glue and the `node-pty`/bwrap story is worse.
- **Node 20**: works but loses `Promise.withResolvers` (small but nice) and runs out of LTS sooner.

**Apply when**: any time an agent considers reaching for `any`, suppressing TS errors, or downgrading to Node 20.

---

## D-002 Server framework: Fastify + @fastify/websocket [user]

**Decision**: Fastify 4.x with `@fastify/websocket` for WebSocket upgrades, native Node `https.createServer` underneath for mTLS.

**Rationale**:
- Plugin ecosystem fits our cross-cutting concerns (auth plugin, security-headers plugin, audit-log plugin, schema validation).
- Built-in JSON schema validation via Ajv — pairs well with zod for request shapes.
- @fastify/websocket integrates upgrades cleanly with the rest of the routing.
- Existing operator familiarity (agent-runner uses Fastify) reduces learning curve.

**Alternatives rejected**:
- **Hono**: tiny and modern, but plugin maturity for mTLS+WS isn't there yet; we'd be writing more glue.
- **Express**: legacy middleware model, slower, no built-in schema validation.
- **Node `http`/`https` directly with `ws`**: more code, no plugin pattern, every cross-cutting concern is hand-rolled.

**Apply when**: any agent considering a different HTTP framework, custom middleware system, or removing Fastify's plugin pattern.

---

## D-003 PWA framework: Preact + @preact/signals [user]

**Decision**: Preact 10.x with `@preact/signals` for reactive state.

**Rationale**:
- Bundle ≤100KB gzip cap (SC-003) is tight; Preact is ~3KB. React would burn most of the budget.
- Signals are well-suited to WS-driven state (tab list updates, per-tab message streams, connection status).
- esbuild has first-class Preact JSX support; no Babel pipeline needed.

**Alternatives rejected**:
- **React 19**: bigger bundle, no signals, more ceremony for our small UI.
- **Vanilla TS + lit-html**: smallest possible, but loses component model and forces hand-rolled state plumbing.
- **SolidJS**: nice reactivity, smaller community for tooling, less familiar.

**Apply when**: agent considering adding React, Redux, Zustand, Tailwind, or any large UI library.

---

## D-004 Storage: SQLite via better-sqlite3 [user]

**Decision**: SQLite single file (`<data_dir>/tabrunner.db`), WAL mode, accessed via better-sqlite3 (synchronous API).

**Rationale** (Constitution IV):
- Single file → trivial backup + restore.
- WAL mode → readers don't block writers; one writer at a time enforced by in-process mutex.
- Synchronous API → simpler code path; transactions are atomic without async coordination headaches.
- FTS5 virtual table support is built-in; no extra dependency.

**Alternatives rejected**:
- **node-sqlite3 (async)**: slower for our use case; async DB ops complicate the multi-writer guard.
- **Postgres**: overkill for single-user local tool; adds an operational dependency.
- **DuckDB**: analytical strengths irrelevant here; not as well-suited to transactional workload.
- **LMDB / RocksDB**: KV stores would force us to reinvent FTS.

**Apply when**: agent considering swapping the DB, adding a "real" database, or removing the write mutex.

---

## D-005 Subprocess sandbox: bubblewrap [constitution]

**Decision**: Each `claude` session spawns inside a `bwrap` sandbox with the spec-kit allowlist.

**Rationale** (Constitution III + matches parallel_runner.py):
- Project dir + per-session scratch are the only writable mounts.
- DNS restricted to: `api.anthropic.com`, `registry.npmjs.org`, `pypi.org`, `files.pythonhosted.org`, `cache.nixos.org`, `github.com`.
- `--unshare-pid` isolates PID namespace.
- No `~/.ssh`, no `~/.aws`, no `~/.claude` (auth handled via env passthrough).

**Alternatives rejected**:
- **No sandbox**: violates Constitution III.
- **Docker per session**: heavier (image + container per session); slower spawn; harder to capture stdout.
- **firejail**: less mature, less spec-kit parity.

**Apply when**: agent considering removing bwrap, weakening the allowlist, or running claude unsandboxed.

---

## D-006 PTY layer: node-pty [agent]

**Decision**: `node-pty` to attach a PTY to each claude subprocess.

**Rationale**:
- `claude` is interactive — slash commands, multi-line prompts, mid-stream interrupt (Ctrl-C) work via PTY but not via plain pipes.
- node-pty is the de-facto Node library for PTY; battle-tested in VS Code's integrated terminal.
- Requires `npm rebuild node-pty` after `npm install --ignore-scripts` (native bindings).

**Alternatives rejected**:
- **Plain `child_process.spawn` with pipes**: loses interactivity; claude CLI behaves differently in non-TTY mode.
- **`claude -p` (print mode) per message**: loses slash commands and mid-stream features; stateless overhead per message.
- **xterm.js in PWA + raw terminal forward**: gives the user a terminal, not a chat UI. Discarded UX direction.

**Apply when**: agent considering switching to pipes or print-mode.

---

## D-007 Auth: mTLS-TOFU with QR pairing [user, constitution]

**Decision**: Per Constitution II. Self-signed CA at `<data_dir>/ca.pem`+`ca-key.pem`. Server cert signed by CA. Client cert per device: browser generates ECDSA P-256 keypair via WebCrypto, posts CSR to `/pair/<token>/csr`, server signs and returns cert + CA. Pairing token: 5-min TTL or single-use (whichever first). Client cert: 365-day TTL. Revocation: in-memory set + DB column, effective on next handshake.

**Rationale**:
- Tailscale alone (network perimeter) + mTLS (endpoint auth) = defense in depth.
- In-browser keygen means private key never transits the wire.
- TOFU + QR keeps UX to one scan per device.
- The five-min TTL + single-use combo means a stolen pairing URL is useless past either condition.

**Alternatives rejected**:
- **No auth, trust Tailscale only**: single layer; if Tailscale ACL slips, the server is wide open.
- **Pre-shared bearer token**: less device-isolated; can be copied between devices.
- **Username/password**: not single-device-bound; not OS-cert-store integrated.
- **OAuth/OIDC**: needs identity provider; overkill for single-user.
- **Server-issued client keypair (private key shipped to browser)**: private key transits pairing channel; weaker than in-browser keygen.

**Apply when**: agent considering bypassing mTLS for "easier testing", swapping to bearer tokens, or weakening any TTL.

---

## D-008 Tailscale binding: shell-out to `tailscale ip -4` [user]

**Decision**: `src/tailscale/discover.ts` runs `tailscale ip -4` at startup, parses first line, binds the server to that IPv4. Fail fast (exit 78) if the command fails or returns no IP.

**Rationale**: No API token required, reliable across Tailscale versions, simple to test (mock `child_process.execSync` for unit tests).

**Alternatives rejected**:
- **Local socket API** (`/var/run/tailscale/tailscaled.sock`): more structured but requires socket parsing; not needed for our single field.
- **Bind to 0.0.0.0 + tailscale serve**: violates Constitution I.
- **Manual `tailscale_interface` config only**: brittle if user's interface name changes; auto-discover + optional override is the friendliest default.

**Apply when**: agent considering binding to `0.0.0.0`, `127.0.0.1`, or using a different discovery mechanism.

---

## D-009 Session continuation: `claude --resume <uuid>` [user]

**Decision**: tabrunner tracks session UUIDs and metadata; the conversation history is owned by Claude Code itself in `~/.claude/projects/<encoded-path>/<uuid>.jsonl`. Reopening a closed tab spawns `claude --resume <uuid>` in a fresh bwrap (or attaches to the still-alive PID if any).

**Rationale**: claude already implements conversation replay correctly. Re-implementing it would duplicate work and be a constant source of drift bugs.

**Alternatives rejected**:
- **Roll our own message replay**: more code, more bugs, divergence from claude.
- **Always start a fresh session with old transcript as context**: loses true continuation.
- **Mirror messages into our DB and replay from there**: doubles storage, still need to call claude with context.

**Apply when**: agent considering implementing parallel session storage, conversation replay, or not using `--resume` on reopen.

---

## D-010 FTS over claude's JSONL via watcher [user]

**Decision**: `chokidar` watches `~/.claude/projects/<encoded-project-path>/` for new and modified `.jsonl` files. `jsonl-parser.ts` reads the tail, derives message rows, upserts into FTS5 `messages_fts` table. Indexing latency target: <5s.

**Rationale**: claude's JSONL is authoritative — single source of truth. We index it; we don't duplicate it. If claude's format changes, the parser breaks loudly (caught by FR-091 version pin).

**Alternatives rejected**:
- **Mirror messages into our own table on stdout intercept**: brittle (PTY output is ANSI-formatted; parsing it is harder than parsing JSONL), redundant.
- **grep over JSONL on demand**: O(N) per query; tab history view needs <1s search.
- **Embedding-based search**: overkill for v1; FTS5 keyword search is the right primitive.

**Apply when**: agent considering not using FTS5, or building parallel message storage.

---

## D-011 Meta agent runtime: pinned claude session with MCP server [user]

**Decision**: The meta agent is a `claude` session like any other, spawned with `--session-id <meta-uuid>` and `.mcp.json` exposing the tabrunner MCP server on stdio. Pinned (always first tab), visually distinguished in PWA. Read-only tool surface per Constitution VI.

**Rationale**:
- Same spawn mechanism = code reuse and predictable behavior.
- claude already handles tool-call rendering, slash commands, model selection.
- MCP enforces the tool surface — there's no `spawn_session` tool to expose by accident.

**Alternatives rejected**:
- **Direct Anthropic Messages API call from server**: reimplements claude; loses slash commands, conversation history, model switching.
- **Headless `claude -p` per query**: stateless, no conversation context, slower per-query.
- **Two-process model (separate meta-agent binary)**: more moving parts; one less spawn path is one less thing to test.

**Apply when**: agent considering bypassing the MCP layer or making the meta agent a direct API caller.

---

## D-012 MCP tool surface: 9 read-only tools [user]

**Decision** (see contracts/mcp.md for full schemas):

| Tool | Purpose |
|------|---------|
| `query_sessions(filter)` | List session metadata by project/date/status |
| `read_session(session_id, since?)` | Read one session's messages |
| `tail_live(session_id, lines?)` | Last N stdout bytes from running PID |
| `list_running()` | Enumerate active sessions |
| `search_messages(query, scope?)` | FTS5 over message text |
| `search_sessions(query)` | FTS over titles/first-messages/project paths |
| `read_project_file(path)` | Read file in watched project (path-guard 403) |
| `list_project_files(glob?)` | Glob in watched project |
| `get_session_summary(session_id)` | 60s-cached summary |

**Rationale**: enough to answer "what's happening across sessions" without enabling mutation. Path-traversal guard on file tools.

**Alternatives rejected**:
- **Operator-mode tools (`kill_session`, `spawn_session`, `edit_file`)**: out of v1 per Constitution VI; needs confirmation UI + audit + kill switch.
- **Embedding-based semantic search**: overkill for v1; FTS5 keyword search is sufficient.
- **One unified `query` tool**: bad UX for the meta agent (no schema discoverability via MCP).

**Apply when**: agent considering adding a write tool to the meta agent's surface in v1.

---

## D-013 No concurrency cap [user, explicit pushback]

**Decision**: Server spawns as many `claude` sessions as requested. No queue, no admission control, no max-concurrency limit. PWA shows a "N running" badge from N≥2.

**Rationale**: Operator's explicit preference — trust the operator, don't artificially limit. The user said "no limit" when prompted with safety-valve alternatives.

**Trade-off** (documented): high API spend bursts possible; theoretical OOM on small hosts. Operator accepts.

**Apply when**: agent considering adding a concurrency cap, queue, or admission control for "safety". DO NOT add. User explicitly rejected this.

---

## D-014 Closed-tab model: disappear from bar, reopen from history [user]

**Decision**: Closing a tab removes it from the active tab bar immediately. Sessions persist in the History view (FTS-indexed). Reopen calls `claude --resume <uuid>` (attaches to live PID if alive).

**Rationale**: Keeps the tab bar uncluttered. History view is the source of truth for past sessions. Matches mental model "tab = current focus; history = past work".

**Alternatives rejected**:
- **Closed tabs stay greyed in tab bar**: clutters bar fast.
- **Tabs never close (only hide)**: needs separate management UI; same clutter problem.

**Apply when**: agent designing tab bar behavior.

---

## D-015 Config file: minimal TOML at standard XDG path [user]

**Decision**: `~/.config/tabrunner/config.toml`. Required: `project`. Optional: `port`, `tailscale_interface`, `data_dir`. Validated via zod schema, fail-fast on invalid.

**Rationale**: TOML is friendlier for hand-editing than JSON, simpler than YAML. Standard XDG path so operator can find it. Minimal v1 surface = less to spec/test/document; future multi-project work can extend.

**Alternatives rejected**:
- **Rich config (logging level, max-concurrency, cert TTLs, etc.)**: most are not v1 settings; defaults in code are fine.
- **JSON config**: less ergonomic for hand-editing.
- **No config file (CLI flags only)**: requires re-typing flags on every `serve`; bad systemd UX.

**Apply when**: agent considering moving config to env-var-only or adding many optional knobs.

---

## D-016 First-run UX: explicit `tabrunner init` [user]

**Decision**: `tabrunner serve` fails fast (exit 78) if config / data dir / CA / DB missing. The operator runs `tabrunner init` first. Init is interactive: prompts for project path, creates config + data dir, generates CA + server cert, initializes DB.

**Rationale**: Auto-init hides security artifacts (CA key) from operator awareness. Explicit init = explicit consent to generate secrets.

**Alternatives rejected**:
- **Auto-init on first serve**: less ceremony but hides CA generation.
- **Config-only init, auto-CA on serve**: middle ground; rejected because the CA is a security artifact and should require explicit creation step.

**Apply when**: agent considering auto-creating any security artifact silently.

---

## D-017 claude version pinning [user]

**Decision**: Pin `claude` in `flake.nix` to a specific version. Server reads `claude --version` at startup; if parsed `major.minor` doesn't match `EXPECTED_CLAUDE_MAJOR_MINOR` constant, exit 78 with clear message. Upgrades = bump flake + bump constant + run regression tests (JSONL parser + `--resume` flow).

**Rationale**: claude's JSONL schema and `--resume` flag are upstream surface area we depend on. Drift breaks us silently otherwise.

**Alternatives rejected**:
- **No pin**: catch breakage at runtime via parse errors; bad operator experience.
- **Pin in flake but no startup check**: trusts the dev environment; misses production drift if operator updates host claude.

**Apply when**: agent considering removing the version check or bumping the constant without running regression tests.

---

## D-018 Send-key behavior: Enter + Cmd/Ctrl+Enter [user]

**Decision**: `Enter` sends; `Shift+Enter` inserts newline; `Cmd+Enter` and `Ctrl+Enter` also send (mobile parity).

**Rationale**: Matches claude.ai, Slack, Discord conventions. Cmd/Ctrl+Enter covers mobile keyboards where Shift+Enter is awkward.

**Apply when**: agent designing composer key bindings.

---

## D-019 Tool-call render: collapsed by default [user]

**Decision**: Tool calls render as one-line summary `<tool>: <preview>`; click to expand args + result. Results >50 lines truncate with "show full".

**Rationale**: Chat stays scannable. Matches claude's own CLI display ethos. Operator can drill into specifics when needed.

**Apply when**: agent designing message rendering.

---

## D-020 CA key protection: chmod 600 + README warning [user]

**Decision**: `data/ca-key.pem` created with mode 0600 and owned by serve user. No encryption-at-rest. README has "Backup" section warning data/ backups must be treated as secrets.

**Rationale**: For a single-operator local tool, encryption-at-rest adds operational complexity (passphrase handling, restart UX) without proportional benefit. Tailscale + host security is the threat model.

**Apply when**: agent considering adding passphrase encryption, age/SOPS, or HSM integration to v1.

---

## D-021 PWA service worker: cache shell, version-poll for updates [agent]

**Decision**: SW caches HTML/JS/CSS/manifest/icons. Build-time version string baked into SW. PWA fetches `/api/v1/sw-version` on each page load; if newer, `skipWaiting()` + notify clients via `MessageChannel`. SW never caches `/api/v1/*` responses.

**Rationale**: Offline shell rendering with "reconnecting" UX (FR-069); reliable update path so a stale PWA doesn't hide a fixed bug.

**Alternatives rejected**:
- **No service worker**: drops PWA install ability; loses offline shell.
- **Cache API responses**: stale data risks; we want server as source of truth.

**Apply when**: agent designing PWA update / caching strategy.

---

## D-022 Test runner: native `node:test` via tsx [agent]

**Decision**: `tsx --test`. Spec-kit structured reporter (`tests/helpers/test-reporter.ts`). c8 for coverage.

**Rationale**: Built into Node 22 — one fewer dep than Jest/Vitest. tsx handles TS transpile on the fly. Reporter writes JSONL parseable by the runner.

**Alternatives rejected**:
- **Jest**: heavy, slow, requires its own TS transformer setup.
- **Vitest**: nicer DX but adds a dep and is overkill for our test surface.
- **Bun test**: depends on Bun runtime (D-001 rejected Bun).

**Apply when**: agent considering swapping the test runner.

---

## D-023 E2E driver: mcp-browser (spec-kit pattern) + Playwright regression [agent]

**Decision**: MCP exploration via `nix-mcp-debugkit`'s `mcp-browser` (headless Chromium). Per-story scripted regressions in `tests/e2e/*.test.ts` using Playwright. Setup/teardown via `tests/e2e/setup.sh`/`teardown.sh`.

**Rationale**: spec-kit's `reference/mcp-e2e-web.md` pattern — exploration finds bugs via agent-driven interaction; regression freezes the fix. Playwright also adds visual regression option later.

**E2E test exception to Constitution I**: `TABRUNNER_E2E_TEST=1` env var allows binding to `127.0.0.1` for tests. Production code path (no env var set) refuses non-Tailscale binds.

**Apply when**: agent considering replacing the dual exploration+regression model with one or the other.

---

## D-024 Logging: pino + correlation IDs [user]

**Decision**: pino structured JSON to stderr, default `info` level. `TABRUNNER_LOG_LEVEL` env override. `TABRUNNER_LOG_DEV=1` for pino-pretty. Correlation IDs: `connection_id`, `session_id`, `audit_id`.

**Rationale**: pino is the fastest Node logger; structured JSON is queryable via `journalctl ... | jq`; correlation IDs let operator trace one request across many lines.

**Apply when**: agent considering swapping to console.log or winston.

---

## D-025 Error hierarchy: typed AppError with HTTP + CLI exit codes [agent]

**Decision**: `AppError` base. Subclasses: `ValidationError` (400), `AuthError` (401/403), `NotFoundError` (404), `ConflictError` (409), `BackpressureError` (503), `InternalError` (500). Each has `httpStatus`, `cliExitCode`, `userMessage`.

**Rationale**: Single error type → consistent rendering in HTTP and CLI. CLI exit codes follow conventional: 0 success, 1 generic, 78 config error.

**Apply when**: agent considering throwing raw `Error` or string from production code paths.

---

## D-026 No metrics / tracing infra in v1 [agent + preset]

**Decision**: Local preset defaults; we don't add OpenTelemetry, Prometheus, or external error reporting in v1. Pino structured logs are sufficient for single-operator debugging.

**Rationale**: Adds operational dependencies (collector, dashboard, retention policy) that single-operator scale doesn't justify.

**Apply when**: agent considering wiring up Prometheus, Sentry, OTLP collectors, or Grafana for v1.

---

## D-027 Rate limiting: deferred with recommendation [agent + preset]

**Decision**: No rate limiting in v1. If we ever need it, recommendation = token-bucket per client cert fingerprint.

**Rationale**: Single operator means natural rate-limiting (operator can't make 1000 req/s by hand). Multi-operator or shared tooling = revisit.

**Apply when**: agent considering adding rate limiting to v1.

---

## D-028 Security headers: strict baseline [agent]

**Decision** (FR-097): HSTS (2 years), X-Content-Type-Options nosniff, X-Frame-Options DENY, Referrer-Policy no-referrer, CSP `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' wss://*; frame-ancestors 'none'`. The `'unsafe-inline'` style-src is the one concession — required for per-tab inline color styles. Remove when all styles are hashed/nonced.

**Rationale**: Defense in depth even though we're mTLS-protected. CSP prevents accidental XSS escalation.

**Apply when**: agent considering loosening any header.

---

## D-029 Branching: direct-to-main [preset]

**Decision**: Direct commits to main per `local` preset. Conventional commit messages. Co-Author trailer for Claude commits.

**Rationale**: Solo developer, no PR ceremony required. CI still runs on every push.

**Apply when**: agent considering creating feature branches or opening PRs unprompted.

---

## D-030 CI/CD: GitHub Actions, no deploy stage [preset]

**Decision**: `.github/workflows/ci.yml` runs lint, typecheck, unit, integration, contract, e2e, build, security-scan (Trivy + Semgrep + Gitleaks + npm audit). Local preset: no deploy stage; operator pulls and restarts manually.

**Apply when**: agent considering adding a deploy job, a release-automation job, or skipping security scans for time.

---

## D-031 Process supervision: systemd user unit [user]

**Decision**: Ship `etc/systemd/tabrunner.service` (user unit). Operator runs `make install` (or equivalent) to symlink into `~/.config/systemd/user/`. `Restart=always`.

**Rationale**: Standard Linux init, journal logs work out of the box, auto-restart on crash.

**Alternatives rejected**:
- **tmux/screen**: requires terminal session; bad UX for set-and-forget.
- **process-compose**: good for dev, worse for production single-binary daemons.

**Apply when**: agent considering removing the systemd unit or adding Docker/k8s.

---

## D-032 History retention: forever, manual prune [user]

**Decision**: No background pruning of session history. Operator can manually run `tabrunner admin prune --older-than <duration>` (post-v1).

**Rationale**: Storage is cheap, conversations are valuable, accidental loss is more painful than disk usage.

**Apply when**: agent considering adding automatic retention policies.

---

## D-033 Tab-close grace period: 10 seconds [user]

**Decision**: SIGTERM first; wait 10s; SIGKILL.

**Rationale**: Balance — long enough for claude to flush jsonl, short enough to feel responsive.

**Apply when**: agent considering changing the grace period.

---

## D-034 Pairing QR token TTL: 5 minutes [user]

**Decision**: Token valid for 5 min OR until first successful use, whichever first.

**Rationale**: Walk-to-device latency budget, minimal exposure window if URL leaks.

**Apply when**: agent considering changing TTL.

---

## D-035 Client cert validity: 365 days [user]

**Decision**: Client cert TTL is 365 days. Revocation via admin CLI.

**Rationale**: Operator convenience; eventual auto-expiry of forgotten devices.

**Apply when**: agent considering auto-rotation or shorter TTL.

---

## D-036 Server restart: kill all sessions on shutdown [user]

**Decision**: On SIGTERM, server SIGTERMs every running claude (10s grace, then SIGKILL). PWA reconnects after restart. Sessions resume via `claude --resume`.

**Rationale**: Simpler ownership model than detaching PIDs across restarts. The reopen-via-`--resume` path covers the recovery flow cleanly.

**Apply when**: agent considering implementing PID handoff across restarts.

---

## D-037 PWA viewport: mobile-first responsive [user]

**Decision**: Single PWA codebase. Tab bar collapses to drawer at viewport <768px. Touch targets ≥44px.

**Rationale**: Operator will use the PWA from a phone over Tailscale frequently.

**Apply when**: agent considering desktop-only or two-codebase split.

---

## D-038 PWA offline: shell only, no IndexedDB cache [user]

**Decision**: Service worker caches HTML/JS/CSS shell. Session content is fetched live; no IndexedDB cache.

**Rationale**: Server is the source of truth; reload-on-reconnect is acceptable UX. IndexedDB cache adds complexity (sync, conflict resolution) for marginal value.

**Apply when**: agent considering full offline mode.

---

## D-039 Stream format: raw + parsed [user]

**Decision**: WS sends both `session.stdout` (raw ANSI bytes, base64) AND `session.message` (parsed from JSONL: user/assistant/tool_call/tool_result). PWA renders parsed by default, raw available via "Show raw" toggle.

**Rationale**: Parsed is the primary UX. Raw is the escape hatch (copy verbatim, debug stalled streams).

**Apply when**: agent considering dropping either channel.

---

## D-040 Project root: single project per server instance [user, constitution]

**Decision**: One server = one watched project. Multi-project = run multiple `tabrunner serve` on different ports.

**Rationale**: Constitution-level scope decision. Multi-project is a deferred feature.

**Apply when**: agent considering multi-project switching in v1.

---

## User preferences and pushbacks (carry forward to all phases)

- **Do not add a concurrency cap.** Explicit pushback (D-013).
- **Do not use the TypeScript Agent SDK in-process.** Shell out to claude CLI.
- **Do not expose write/spawn/kill MCP tools to the meta agent in v1.** Constitution VI.
- **Do not bind to 0.0.0.0 or 127.0.0.1 in production paths.** Constitution I; one E2E test exception via env var.
- **Do not mock SQLite, bwrap, or child_process at integration tier.** Constitution V.
- **Do not introduce React, Tailwind, or large UI libraries.** Bundle cap SC-003.
- **Do not auto-create the CA without operator-initiated `init`.** D-016.
- **Do not skip the claude version startup check.** D-017.
- **Do not add automatic prune or rotation.** D-032, D-035.

## DX friction summary

| Activity | Friction | How to reduce |
|----------|----------|---------------|
| First clone → working dev shell | `git clone && cd && nix develop` | flake covers everything |
| Install dependencies | `npm install --ignore-scripts && npm rebuild better-sqlite3 node-pty` | Scripted as `npm run setup` |
| Run dev server | `npm run dev` (concurrent server + PWA bundle watch) | One command via dev-full.sh |
| Run tests | `npm run test` runs all tiers | Single command |
| Pre-PR validation | `make pre-pr` | One command |
| Add a new dep | Add to `package.json`, run `npm install --ignore-scripts`, optionally `npm rebuild <name>` for native | No global installs |
| Bump claude version | Update flake input, bump `EXPECTED_CLAUDE_MAJOR_MINOR`, run integration tests | Documented in RUNBOOK |

**Manual setup steps remaining after `nix develop`**:
1. `npm install --ignore-scripts && npm rebuild better-sqlite3 node-pty` (one time)
2. `tabrunner init` (one time per host)
3. `tabrunner serve` (or `systemctl --user start tabrunner`)
4. `tabrunner pair` per device (one time per device)

That's the minimum operator setup. No env vars to fill in (no third-party API keys in v1; Anthropic OAuth is handled by claude itself).
