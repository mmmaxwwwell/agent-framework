# Tasks: tabrunner 001-tabbed-pwa

**Input**: Design documents from `specs/001-tabbed-pwa/`
**Prerequisites**: [spec.md](./spec.md), [plan.md](./plan.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [workflows.md](./workflows.md), [interview-notes.md](./interview-notes.md)

**Approach**: Fix-validate loop. Each phase: build → typecheck → lint → test (unit + integration + contract) → security scan → read `test-logs/<phase>-<run>.jsonl` failures → fix code → re-run until green. E2E phase tasks use `[needs: mcp-browser, e2e-loop]` per the runner contract; workflows in [workflows.md](./workflows.md) are the test source of truth.

**Preset**: `local` (with mTLS-TOFU override). See [interview-notes.md](./interview-notes.md) for full preset application notes.

**Non-Goals reminder** (see spec.md § Non-Goals): no multi-user, no runtime multi-project, no operator-mode meta agent, no concurrency cap, no cloud sync, no Windows/macOS, no auto-prune, no IndexedDB session cache, no xterm.js terminal. If an agent encounters an unlisted scenario, check Non-Goals before implementing; if not listed and genuinely ambiguous, write `BLOCKED.md`.

## Format

`[T### ] [P?] [Tags] Description`

- `[P]`: can be parallelized (different files AND no shared singleton resource)
- `[needs: gh]`: granted GitHub CLI access at runtime
- `[needs: gh, ci-loop]`: runner-managed CI debug cycle
- `[needs: mcp-browser, e2e-loop]`: runner-managed E2E exploration loop
- `[FR-xxx]`, `[SC-xxx]`, `[US-x]`: traceability tags
- `[produces: IC-xxx]` / `[consumes: IC-xxx]`: internal interface contract tags
- `Done when:` — concrete completion criteria (verifiable, non-stub, exact names where pinned)

---

## Phase 1: Setup & Test Infrastructure

**Purpose**: bootstrap the dev environment, test infrastructure, and code-review-graph. No feature code yet.

- [ ] **T001** [P] Add project dependencies to `package.json`: fastify, @fastify/websocket, better-sqlite3, node-pty, pino, pino-pretty, zod, chokidar, qrcode, preact, @preact/signals, @modelcontextprotocol/sdk, @iarna/toml (or smol-toml). Dev deps: tsx, typescript, esbuild, @types/node, eslint, @typescript-eslint/{parser,eslint-plugin}, prettier, c8, playwright, size-limit. Run `npm install --ignore-scripts && npm rebuild better-sqlite3 node-pty`. [FR-089]
  Done when: `package.json` contains all listed deps; `package-lock.json` exists; `node_modules/better-sqlite3/build/Release/better_sqlite3.node` exists; `node_modules/node-pty/build/Release/pty.node` exists; `npm ls --depth=0` exits 0.

- [ ] **T002** Update [flake.nix](../../flake.nix) to add `claude` (Claude Code CLI) at a pinned version. Try `pkgs.claude-code` first; if not in nixpkgs or wrong version, write a derivation that fetches the upstream tarball or GitHub release for the target version. Update [research.md](./research.md) Tool environment inventory with the chosen approach. [FR-091] [IC-012]
  Done when: `nix develop --command claude --version` prints a version whose `major.minor` matches `EXPECTED_CLAUDE_MAJOR_MINOR` in `src/config/claude-version.ts`; `flake.lock` updated; flake committed.

- [ ] **T003** [P] Add `nix-mcp-debugkit` as a flake input and re-export `packages.mcp-browser` and `packages.mcp-browser-config` (Nix-store-pinned `mcp/browser.json`). Add a `nix-mcp-debugkit` line to [flake.nix](../../flake.nix) inputs. [FR-T5, plan.md § Real-runtime E2E]
  Done when: `nix run .#mcp-browser -- --help` succeeds; `.mcp.json` updated to reference the pinned path; flake.lock updated.

- [ ] **T004** [P] Add `Bash(nix run .#mcp-browser:*)`, `Bash(npm run build:*)`, `Bash(npm run start:*)`, `Bash(tests/e2e/setup.sh:*)`, `Bash(tests/e2e/teardown.sh:*)`, `Bash(tabrunner *:*)`, `Bash(systemctl --user *:*)`, `Bash(journalctl --user *:*)` to `.claude/settings.json` permission allowlist. [plan.md § Real-runtime E2E]
  Done when: `.claude/settings.json` contains these entries; runs of those commands do not prompt during agent execution.

- [ ] **T005** [P] Create [tsconfig.json](../../tsconfig.json) with `"strict": true`, `"target": "ES2023"`, `"module": "NodeNext"`, `"moduleResolution": "NodeNext"`, `"resolveJsonModule": true`, `"esModuleInterop": true`, `"forceConsistentCasingInFileNames": true`, `"noUncheckedIndexedAccess": true`, `"noImplicitOverride": true`, `"jsx": "react-jsx"`, `"jsxImportSource": "preact"`. Include `src/**/*.ts(x)` and `tests/**/*.ts(x)`. [FR-071, research.md D-001]
  Done when: `nix develop --command tsc --noEmit` exits 0 on an empty `src/index.ts`.

- [ ] **T006** [P] Create [eslint.config.js](../../eslint.config.js) (flat config). Rules: `@typescript-eslint/no-explicit-any: error`, `@typescript-eslint/no-unused-vars: error`, `no-console: ["error", { allow: ["warn","error"] }]` (lint must catch stray `console.log`), `@typescript-eslint/no-floating-promises: error`. Add `npm run lint` and `lint:fix` scripts. [W-DEV-5]
  Done when: `npm run lint` exits 0 on empty source; introducing `const x: any` triggers an error with line number.

- [ ] **T007** [P] Create [.prettierrc.json](../../.prettierrc.json) with `{ "semi": true, "singleQuote": false, "trailingComma": "all", "printWidth": 100 }`. Add pre-commit hook via `husky` (or equivalent) that runs `prettier --check` and `eslint` on staged files.
  Done when: pre-commit hook fails on un-formatted file; passes on formatted file.

- [ ] **T008** [P] Pre-commit secret guard: hook MUST reject any committed file matching `*.pem` or `*.key` outside `*.example`. Use `lint-staged` + a shell guard, or `gitleaks` configured against this pattern. [FR-090]
  Done when: committing `data/ca-key.pem` is rejected by the hook with a clear message; committing `.env.example` is allowed.

- [ ] **T009** Create the **structured test reporter** at [tests/helpers/test-reporter.ts](../../tests/helpers/test-reporter.ts). Implements `node:test`'s reporter protocol; writes one JSONL row per test result to `test-logs/<phase>-<run>.jsonl` with fields `{name, file, status, duration_ms, error?: {message, stack}}`. Also emits a per-run `test-logs/<phase>-<run>.summary.json` with totals. [FR-T3]
  Done when: a sample failing test produces a JSONL row with `status: "fail"` and the error stack; `test-logs/` is gitignored.

- [ ] **T010** [P] Create [tests/helpers/test-ca.ts](../../tests/helpers/test-ca.ts) — test CA + client/server cert factory using Node's crypto API. Exports `createTestCa()`, `signServerCert(ca, sanIp)`, `signClientCert(ca, cn, opts: { expiresInDays, revoked? })`. Generates ECDSA P-256 keys throughout. [FR-003, FR-013, IC-002, IC-004]
  Done when: unit test `tests/unit/test-ca.test.ts` verifies (a) CA can sign a client cert, (b) the client cert verifies against the CA, (c) `verifyChain` rejects an unrelated CA, (d) signing with `revoked: true` does not produce a different cert (revocation is per-server state, not embedded).

- [ ] **T011** [P] Create [tests/helpers/test-db.ts](../../tests/helpers/test-db.ts) — per-test SQLite file factory under `test-logs/db/<run-id>-<test-name>.db`, returns a `Database` instance with migrations applied. Cleanup in `afterEach`. [FR-036, FR-037]
  Done when: integration test using `getTestDb()` opens a fresh DB, runs migrations, and the file is deleted after the test completes.

- [ ] **T012** [P] Create [tests/helpers/fake-claude.ts](../../tests/helpers/fake-claude.ts) and a build script [scripts/gen-fake-claude.sh](../../scripts/gen-fake-claude.sh) that compiles a small Node binary (or shell script wrapped in a node-pty-compatible PTY-friendly bash) named `fake-claude`. Contract: accepts `--session-id <uuid>` and `--resume <uuid>`; reads stdin line-by-line; for each line, writes a corresponding JSONL row to `~/.claude/projects/<encoded-cwd>/<uuid>.jsonl` (matching claude's format per IC-008), then writes a fixture assistant response to both stdout and JSONL. Test-only env var `FAKE_CLAUDE_BEHAVIOR=crash|stall|echo` switches modes for edge tests. Print `claude 1.0.0` for `--version`. [FR-T4, IC-008, IC-012]
  Done when: `fake-claude --version` prints `claude 1.0.0`; a smoke test runs `echo hi | fake-claude --session-id <uuid>`, observes a new `~/.claude/projects/<cwd>/<uuid>.jsonl` with at least one row containing `role: "assistant"`; `FAKE_CLAUDE_BEHAVIOR=crash` causes exit code 137 mid-input.

- [ ] **T013** [P] Create [tests/helpers/ws-test-client.ts](../../tests/helpers/ws-test-client.ts) — WS test client that performs mTLS handshake using a fixture client cert (from T010), connects with subprotocol `tabrunner-v1`, and exposes `await client.next("session.message")` and `client.send({type:"client.input",...})` helpers. [FR-T6, IC-007]
  Done when: unit test connects to a tiny in-process WS echo server and round-trips a typed envelope; rejects connection without a client cert.

- [ ] **T014** Update [.gitignore](../../.gitignore) to include `test-logs/security/`. [reference/security.md]
  Done when: `test-logs/security/` is ignored alongside `test-logs/`.

- [ ] **T015** [P] Create [scripts/security-scan.sh](../../scripts/security-scan.sh) that runs `trivy fs . --format json --output test-logs/security/trivy.json`, `semgrep --config auto src/ --json --output test-logs/security/semgrep.json`, `gitleaks detect --report-format json --report-path test-logs/security/gitleaks.json --no-banner`, and `npm audit --audit-level=high --json > test-logs/security/npm-audit.json`. Produces `test-logs/security/summary.json` with per-scanner pass/fail and aggregate critical-count. Add `trivy`, `semgrep`, `gitleaks` to [flake.nix](../../flake.nix). [FR-T1, SC-008, reference/security.md]
  Done when: `bash scripts/security-scan.sh` exits 0 on a clean checkout; `summary.json` shows zero critical findings; introducing `const apiKey = "AKIA..."` causes Gitleaks to flag it and `summary.json` to report a critical finding.

- [ ] **T016** **Phase 1 validation**: confirm structure. Run `nix develop --command bash -c 'node --version && tsc --version && claude --version && code-review-graph --version && bwrap --version && tailscale ip -4'`. All MUST succeed. [Critical Path, plan.md]
  Done when: every tool prints a version line; `nix develop --command bash -c 'npm run lint && npm run typecheck'` exits 0.

---

## Phase 2: Foundational Infrastructure

**Purpose**: shared libraries every later phase depends on. No feature code, no UI.

- [ ] **T020** Implement [src/lib/logger.ts](../../src/lib/logger.ts) pino factory with correlation-ID helpers. Default level `info`; `TABRUNNER_LOG_LEVEL` env override (`trace|debug|info|warn|error`); `TABRUNNER_LOG_DEV=1` pipes through pino-pretty. Provides `createLogger(name)`, `withCorrelation(logger, { connection_id?, session_id?, audit_id? })`. Audit channel: `logger.child({ channel: "audit" })`. [FR-083, FR-084, FR-085, IC-011, research.md D-024]
  Done when: unit test asserts JSON output to stderr with `{level, time, name, msg}`; correlation IDs round-trip; `TABRUNNER_LOG_DEV=1` produces non-JSON pretty output; `child({channel:"audit"})` logs include `channel:"audit"` field.

- [ ] **T021** [P] Implement [src/lib/errors.ts](../../src/lib/errors.ts) — `AppError` base + subclasses `ValidationError`, `AuthError`, `NotFoundError`, `ConflictError`, `BackpressureError`, `InternalError`, `ConfigError`. Each has `code: string`, `httpStatus: number`, `cliExitCode: number`, `userMessage: string`, plus an optional `details?: object`. ConfigError defaults to cliExitCode 78. [FR-T, research.md D-025]
  Done when: unit tests assert each subclass's properties and that `instanceof AppError` is true for all of them; `JSON.stringify(new ValidationError({field:"x"}))` produces `{name, code, message, httpStatus, details}` (no stack in JSON).

- [ ] **T022** [P] Implement [src/lib/time.ts](../../src/lib/time.ts) with `nowIso(): string` (ISO-8601 UTC millisecond precision), `parseIso(s)`, `withinDays(d, n)`. No clock skew handling — host time is trusted. [data-model.md § Timestamps]
  Done when: unit tests assert `nowIso()` returns a string matching `/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/`.

- [ ] **T023** Implement [src/config/load.ts](../../src/config/load.ts) — TOML loader using `@iarna/toml` (or `smol-toml`); zod schema for the config shape per [contracts/interface.md](./contracts/interface.md) IC-001. Resolves `~/.config/tabrunner/config.toml` by default; `TABRUNNER_CONFIG` env overrides path. Performs tilde expansion. Validates `project` exists and is a directory. On any error, throws `ConfigError` (exit 78). [FR-082, FR-095, IC-001]
  Done when: unit test loads a valid config and returns the parsed object; loads a missing config and throws `ConfigError`; loads a config with `project = "/nonexistent"` and throws `ConfigError` with message mentioning the path; loads a config with extra unknown keys and either warns or fails per schema choice (zod `.strict()` for `.passthrough()` — pick `.strict()`).

- [ ] **T024** [P] Implement [src/config/claude-version.ts](../../src/config/claude-version.ts) exporting `export const EXPECTED_CLAUDE_MAJOR_MINOR = "1.0"` and `verifyClaudeVersion(): Promise<void>` that shells out to `claude --version`, parses `/^(?:claude\s+)?(\d+)\.(\d+)/`, and throws `ConfigError` if the major.minor doesn't match. [FR-091, IC-012, SC-013]
  Done when: integration test temporarily places a stub `claude` printing `claude 2.0.0` on PATH; `verifyClaudeVersion()` rejects with `ConfigError`; stub printing `claude 1.0.5` resolves; the function completes in <1s in both cases.

- [ ] **T025** Implement [src/db/index.ts](../../src/db/index.ts) — `getDb(dbPath): Database` opens `better-sqlite3` in WAL mode, applies `PRAGMA journal_mode=WAL; foreign_keys=ON; busy_timeout=5000;`, and returns the connection. Wraps writes in a mutex (single async-mutex serializing all writes to one connection). [FR-036, FR-043]
  Done when: unit test opens a DB, runs a write, opens a parallel reader, observes the read works concurrently; integration test runs 100 parallel writes through the mutex with no `SQLITE_BUSY` errors.

- [ ] **T026** Implement [src/db/migrate.ts](../../src/db/migrate.ts) — migration runner that reads `migrations/*.sql` in lex order, applies missing migrations transactionally, updates `_meta.schema_version`. Refuses to start if `schema_version` > newest local migration (downgrade guard). [FR-037, data-model.md § Migrations]
  Done when: integration test applies migrations to a fresh DB, observes `_meta.schema_version = 1`; second run is a no-op; corrupting the SQL file mid-run produces a failed transaction (no partial schema); manually setting `schema_version=99` causes `migrate()` to throw with a clear downgrade message.

- [ ] **T027** Create [migrations/001_init.sql](../../migrations/001_init.sql) with all tables, indexes, and FTS5 virtual table per [data-model.md](./data-model.md). Includes initial `_meta` rows: `schema_version=1`, `ca_next_serial=1`, `installed_at=<placeholder>` (populated by init code). [data-model.md]
  Done when: applying this migration on a fresh DB and querying `SELECT name FROM sqlite_master WHERE type='table'` returns the expected 6 names: `sessions`, `messages_fts` (+ FTS shadow tables), `clients`, `pairing_tokens`, `_meta`.

- [ ] **T028** [P] Implement [src/db/repo/sessions.ts](../../src/db/repo/sessions.ts) — typed CRUD for the `sessions` table per IC-005. Methods: `create(row)`, `get(id)`, `list(filter)`, `update(id, patch)`, `markRunning(id, pid)`, `markExited(id, code, signal)`, `markCrashed(id, code, signal)`, `markTerminated(id, signal)`. All terminal transitions MUST clear `pid` and set `exited_at`. [IC-005, FR-027, data-model.md § Session state]
  Done when: unit tests assert each transition writes the expected row state; attempting to set a non-enum `status` value throws (CHECK constraint); after `markExited`, `pid IS NULL`.

- [ ] **T029** [P] Implement [src/db/repo/messages-fts.ts](../../src/db/repo/messages-fts.ts) — FTS5 query builder + upsert helper. `upsert({session_id, message_id, role, content, timestamp})`, `search({query, scope, limit})` returning matches with `bm25()` rank + `snippet()`. `searchSessions(query, limit)` does FTS over a derived session-summary view. [FR-039, FR-057, IC-006]
  Done when: integration test indexes 100 messages, searches for a unique token, gets back the right row with `rank` and `snippet` populated.

- [ ] **T030** [P] Implement [src/db/repo/clients.ts](../../src/db/repo/clients.ts) — CRUD for clients per IC-004. Methods: `create({fingerprint, common_name, issued_at, expires_at})`, `list({includeRevoked?})`, `get(fp)`, `revoke(fp)`, `updateLastSeen(fp)`. [FR-040, IC-004]
  Done when: unit tests assert `revoke(fp)` sets `revoked_at` to now-ish; calling `revoke(fp)` twice is idempotent; `revoke("unknown")` returns a sentinel result (no exception) but logs at warn level.

- [ ] **T031** [P] Implement [src/db/repo/pairing-tokens.ts](../../src/db/repo/pairing-tokens.ts) — CRUD for pairing tokens per IC-003. `issue()` generates a 32-byte base64url token, sets TTL 5 min from now, inserts row. `verify(token)` returns `{state: "issued"|"used"|"expired", row?}`. `markUsed(token, client_fingerprint)` is single-shot (returns false if already used). `gc()` deletes rows where `expires_at < now - 1 day`. [FR-041, IC-003, FR-008]
  Done when: integration test issues a token, verifies it returns `issued`, calls `markUsed` once (true), calls again (false), advances clock past TTL, verifies returns `expired`.

- [ ] **T032** [P] Implement [src/db/repo/audit.ts](../../src/db/repo/audit.ts) — minimal write-through wrapper around the audit logger (pino). Records `recordAuditEntry({audit_id, actor, tool?, args?, outcome, reason?})`; backed by pino's audit channel, NOT a DB table (audit lines are append-only to the journal). [IC-011, FR-085]
  Done when: calling `recordAuditEntry` emits a pino JSON line with `channel: "audit"` and the expected fields; integration test asserts the line via `process.stderr` mocked write capture.

- [ ] **T033** Implement [src/security/headers.ts](../../src/security/headers.ts) — Fastify plugin that adds the 5 mandatory security headers to every response per FR-097. Constant string for CSP. [FR-097, SC-017]
  Done when: contract test sets up a minimal Fastify instance with this plugin, requests any route, asserts response headers contain `Strict-Transport-Security: max-age=63072000`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and a `Content-Security-Policy` starting with `default-src 'self'`.

- [ ] **T034** Implement [src/security/audit-log.ts](../../src/security/audit-log.ts) — thin façade that wraps `db/repo/audit.ts` with helpers `auditAllow({actor, tool, args})`, `auditDeny({actor, tool, args, reason})`, `auditError({actor, tool, args, reason})`. Used by API routes and MCP server. [IC-011]
  Done when: unit tests assert each helper produces an audit-channel pino line with `outcome` set correctly.

- [ ] **T035** Implement [src/tailscale/discover.ts](../../src/tailscale/discover.ts) — shells out to `tailscale ip -4`, parses the first non-empty line, returns the IPv4 string. Throws `ConfigError` (exit 78) on non-zero exit or no IP. [FR-001, IC-009, research.md D-008]
  Done when: integration test (with tailscale present) returns a valid IPv4; integration test that prepends a stub `tailscale` returning empty stdout throws `ConfigError`; integration that returns exit code 1 throws `ConfigError`.

- [ ] **T036** Create [src/lib/index.ts](../../src/lib/index.ts) and [src/types/shared.ts](../../src/types/shared.ts). Re-export from `errors.ts`, `logger.ts`, `time.ts`. `shared.ts` defines the WS envelope discriminated-union zod schema per [contracts/ws.md](./contracts/ws.md). [IC-007]
  Done when: `tests/contract/ws-envelope.test.ts` (created in later task) imports the schemas and round-trips every envelope variant.

- [ ] **T037** **Phase 2 user-flow integration test**: bootstrap a DB, write a session row, search FTS, retrieve it back. [Critical Path]
  Done when: `tests/integration/foundational-roundtrip.test.ts` creates a test DB, inserts a session, inserts 3 FTS messages, queries `search_messages("unique token")`, asserts the right session_id + snippet; runs in <3s.

- [ ] **T038** **Phase 2 security scan**: run `bash scripts/security-scan.sh`. [SC-008]
  Done when: `test-logs/security/summary.json` shows 0 critical, 0 high findings on this phase's code; the script exits 0.

- [ ] **T039** **Phase 2 validation**: `npm run typecheck && npm run lint && npm run test:unit && npm run test:contract && npm run test:integration -- tests/integration/foundational-*` all exit 0; structured reporter writes JSONL files. [Critical Path]
  Done when: phase reporter shows 0 failures across all four commands.

---

## Phase 3: TLS, CA, mTLS, Pairing

**Purpose**: implement Constitution II from the bottom up. After this phase, `curl --cert` works against `/api/v1/health`.

- [ ] **T040** Implement [src/tls/ca.ts](../../src/tls/ca.ts) — `generateCa(): { certPem, keyPem }` creates an ECDSA P-256 root CA with 10-year validity and subject `CN=tabrunner-ca`. Writes `<data_dir>/ca.pem` (0644) and `<data_dir>/ca-key.pem` (0600). Reuses if both files exist. [FR-003, FR-094, IC-002]
  Done when: integration test calls `generateCa()` twice; second call reads existing files and returns identical content; `stat -c %a <data_dir>/ca-key.pem` returns `600`.

- [ ] **T041** Implement [src/tls/server-cert.ts](../../src/tls/server-cert.ts) — `ensureServerCert(ca, sanIp)`: generates an ECDSA P-256 server cert signed by `ca`, SAN includes the Tailscale IP, 90-day validity. Auto-rotates if the existing cert expires within 30 days. Writes `<data_dir>/server-cert.pem` (0644) and `<data_dir>/server-key.pem` (0600). [FR-004, IC-002]
  Done when: integration test generates cert; second call returns existing cert; calling with a cert artificially aged to "30 days before expiry" rotates and produces a new serial; key file mode is 0600.

- [ ] **T042** Implement [src/tls/pairing.ts](../../src/tls/pairing.ts) — `issueToken(): { url, qr }` creates a row in `pairing_tokens` (via T031), returns the full URL and the QR code (via `qrcode` lib's text rendering for terminals; also returns a data URL for the pairing page). `signCsr(token, csrPem): { clientCertPem, caCertPem, fingerprint, expiresAt }` verifies token state, parses CSR, validates it's ECDSA P-256, signs producing a 365-day cert with subject CN `tabrunner-client-<short-fp>`. [FR-007..011, FR-013, IC-003, IC-004]
  Done when: integration test issues a token, verifies it exists; signs a fixture CSR; verifies the resulting cert chains to the CA and is in `clients` table; expired token returns error; reused token returns error.

- [ ] **T043** Implement [src/tls/revocation.ts](../../src/tls/revocation.ts) — `RevocationSet` class holding an in-memory `Set<fingerprint>` plus DB sync. `load()` reads `clients` rows where `revoked_at IS NOT NULL` into the set. `revoke(fp)` writes DB + adds to set. `isRevoked(fp)` returns bool. Used by the Fastify TLS hook to reject revoked client certs at handshake. [FR-006, FR-015, SC-012]
  Done when: integration test loads a revoked client, asserts `isRevoked(fp) === true`; revoking a new fp updates both DB and in-memory state synchronously.

- [ ] **T044** Implement [src/tailscale/discover.ts]() already in T035; now wire it into [src/app.ts](../../src/app.ts) — the Fastify app factory. `createApp({ db, logger, config, ca, revocation })` returns a configured Fastify instance bound to the resolved Tailscale IPv4 with HTTPS using server cert from T041 and `requestCert: true, rejectUnauthorized: true, ca: <our-ca>` so client certs are required. [FR-002, FR-005]
  Done when: integration test starts the app with a test CA + test client cert; `curl --cert client.pem --key client.key --cacert ca.pem https://<bind>:<port>/api/v1/health` returns 200; the same curl without `--cert` fails at TLS handshake.

- [ ] **T045** [P] Implement [src/api/health.ts](../../src/api/health.ts) — registers `GET /api/v1/health`, `GET /api/v1/ready`, `GET /api/v1/sw-version` per [contracts/http.md](./contracts/http.md). Returns the documented JSON shapes. `/ready` returns 503 until `app.state.ftsInitialScanComplete === true` AND `app.state.migrationsApplied === true`. `/sw-version` returns the build-time version env (`BUILD_VERSION`). [FR-098, FR-099, SC-018]
  Done when: contract test asserts each endpoint's response shape and status code; `/ready` flips from 503 to 200 once both state flags are set.

- [ ] **T046** [P] Implement [src/api/pair.ts](../../src/api/pair.ts) — `GET /pair/:token` returns the pairing HTML page (read from `public/pair.html`, dynamic-replaced with the token + server cert fingerprint for in-page pinning), `POST /pair/:token/csr` calls `tls/pairing.ts:signCsr`, `GET /pair/:token/status` returns token state. These routes MUST be exempt from client-cert requirement (Fastify hook adjustment: allow `/pair/*` paths without client cert). [FR-005 exception, FR-007..011, IC-003]
  Done when: integration test POSTs a CSR with no client cert (mTLS exception confirmed); receives 200 with expected JSON; second POST with same token returns 410.

- [ ] **T047** Implement [src/cli/pair.ts](../../src/cli/pair.ts) — `tabrunner pair` subcommand. Calls `tls/pairing.ts:issueToken()`; prints the QR (via `qrcode-terminal` or `qrcode` ASCII renderer) plus the URL plus a `Token valid for 5 minutes or one use.` line. Exits 0. [FR-007, US-1, W-SYS-3]
  Done when: integration test runs `tabrunner pair`, captures stdout, asserts it contains a URL matching `https://\d+\.\d+\.\d+\.\d+:\d+/pair/[A-Za-z0-9_-]{40,}` and at least 10 lines of QR characters; DB has a fresh `pairing_tokens` row.

- [ ] **T048** Implement [src/cli/clients.ts](../../src/cli/clients.ts) — `tabrunner clients list` and `tabrunner clients revoke <fp>` subcommands. `list` prints a table with columns `FINGERPRINT  COMMON_NAME  ISSUED_AT  EXPIRES_AT  LAST_SEEN  REVOKED`; `--json` outputs JSON array. `revoke <fp>` calls `tls/revocation.ts:revoke(fp)`, exits 0 with `Revoked <fp> at <iso>` even if unknown (idempotent with warn line). [FR-014, FR-015, US-7, W-SYS-4]
  Done when: integration test pairs a fixture client; runs `tabrunner clients list --json`, asserts the fingerprint is present; runs `tabrunner clients revoke <fp>`; asserts subsequent TLS handshake from that client fails (SC-012); running `revoke` again is idempotent.

- [ ] **T049** **Phase 3 critical-path checkpoint**: full pair → connect flow. [Critical Path]
  Done when: `tests/integration/pair-and-connect.test.ts` (a) starts test server, (b) runs `tabrunner pair` programmatically, (c) generates an in-process WebCrypto-equivalent keypair via Node crypto + builds a CSR via `crypto.X509Certificate` flow, (d) POSTs CSR to `/pair/<token>/csr`, (e) parses the response, (f) reconnects with the new client cert, (g) hits `/api/v1/health`, asserts 200. End-to-end runs in <5s.

- [ ] **T050** **Phase 3 adversarial security tests** in [tests/integration/adversarial-tls.test.ts](../../tests/integration/adversarial-tls.test.ts) per plan.md § Adversarial security tests. Cases: no client cert; wrong-CA client cert; expired client cert; revoked client cert (within 5s of revoke command). [FR-005, FR-006, FR-015, SC-012]
  Done when: all four cases fail at TLS handshake (no application handler invoked, verified via no audit log entry); revoked case fails within 5s of revoke per SC-012; test runs in <10s total.

- [ ] **T051** **Phase 3 validation**: typecheck, lint, unit + contract + integration tests, security scan all green.
  Done when: same as T039 across the expanded test scope.

---

## Phase 4: Sessions — bwrap, PTY, JSONL parser, JSONL watcher, FTS

**Purpose**: spawn `claude` per session inside bwrap, attach PTY, parse JSONL, index FTS. After this phase, sessions can be created and their messages indexed.

- [ ] **T060** Implement [src/claude/encoded-path.ts](../../src/claude/encoded-path.ts) — converts `/home/max/git/foo` → `-home-max-git-foo` (replace `/` with `-`). Pure function. [IC-008]
  Done when: unit test asserts the conversion for paths with/without trailing slash, with multiple slashes, with hyphens (which are preserved as-is; the only transform is `/` → `-`).

- [ ] **T061** Implement [src/claude/spawn.ts](../../src/claude/spawn.ts) — `spawnClaudeSession({ sessionId, projectPath, scratchDir, resumeId? })` builds the bwrap argv per IC-009 and uses `node-pty` to spawn. Returns `{ pty, pid }`. The argv MUST include `--die-with-parent --unshare-pid --unshare-uts --unshare-ipc`, mounts per IC-009, env passthrough for `CLAUDE_CODE_OAUTH_TOKEN`, `--chdir <projectPath>`, then `-- claude --session-id <sessionId>` (or `--resume <resumeId>` when resuming). [FR-017, FR-018, IC-009, US-2, US-4]
  Done when: integration test uses `fake-claude` (T012) to spawn a session; PTY emits the expected greeting; writing `echo hi\n` to PTY stdin produces a JSONL row under `~/.claude/projects/<encoded>/<uuid>.jsonl`; killing the PTY's PID cleans up the bwrap child.

- [ ] **T062** [P] Implement [src/claude/jsonl-parser.ts](../../src/claude/jsonl-parser.ts) — parses one JSONL line into a typed `ClaudeJsonlRow` discriminated union per the claude-1.0 schema (FR-091). Skip + warn on malformed lines (set a `partialIndex: true` flag on the consumer side). Recognizes at least `{type:"queue-operation"}`, `{type:"user-message"}`, `{type:"assistant-message"}`, `{type:"tool-call"}`, `{type:"tool-result"}` (exact field shapes derived from inspecting real claude jsonl files; T002 confirms claude version). [IC-008, FR-044, FR-045]
  Done when: unit tests cover each row type; fixture jsonl file with 100 valid lines + 3 garbled lines parses 100 successfully; warn log emitted 3 times; `partialIndex` flag returned true.

- [ ] **T063** Implement [src/claude/jsonl-watcher.ts](../../src/claude/jsonl-watcher.ts) — chokidar-based watcher over `~/.claude/projects/<encoded-project>/`. Detects new files (newly-created session jsonl) and modifications. For each change, reads the tail (since last cursor), parses each row via T062, upserts into `messages_fts` (T029). Exposes `app.state.ftsInitialScanComplete: boolean` flag set after the first sweep finishes. [FR-044, FR-045, SC-006, IC-006]
  Done when: integration test starts the watcher pointed at a temp `~/.claude/projects/<encoded>/`, writes a 10-row JSONL file, observes `messages_fts` has 10 rows within 5s; introduces a malformed line and observes a warn log + `partial_index: true` on the session row.

- [ ] **T064** Implement [src/claude/session.ts](../../src/claude/session.ts) — per-session orchestrator. Holds `{ id, pid, pty, status, subscribers: Set<WsConn>, replayBuffer }`. Wires PTY stdout → both `session.stdout` events (raw bytes base64) and per-session `session.message` events derived from jsonl-watcher upserts that match this session_id. Handles SIGTERM (10s grace, SIGKILL). On exit, calls `sessions repo.markExited|markCrashed|markTerminated`. On every PTY write OR every 5s of activity, performs an `fs.access(watchedProjectDir, R_OK)` probe; if it fails, transitions the session to `crashed` with `exit_signal: "EPROJDIR"` and broadcasts `session.exit` so the operator sees the failure. Termination paths MUST NOT delete the `sessions` row, the claude jsonl file, or the per-session scratch directory `<data_dir>/sessions/<uuid>/`. [FR-018, FR-020, FR-021, FR-022, FR-027, FR-031, FR-035, IC-005]
  Done when: integration test spawns a fake-claude session, observes `session.stdout` event with base64-encoded bytes; spawns one with `FAKE_CLAUDE_BEHAVIOR=crash`, observes `session.exit{status:"crashed",exit_code:137}`; calls `session.close()`, observes SIGTERM, then process exits within 10s and DB row shows `status:"terminated"`. Additional assertions (FR-022): after a `terminated`/`exited`/`crashed` transition, `SELECT 1 FROM sessions WHERE id=?` still returns the row, `~/.claude/projects/<encoded>/<uuid>.jsonl` still exists, and `<data_dir>/sessions/<uuid>/` still exists. Additional assertion (FR-035): renaming the watched project dir mid-session causes the session to transition to `crashed` with `exit_signal: "EPROJDIR"` within 10s and a `session.exit` event is broadcast.

- [ ] **T065** **Phase 4 critical-path checkpoint**: spawn → message → FTS round-trip. [Critical Path]
  Done when: `tests/integration/session-lifecycle.test.ts` (a) spawns a fake-claude session via T064, (b) writes "hello" to PTY stdin, (c) waits for jsonl-watcher upsert, (d) calls `messages-fts.search("hello")`, (e) gets back the matching row with session_id; test runs in <5s.

- [ ] **T066** **Phase 4 validation**: typecheck + lint + unit + contract + integration tests + security scan all green.

---

## Phase 5: WebSocket multiplexer + replay buffer

**Purpose**: PWA can connect via `@fastify/websocket`, subscribe to sessions, receive multiplexed events, resume after disconnect.

- [ ] **T070** Implement [src/ws/envelope.ts](../../src/ws/envelope.ts) — zod schemas for every WS event type per [contracts/ws.md](./contracts/ws.md). One discriminated union for server→client, another for client→server. Exports type-safe `encode(envelope): string` and `decode(json): Envelope` helpers. [IC-007]
  Done when: contract test in `tests/contract/ws-envelope.test.ts` round-trips every event type; introduces a malformed envelope and asserts `decode` throws a `ValidationError`.

- [ ] **T071** Implement [src/ws/buffer.ts](../../src/ws/buffer.ts) — per-session replay buffer keyed by `session_id`, retains last 60s of events indexed by `seq`. `push(session_id, envelope)` adds; `since(session_id, seq)` returns all envelopes with `seq > seq`. Bounded — drops the oldest event when total queued > 10K per session. [FR-032]
  Done when: unit test pushes 100 events, calls `since(sid, 50)`, gets back events 51-100; advances time +61s, calls `since(sid, 0)`, gets back only events from the last 60s; pushes 10001 events, asserts the buffer dropped the oldest.

- [ ] **T072** Implement [src/ws/multiplexer.ts](../../src/ws/multiplexer.ts) — maps `session_id` → `Set<WsConn>` subscribers and monotonic `seq` counter per session. `subscribe(conn, session_id, since?)` replays from buffer then adds to set. `unsubscribe(conn, session_id)` removes. `broadcast(session_id, envelope)` increments seq, pushes to buffer, sends to all subscribers. Also broadcasts `connection.*` and global events to a per-connection unicast channel. [IC-007, FR-032, FR-033]
  Done when: integration test connects 2 WS clients, subscribes both to the same session, broadcasts 3 events, asserts both clients receive them in order with monotonic seq; disconnects one, reconnects with `since:<last_seq>`, observes replay then live events.

- [ ] **T073** Implement [src/ws/server.ts](../../src/ws/server.ts) — Fastify plugin that registers `@fastify/websocket` on `/api/v1/ws`, validates subprotocol `tabrunner-v1`, sets up per-connection state (connection_id, correlation logger, multiplexer subscriptions), handles `client.hello` (replay per `resume` map), `client.spawn`, `client.input` (writes to claude PTY stdin via T064), `client.interrupt` (writes Ctrl-C), `client.close_tab`, `client.subscribe`, `client.unsubscribe`. Send `connection.hello` immediately after upgrade. [FR-019, IC-007, US-2, US-3, US-7, W-OP-2, W-OP-7]
  Done when: integration test connects via T013, receives `connection.hello`, sends `client.hello{resume:{}}`, then `client.spawn`, observes the full `session.created` → `session.status` → `session.stdout` → `session.message` sequence; sends `client.input{text:"hi",append_newline:true}`, observes the assistant response stream back.

- [ ] **T074** Implement backpressure in [src/ws/server.ts]() — if per-session queue for any subscriber exceeds 10K events, send `connection.error{code:"client_too_slow"}` and close the WS with code 1011. [contracts/ws.md § Backpressure]
  Done when: integration test artificially pauses a WS client's onMessage handler while emitting >10K events; asserts the server closes the connection within 1s of crossing the threshold.

- [ ] **T075** **Phase 5 user-flow integration test** end-to-end: REST + WS together. `tests/integration/ws-replay.test.ts` connects, spawns a session, disconnects mid-stream, reconnects with `resume`, observes replay then continues. [SC-005, W-OP-14]
  Done when: full disconnect → reconnect → first replayed event takes < 1s (SC-005); no duplicate messages.

- [ ] **T076** **Phase 5 validation**: full test suite + security scan green.

---

## Phase 6: REST API + history + search

**Purpose**: REST routes for `/api/v1/sessions/*` per [contracts/http.md](./contracts/http.md). PWA history view can query.

- [ ] **T080** [P] Implement [src/api/sessions.ts](../../src/api/sessions.ts): `GET /api/v1/sessions` (paginated list with optional `project`, `status`, `pinned`, `search`, `since`, `limit` per FR-046), `GET /api/v1/sessions/:id`, `POST /api/v1/sessions` (creates a session row via T064 spawn), `POST /api/v1/sessions/:id/reopen` (per FR-023), `DELETE /api/v1/sessions/:id` (SIGTERM via T064), `GET /api/v1/sessions/:id/messages` (paginated messages via T029). All endpoints require client cert (FR-005). [FR-046, FR-023, FR-029, IC-005, IC-006, US-4, US-6, W-OP-4, W-OP-6]
  Done when: contract test in `tests/contract/http-shapes.test.ts` asserts every endpoint matches the schemas in `contracts/http.md`; integration test creates 5 sessions, lists them with `limit=2`, asserts pagination cursor works; `?search=` returns FTS5 hits with snippets; `limit=500` is clamped to 200.

- [ ] **T081** [P] Implement [src/api/admin.ts](../../src/api/admin.ts): `GET /api/v1/admin/clients`, `POST /api/v1/admin/clients/:fingerprint/revoke`. Backs the CLI subcommands. [FR-014, FR-015, contracts/http.md § Admin]
  Done when: contract test asserts each endpoint shape; revoke endpoint flips `clients.revoked_at` and updates the in-memory revocation set.

- [ ] **T082** [P] Implement [src/api/errors.ts](../../src/api/errors.ts) — Fastify error handler maps `AppError` → JSON `{error, message, details?}` with the correct HTTP status; unknown errors → 500 + log full stack with correlation ID. [research.md D-025]
  Done when: contract test fires a route that throws `ValidationError`, observes 400 + JSON with `error:"validation_error"`; throws `Error("oops")`, observes 500 + log line with the stack.

- [ ] **T083** [P] Implement [src/api/routes.ts](../../src/api/routes.ts) — registers all route plugins (`health`, `pair`, `sessions`, `admin`) plus the security headers plugin from T033 and the error handler from T082.
  Done when: integration test boots `app.ts` end-to-end and `curl`s each registered route, asserts none returns 404 (with appropriate other status codes per their semantics).

- [ ] **T084** [P] Implement [src/cli/sessions.ts](../../src/cli/sessions.ts) — `tabrunner sessions list` and `tabrunner sessions kill <id>` subcommands. Hits the admin API over loopback with a built-in admin cert (generated by `tabrunner init` and stored at `<data_dir>/admin-cert.pem` + `<data_dir>/admin-key.pem`, both 0600). `list` prints a table; `--json` outputs JSON. `kill` returns idempotently. [FR-028, FR-029, US-7, W-SYS-9]
  Done when: integration test starts the server, runs `tabrunner sessions list --json`, asserts the JSON shape; runs `tabrunner sessions kill <known-id>`, asserts SIGTERM emitted and session row updated.

- [ ] **T085** **Phase 6 user-flow integration test**: search across sessions. `tests/integration/history-search.test.ts` creates 3 sessions with distinct content, waits for FTS indexing, queries `GET /api/v1/sessions?search=<unique>`, asserts the right session returns with snippet. [W-OP-6, SC-006]
  Done when: FTS lag ≤5s; query returns correct match.

- [ ] **T086** **Phase 6 validation**: full test suite + security scan green.

---

## Phase 7: Meta agent MCP server

**Purpose**: tabrunner MCP server with 9 read-only tools exposed to the meta agent's claude session.

- [ ] **T090** Implement [src/meta-agent/path-guard.ts](../../src/meta-agent/path-guard.ts) — `safeResolve(projectRoot, requestedPath): string` resolves the real path (following symlinks via `fs.realpath`), checks it's inside `projectRoot`, returns the resolved absolute path. Throws `AuthError({code:"path_outside_project"})` otherwise. [FR-059, SC-011]
  Done when: unit tests cover relative paths, absolute paths inside the root, absolute outside, `../../etc/passwd`, and a symlink inside pointing outside; all malicious cases throw with the documented error code.

- [ ] **T091** Implement [src/meta-agent/tools.ts](../../src/meta-agent/tools.ts) — 9 tool implementations per [contracts/mcp.md](./contracts/mcp.md):
  - `query_sessions`, `read_session` (via sessions + FTS repos)
  - `tail_live` (reads from per-session ring buffer maintained by `claude/session.ts`)
  - `list_running` (query sessions with `status='running'`)
  - `search_messages`, `search_sessions` (FTS)
  - `read_project_file`, `list_project_files` (uses T090)
  - `get_session_summary` (60s cache)

  Every tool call writes an audit log entry via T034. [FR-051..065, FR-062, FR-063, IC-010]
  Done when: contract test in `tests/contract/mcp-tools.test.ts` invokes each tool with a fixture DB + session ring buffer, asserts the response matches the zod schema in `contracts/mcp.md`; `read_project_file("../../etc/passwd")` returns 403 with an audit-deny log entry (SC-011); `tail_live` p95 ≤ 200ms on a 10K-line buffer (SC-010).

- [ ] **T092** Implement [src/meta-agent/mcp-server.ts](../../src/meta-agent/mcp-server.ts) — stdio MCP server using `@modelcontextprotocol/sdk`. Registers exactly the 9 tools from T091. NO write/spawn/kill/exec/shell tools — enforced by a startup assertion + a contract test. [IC-010, FR-062]
  Done when: contract test launches the MCP server as a child process, sends `list_tools` JSON-RPC, asserts exactly 9 tools returned and none of them have names matching `/(spawn|kill|write_file|exec|shell|update|delete|revoke|create)/i`.

- [ ] **T093** Wire the meta session in [src/server.ts](../../src/server.ts) — at startup, if no `sessions` row with `pinned=1` exists, create one with a fresh UUID, title `"Meta"`. Generate `<data_dir>/meta.mcp.json` referencing the MCP server binary (built from T092). Spawn the meta session at boot through T064 with `--mcp-config <data_dir>/meta.mcp.json`. [FR-051, FR-052, FR-065, US-5]
  Done when: integration test boots the server cold, observes the meta session row exists with `pinned=1`; the corresponding claude PID is alive; killing the meta PID and restarting the server respawns it via `--resume`.

- [ ] **T094** **Phase 7 user-flow integration test**: meta query end-to-end. `tests/integration/meta-tools.test.ts` populates the DB with 3 sessions in various states (1 running, 1 exited, 1 crashed), launches the MCP server, calls each of the 9 tools with realistic arguments, asserts the right results. [W-OP-5]
  Done when: every tool returns documented output; `tail_live` returns within 200ms p95 over 100 trials (SC-010); `search_messages` returns hits ordered by FTS5 rank.

- [ ] **T095** **Phase 7 validation**: full test suite + security scan green.

---

## Phase 8: PWA — Preact app, pairing, tab bar, composer, history, meta tab

**Purpose**: end-to-end PWA frontend. After this phase, a paired device can use tabrunner from a browser.

- [ ] **T100** Create [src/pwa/index.html](../../src/pwa/index.html) — minimal shell that loads `/app.css` and `/app.js`, registers the service worker, includes the web manifest link. [FR-066]
  Done when: navigating to `/` in a paired browser returns this HTML; CSP allows `script-src 'self'` only (no inline scripts).

- [ ] **T101** [P] Create [public/manifest.webmanifest](../../public/manifest.webmanifest) — PWA manifest with name "tabrunner", icons (192px, 512px), `display: "standalone"`, `theme_color`, `background_color`. Create [public/icons/](../../public/icons/) with the two PNGs. [FR-068]
  Done when: in a Chromium-based browser, the install prompt is offered; `lighthouse --only-categories=pwa` reports a passing install category (or equivalent assertion).

- [ ] **T102** [P] Implement [src/pwa/sw.ts](../../src/pwa/sw.ts) — service worker. Embeds a build-time `BUILD_VERSION` constant. Caches HTML/JS/CSS/manifest/icons on `install`. On each page navigation, fetches `/api/v1/sw-version`; if newer, calls `skipWaiting()` and posts `update_available` via MessageChannel. NEVER caches `/api/v1/*` responses. [FR-066, FR-069, FR-099, SC-019, research.md D-021]
  Done when: integration-ish test (Playwright) registers the SW, bumps `BUILD_VERSION`, navigates, observes the `update_available` MessageChannel post; CC-3 satisfied (no errors).

- [ ] **T103** [P] Implement [src/pwa/state/signals.ts](../../src/pwa/state/signals.ts) — central signals: `tabs: Signal<Tab[]>`, `activeTabId: Signal<string|null>`, `runningCount: Signal<number>`, `connectionStatus: Signal<"connecting"|"syncing"|"connected"|"reconnecting">`, `paired: Signal<boolean>`. [FR-071, FR-078, research.md D-003]
  Done when: unit test asserts signal mutations trigger subscribers; multiple subscribers receive updates in order.

- [ ] **T104** Implement [src/pwa/state/ws-client.ts](../../src/pwa/state/ws-client.ts) — WS client wrapping `WebSocket` API; sends `client.hello{resume:{...}}` with last-seen `seq` per session_id (from a persisted Map in memory; not localStorage). Reconnect with exponential backoff (1s, 2s, 4s, 8s, capped 30s). On `connection.error{code:"client_too_slow"}`, drop in-memory state and refetch via REST. [FR-032, FR-078, IC-007]
  Done when: Playwright integration test connects, drops the socket, reconnects within ~1s, asserts `client.hello.resume` is sent with the correct sequence numbers per session; SC-005 satisfied.

- [ ] **T105** Implement [src/pwa/pairing/webcrypto.ts](../../src/pwa/pairing/webcrypto.ts) — generates ECDSA P-256 keypair via `crypto.subtle.generateKey`, builds a CSR using a small ASN.1 helper (or `pkijs` if added as a dep). Submits to `/pair/<token>/csr`. On success, attempts cert install via the browser's client-cert API (browser-specific; iOS Safari prompts to install via Settings; desktop Chrome may need the user to manually accept the prompt). [FR-009, FR-011, W-OP-1]
  Done when: Playwright test runs the pairing flow in a fresh browser context, ends with a valid client cert available for subsequent requests; verified via `await context.cookies()` or `context.clientCertificates()` (Playwright >=1.39).

- [ ] **T106** [P] Implement [src/pwa/ui/PairingPage.tsx](../../src/pwa/ui/PairingPage.tsx) — pairing UI per W-OP-1. ARIA: `role="heading" name="Pair this device"`, `role="status"` text transitions `Generating keypair…` → `Awaiting server signature…` → `Pairing complete!`. Shows a `Retry` button on network blip. [W-OP-1]
  Done when: Playwright test snapshots the DOM at each state transition.

- [ ] **T107** Implement [src/pwa/ui/App.tsx](../../src/pwa/ui/App.tsx) — top-level app. If `paired === false` (detected by absence of usable client cert, signaled by a hard TLS failure on the initial `fetch('/api/v1/health')` probe), render `<UnpairedPage />` showing exactly the copy `Device not paired. Please run \`tabrunner pair\` and scan the QR code on this device.` as a `role="alert"` with `aria-live="assertive"`. Otherwise render `<Header />` + `<TabBar />` + `<TabBody />` + `<Footer />` showing Tailscale IP/port (FR-080). Shows "reconnecting" banner when `connectionStatus !== "connected"`. [FR-067, FR-078, FR-079, FR-080, W-OP-7]
  Done when: Playwright test boots a paired browser, observes the full UI scaffold rendered with the running-count badge and pinned Meta tab. Additional assertion (FR-079): Playwright test in an UNPAIRED browser context navigates to `/`, asserts a visible element with `role="alert"` whose `textContent.trim()` exactly equals `Device not paired. Please run \`tabrunner pair\` and scan the QR code on this device.` (verbatim including backticks).

- [ ] **T108** [P] Implement [src/pwa/ui/TabBar.tsx](../../src/pwa/ui/TabBar.tsx) and [src/pwa/ui/Tab.tsx](../../src/pwa/ui/Tab.tsx) — tab bar collapses to a hamburger drawer at viewport <768px (FR-067). Pinned Meta tab is always first and visually distinguished (FR-064). Touch targets ≥44px. Close button on each tab prompts a confirmation dialog (FR-073). Running-count badge visible when N≥2 (FR-025, FR-077). [FR-064, FR-067, FR-073, FR-077, W-OP-9]
  Done when: Playwright test (mobile emulation) opens hamburger, sees tabs in drawer; clicking a tab closes the drawer and switches active; click X on a tab shows the "Close tab?" dialog.

- [ ] **T109** [P] Implement [src/pwa/ui/Composer.tsx](../../src/pwa/ui/Composer.tsx) — `role="textbox" name~="Message"` textarea + `role="button" name="Send"`. Key bindings per FR-092: Enter sends, Shift+Enter newline, Cmd/Ctrl+Enter sends. Disabled when session is in a terminal state (FR-073/W-OP-15). [FR-092, SC-016, W-OP-12, W-OP-15]
  Done when: Playwright test types into the composer, presses each key combo, asserts the right outcome (send vs newline); mobile-emulation test Cmd+Enter sends; SC-016 satisfied.

- [ ] **T110** [P] Implement [src/pwa/ui/Message.tsx](../../src/pwa/ui/Message.tsx) — chat-bubble renderer. Supports roles `user|assistant|tool_call|tool_result`. Tool calls render collapsed by default with summary `<tool>: <preview>`; click expands to show args + result. Results >50 lines truncate with "show full" affordance. Raw bytes toggle per tab (FR-072). [FR-093, FR-072, SC-015, W-OP-11, W-OP-13]
  Done when: Playwright test asserts tool-call summary is rendered as `role="button"` with the expected name; click expands within 100ms (SC-015); "show full" link appears for a 100-line tool result.

- [ ] **T111** [P] Implement [src/pwa/ui/HistoryView.tsx](../../src/pwa/ui/HistoryView.tsx) — `role="searchbox"` with debounce 300ms; results render rows with title/project/started_at/last_activity/status/message_count; clicking a row opens a new tab (calls `/api/v1/sessions/:id/reopen`). [FR-075, FR-076, W-OP-4, W-OP-6]
  Done when: Playwright test seeds 3 sessions, opens History, searches a unique phrase, asserts the right row appears with snippet; clicking it opens a new tab populated with the replayed messages.

- [ ] **T112** [P] Implement [src/pwa/ui/MetaTab.tsx](../../src/pwa/ui/MetaTab.tsx) — visually distinguished header banner `role="banner" name~="Meta agent (read-only)"`. Renders the meta session's messages using `<Message />`; shows `meta.tool_call`/`meta.tool_result` envelopes inline so the operator sees what the meta agent did. [FR-064, W-OP-5]
  Done when: Playwright test opens Meta tab, asks "list running sessions", observes tool-call summary + assistant message with the answer.

- [ ] **T113** Wire the PWA build in [package.json](../../package.json): `build:client` runs esbuild to bundle `src/pwa/ui/App.tsx` → `public/app.js`, plus a separate `src/pwa/sw.ts` → `public/sw.js`. CSS via `public/app.css` (hand-rolled). `build` runs `tsc` (server) plus `build:client`. `dev` runs `tsx watch src/server.ts` AND `esbuild --watch` concurrently (via `concurrently` or a small shell script). [FR-066, FR-071, FR-086]
  Done when: `npm run build` produces `dist/server.js`, `public/{index.html,app.js,sw.js,app.css,manifest.webmanifest,icons/*}`; gzipped `public/app.js + public/app.css` ≤ 100KB (SC-003) — enforced via `size-limit` check (T134).

- [ ] **T114** **Phase 8 critical-path checkpoint**: full operator day-1 flow end-to-end in a real browser. [Critical Path]
  Done when: Playwright test (`tests/e2e/day-one.test.ts`) pairs, opens a tab, types "hello", observes the assistant response, opens the Meta tab and asks "show running sessions", observes the tool call + answer; completes in <60s.

- [ ] **T115** **Phase 8 validation**: full test suite + size-limit check + security scan green.

---

## Phase 9: Admin CLI (init, finalize) + systemd unit

**Purpose**: complete the CLI surface and the install path.

- [ ] **T120** Implement [src/cli/init.ts](../../src/cli/init.ts) — interactive `tabrunner init`. Per FR-096: prompts for project absolute path (validates existence + is-dir); creates `~/.config/tabrunner/config.toml` (refuses to overwrite without `--force`); creates `<data_dir>/`; generates CA (T040) and server cert (T041); creates admin cert at `<data_dir>/admin-cert.pem` (for loopback CLI access); initializes SQLite + runs migrations (T026, T027); prints summary + "Now run: tabrunner serve". Idempotent for already-present artifacts. [FR-096, W-SYS-1, SC-014]
  Done when: integration test on a clean HOME runs `tabrunner init`, supplies the project path, completes in <10s (SC-014); re-running prints "current state: ..." and exits 0; with `--force` overwrites config.

- [ ] **T121** Implement [src/cli/serve.ts](../../src/cli/serve.ts) — the `tabrunner serve` orchestrator. Loads config (T023), verifies claude version (T024), runs migrations (T026), creates CA + server cert if missing (BUT does NOT auto-create config — that's `init`'s job per FR-095), starts the JSONL watcher (T063), spawns the meta session (T093), creates the Fastify app (T044), binds, listens. Registers SIGTERM/SIGINT shutdown handler that orchestrates the full 11-step graceful shutdown sequence. [FR-030, FR-095, IC-013, W-SYS-6]
  Done when: integration test starts serve cold (with init artifacts in place), observes listener within 2s (SC-007); sending SIGTERM gracefully terminates 3 active fake-claude sessions within 12s; DB rows show `status: "terminated"`; no orphan PIDs.

- [ ] **T122** Implement [src/server.ts](../../src/server.ts) — entry point. Subcommand dispatcher: `init|serve|pair|sessions|clients|--version|--help`. Default subcommand prints usage. Each subcommand imports its module from `src/cli/`. [FR-T]
  Done when: `tabrunner --help` lists all subcommands; `tabrunner --version` prints the package version; unknown subcommand exits 1 with usage.

- [ ] **T123** [P] Create [etc/systemd/tabrunner.service](../../etc/systemd/tabrunner.service) per IC-013. Sections: `[Unit] Description=tabrunner — Tailscale-bound PWA for parallel Claude Code sessions, After=tailscaled.service network-online.target`, `[Service] Type=exec, ExecStart=%h/.nix-profile/bin/tabrunner serve, Restart=always, RestartSec=5, Environment=TABRUNNER_LOG_DEV=0`, `[Install] WantedBy=default.target`. Add a `scripts/install-systemd.sh` that copies the unit to `~/.config/systemd/user/`, runs `daemon-reload`, optionally `enable --now`. [FR-081, IC-013, W-SYS-5]
  Done when: integration test on a host with systemd-user installs the unit, runs `systemctl --user start tabrunner`, asserts active state within 5s; restart simulation produces a fresh boot log.

- [ ] **T124** **Phase 9 validation**: full test suite + security scan green.

---

## Phase 10: README, RUNBOOK, .env.example, VS Code launch.json, pre-PR

**Purpose**: developer + operator documentation, full DX inventory.

- [ ] **T130** Generate [README.md](../../README.md) per `reference/readme.md`. Sections: title + tagline; description; architecture overview (1 paragraph + Mermaid graph from plan.md); getting started (Prerequisites; Install; Quickstart link); features list; configuration table; **Backup section** explicitly warning the CA key risk (FR-094); security notes; development setup; license. Verify every command in "Getting started" works by running it. [FR-094 (Backup section), reference/readme.md, W-SYS-8]
  Done when: README exists; every CLI command in the README runs without error in a clean nix-develop shell.

- [ ] **T131** Generate [RUNBOOK.md](../../RUNBOOK.md). Sections per W-SYS-7..W-SYS-12: log inspection, server restart, cert rotation, backup/restore, upgrade flow (with migration walk-through), Tailscale flap recovery, manual rebuild of FTS index (admin command — placeholder in v1 with `# DEFERRED v1.1`), CA key backup protection (W-SYS-8). [W-SYS-1..W-SYS-12]
  Done when: RUNBOOK has one section per W-SYS workflow; commands match those in the workflows.

- [ ] **T132** [P] Create [.env.example](../../.env.example) documenting `TABRUNNER_LOG_LEVEL`, `TABRUNNER_LOG_DEV`, `TABRUNNER_CONFIG`, `TABRUNNER_E2E_TEST` (test-only), `BUILD_VERSION` (build-time). [FR-087]
  Done when: every env var read anywhere in `src/**` has a corresponding line with a one-line description.

- [ ] **T133** [P] Create [.vscode/launch.json](../../.vscode/launch.json) with debug configs: `tabrunner serve`, `Run current test file (node:test)`, `Attach to running tabrunner`. [FR-088]
  Done when: each config can be launched from VS Code; the `tabrunner serve` config starts the server with breakpoints honored.

- [ ] **T134** [P] Wire size-limit check. Add a `.size-limit.json` constraining `public/app.js + public/app.css` to ≤ 100KB gzipped. Hook it into `npm run check` and `pre-pr`. [SC-003]
  Done when: `npx size-limit` runs and reports under 100KB; introducing a fake 50KB module bumps it over the limit and the check fails.

- [ ] **T135** Create the **pre-PR gate** target. Add to `Makefile` (or `scripts/pre-pr.sh`) a single command `make pre-pr` that runs (fail-fast):
  ```
  npm run typecheck && \
  npm run lint && \
  npm run test:unit && \
  npm run test:contract && \
  npm run test:integration && \
  npm run build && \
  npx size-limit && \
  bash scripts/security-scan.sh && \
  npm run test:e2e
  ```
  Wire `make pre-pr` into the conventional commits pre-push hook (optional; pre-commit covers smaller checks). [reference/pre-pr.md]
  Done when: `make pre-pr` runs all stages and exits 0 on the current clean tree; introducing a typecheck error fails the gate at the typecheck stage; introducing a critical security finding fails at the security stage.

- [ ] **T136** **Phase 10 validation**: `make pre-pr` exits 0 end-to-end.

---

## Phase E2E: Per-workflow tests + adversarial + restart resilience

**Purpose**: implement every workflow in [workflows.md](./workflows.md) as a Playwright test under `tests/e2e/`. The MCP exploration loop (`[needs: mcp-browser, e2e-loop]`) finds bugs; the scripted Playwright tests freeze the fix.

**Backend setup task** runs before any E2E task (the runner invokes it automatically):

- [ ] **T200** Create [tests/e2e/setup.sh](../../tests/e2e/setup.sh) and [tests/e2e/teardown.sh](../../tests/e2e/teardown.sh). Setup starts a test server bound to 127.0.0.1 (gated by `TABRUNNER_E2E_TEST=1`), creates a test CA + admin client cert, seeds a test project dir, writes `tests/e2e/.state/env.sh` with `TEST_SERVER_HOST`, `TEST_SERVER_PORT`, `TEST_CA_PATH`, `TEST_ADMIN_CERT_PATH`, `TEST_PROJECT_DIR`. Teardown SIGTERMs the test server, removes `.state/`, kills orphan fake-claude PIDs on known ports. Idempotent. [plan.md § Real-runtime E2E]
  Done when: running `bash tests/e2e/setup.sh` produces `.state/env.sh` with all 5 vars; subsequent `bash tests/e2e/teardown.sh` cleans up; running setup twice in a row is a no-op (idempotent).

**E2E task per workflow** — one task per row in [workflows.md](./workflows.md). All `[needs: mcp-browser]` tasks share one Chromium and MUST run sequentially (no `[P]`):

### Developer workflows

- [ ] **T201** E2E: W-DEV-1 — Cold dev shell + install + init produces working server. [W-DEV-1]
  Done when: `tests/e2e/dev-cold-bootstrap.test.ts` per workflows.md W-DEV-1 passes; no console errors; TLS handshake rejection on missing client cert.

- [ ] **T202** E2E: W-DEV-2 — File edit triggers tsx hot reload. [W-DEV-2]
- [ ] **T203** E2E: W-DEV-3 — PWA edit triggers esbuild rebuild and SW update prompt. [W-DEV-3, SC-019]
- [ ] **T204** E2E: W-DEV-4 — `npm run typecheck` strict + green on clean source. [W-DEV-4]
- [ ] **T205** E2E: W-DEV-5 — `npm run lint` rejects `any` / `@ts-ignore` / stray `console.log`. [W-DEV-5]
- [ ] **T206** E2E: W-DEV-6 — `npm run test` runs all tiers, structured reporter writes JSONL. [W-DEV-6, FR-T1, FR-T2]
- [ ] **T207** E2E: W-DEV-7 — Server exits 78 within 1s on claude version drift. [W-DEV-7, SC-013]
- [ ] **T208** E2E: W-DEV-8 — `clean` and `clean:all` semantics. [W-DEV-8]
- [ ] **T209** E2E: W-DEV-9 — code-review-graph stays fresh during edits. [W-DEV-9]

### Sysadmin workflows

- [ ] **T210** E2E: W-SYS-1 — `tabrunner init` on a clean host. [W-SYS-1, SC-014]
- [ ] **T211** E2E: W-SYS-2 — `tabrunner serve` fails fast when init not run. [W-SYS-2]
- [ ] **T212** E2E: W-SYS-3 — `tabrunner pair` CLI + successful CSR signing. [W-SYS-3, SC-001]
- [ ] **T213** E2E: W-SYS-4 — `tabrunner clients list|revoke`. [W-SYS-4, SC-012]
- [ ] **T214** E2E: W-SYS-5 — Install systemd unit + boot at login + crash recovery. [W-SYS-5]
- [ ] **T215** E2E: W-SYS-6 — Graceful shutdown via SIGTERM. [W-SYS-6]
- [ ] **T216** E2E: W-SYS-7 — Inspect logs via journalctl. [W-SYS-7]
- [ ] **T217** E2E: W-SYS-8 — Manual backup and restore of `data/`. [W-SYS-8]
- [ ] **T218** E2E: W-SYS-9 — `tabrunner sessions list|kill`. [W-SYS-9]
- [ ] **T219** E2E: W-SYS-10 — Tailscale interface flap recovery. [W-SYS-10] — **manual smoke documented in RUNBOOK; not automated**.
- [ ] **T220** E2E: W-SYS-11 — Upgrade flow with migration. [W-SYS-11]
- [ ] **T221** E2E: W-SYS-12 — Server cert auto-rotation. [W-SYS-12]

### Operator workflows

- [ ] **T230** [needs: mcp-browser, e2e-loop] E2E: W-OP-1 — Pair a new device (mobile-emulation Safari). [W-OP-1, US-1, SC-001]
  Done when: regression Playwright spec at `tests/e2e/pair-flow.test.ts` passes; MCP exploration finds zero P1 bugs; CC-1, CC-2 satisfied.

- [ ] **T231** [needs: mcp-browser, e2e-loop] E2E: W-OP-2 — Open New Tab + send first prompt. [W-OP-2, US-2, SC-002]
- [ ] **T232** [needs: mcp-browser, e2e-loop] E2E: W-OP-3 — Multi-tab parallelism (incl. 30-min soak gated to `npm run test:e2e:soak`). [W-OP-3, US-3, SC-004]
- [ ] **T233** [needs: mcp-browser, e2e-loop] E2E: W-OP-4 — Close + reopen via History. [W-OP-4, US-4]
- [ ] **T234** [needs: mcp-browser, e2e-loop] E2E: W-OP-5 — Meta agent observability query. [W-OP-5, US-5, SC-010, SC-011]
- [ ] **T235** [needs: mcp-browser, e2e-loop] E2E: W-OP-6 — FTS search across all sessions. [W-OP-6, US-6, SC-006]
- [ ] **T236** [needs: mcp-browser, e2e-loop] E2E: W-OP-7 — Server restart resilience (operator side). [W-OP-7, US-8, SC-005]
- [ ] **T237** E2E: W-OP-8 — Adversarial cert rejection sweep (no `mcp-browser` needed; pure curl). [W-OP-8, FR-005, FR-006, SC-012]
- [ ] **T238** [needs: mcp-browser, e2e-loop] E2E: W-OP-9 — Mobile-viewport drawer behavior. [W-OP-9, FR-067]
- [ ] **T239** [needs: mcp-browser, e2e-loop] E2E: W-OP-10 — PWA install to home screen. [W-OP-10, FR-068]
- [ ] **T240** [needs: mcp-browser, e2e-loop] E2E: W-OP-11 — Tool-call expand/collapse. [W-OP-11, FR-093, SC-015]
- [ ] **T241** [needs: mcp-browser, e2e-loop] E2E: W-OP-12 — Composer key bindings. [W-OP-12, FR-092, SC-016]
- [ ] **T242** [needs: mcp-browser, e2e-loop] E2E: W-OP-13 — Show raw stdout toggle. [W-OP-13, FR-072]
- [ ] **T243** [needs: mcp-browser, e2e-loop] E2E: W-OP-14 — PWA reconnect with replay-buffer hit. [W-OP-14, FR-032, SC-005]
- [ ] **T244** [needs: mcp-browser, e2e-loop] E2E: W-OP-15 — Session crashed UX. [W-OP-15, FR-031]
- [ ] **T245** [needs: mcp-browser, e2e-loop] E2E: W-OP-16 — Service-worker update prompt. [W-OP-16, FR-099, SC-019]

- [ ] **T246** Declare `test:e2e` script in `package.json` that runs all Playwright specs + invokes the runner for `[needs: mcp-browser, e2e-loop]` tasks. [phases/tasks.md § Reading workflows.md]
  Done when: `npm run test:e2e` runs end-to-end and exits 0 on a clean tree.

- [ ] **T247** **Phase E2E validation**: `npm run test:e2e` exits 0; the verify gate aggregates all per-workflow results; SC-009 satisfied (all eight user-story workflows pass).

---

## Phase 11: Smoke + observable output + CI

**Purpose**: ship.

- [ ] **T260** [needs: gh] Local smoke pass: from a clean HOME (`unset XDG_CONFIG_HOME XDG_DATA_HOME; HOME=/tmp/smoke-home`) run `npm install --ignore-scripts && npm rebuild ... && npm run build && tabrunner init && tabrunner serve &` and a paired Playwright session walks W-OP-1, W-OP-2, W-OP-5, W-OP-6. Capture failures into `test-logs/smoke/*.log`. Fix-validate loop (20 cap). [phases/tasks.md § Local smoke test phase]
  Done when: all four flows pass in the cold-home shell; logs show 0 errors; second run (warm) is faster than first (FR-T2 budgets).

- [ ] **T261** [P] [needs: gh] Validate README badges resolve to HTTP 200; verify `gh repo view` reports the right description and license; verify the CI workflow file is present on the default branch. [phases/tasks.md § Observable output validation phase]
  Done when: every badge URL returns 200; `gh api repos/<owner>/<repo>` shows license + description matching the README; `.github/workflows/ci.yml` present.

- [ ] **T262** Create [.github/workflows/ci.yml](../../.github/workflows/ci.yml) running (on push + PR): jobs `lint`, `typecheck`, `test-unit`, `test-contract`, `test-integration`, `build`, `security-scan` (uploads SARIF for trivy + semgrep via `github/codeql-action/upload-sarif@v3`), `test-e2e` (only on `develop`/`main` or with a label). All jobs run inside `nix develop`. `security-events: write` permission set. [FR-T1..T7, SC-008, reference/cicd.md]
  Done when: workflow YAML parses (`gh workflow list`); local sub-task verification (T263) runs every job's commands; first push triggers a run; first run is green.

- [ ] **T263-a** [P] Verify local: `nix develop --command bash -c 'npm run typecheck && npm run lint && npm run test:unit && npm run test:contract && npm run test:integration'`. Fix-validate loop, 20-iteration cap. [phases/tasks.md § CI workflow local verification]
  Done when: every command exits 0; tests produce non-zero counts; structured reporter outputs present in `test-logs/`.

- [ ] **T263-b** [P] Verify local: `nix develop --command bash -c 'npm run build && npx size-limit'`. Fix-validate loop, 20-iteration cap.
  Done when: `dist/` and `public/` produced; size budget met (SC-003).

- [ ] **T263-c** [P] Verify local: `nix develop --command bash scripts/security-scan.sh`. Fix-validate loop, 20-iteration cap.
  Done when: `test-logs/security/summary.json` shows 0 critical, 0 high; all four scanner JSON outputs present.

- [ ] **T264** [needs: gh, ci-loop] CI validation: push branch; runner-managed diagnose/fix loop on CI failures (15-cycle cap); creates PR when CI is green. [phases/tasks.md § CI/CD validation phase]
  Done when: PR exists on GitHub with all checks green; structured CI artifacts (`test-logs/`, `test-logs/security/`) uploaded; `ci-debug/<task_id>/` present locally for any debug iterations that ran.

---

## Phase Final: Code review

- [ ] **T270** REVIEW: spawn `code-review-react` (the PWA is Preact, same family) and `code-review-node` for the server. Both consume the merge candidate. Apply auto-fixes; write `REVIEW-TODO.md` for human-required follow-ups; run fix-validate loop until both reviews are clean. [phases/implement.md § Code review]
  Done when: both reviewers report no CRITICAL or HIGH findings; `REVIEW-TODO.md` (if any) tracks LOW/MEDIUM as future work; `make pre-pr` exits 0 post-review.

---

## Phase Dependencies

```
Phase 1 (Setup) → Phase 2 (Foundational) → Phase 3 (TLS) → Phase 4 (Sessions) → Phase 5 (WS) → Phase 6 (REST) → Phase 7 (Meta MCP) → Phase 8 (PWA) → Phase 9 (CLI+systemd) → Phase 10 (Docs) → Phase E2E → Phase 11 (Smoke+CI) → Phase Final (Review)
```

**Parallelizable within phase**: `[P]` tags above. **Single-runtime constraint**: Phase E2E `[needs: mcp-browser]` tasks share one Chromium and run sequentially.

**Critical path**: T002 (claude pinned) → T016 (Phase 1 validation) → T049 (TLS checkpoint) → T065 (session checkpoint) → T075 (WS checkpoint) → T094 (meta checkpoint) → T114 (PWA day-one) → T264 (CI green) → T270 (review clean).

## Approach (reminder)

Fix-validate loop. Each phase ends with a validation task that runs build + typecheck + lint + tests + security scan; on failure, the runner reads `test-logs/<phase>-<run>.jsonl`, fixes, re-runs until green. No phase advances with red. Code review runs at the end with auto-fix-and-recheck.
