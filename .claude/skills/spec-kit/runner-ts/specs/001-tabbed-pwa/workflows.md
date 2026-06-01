# Workflows — tabrunner 001-tabbed-pwa

This file is the **E2E test contract**. One workflow → one E2E test, exhaustively scripted at selector + network granularity. The runner's verify gate (Phase 7) executes every workflow.

## Personas

- **Developer** (`W-DEV-*`): a human running tabrunner locally with `npm run dev`, iterating on code, debugging, profiling. Sees dev-mode logs and HMR.
- **Sysadmin** (`W-SYS-*`): a human setting up, installing, and operating the built artifact on a Linux host. Runs `tabrunner init`, installs the systemd unit, pairs devices, rotates secrets, inspects logs, restores from backup, upgrades. May be the same human as the Operator, but the role is distinct.
- **Operator** (`W-OP-*`): a human using the PWA from any paired device on the Tailnet to drive Claude Code sessions across tabs and ask the meta agent cross-session questions.

Workflow ids use the persona prefix; numbering is per-persona.

## Coverage matrix

| Persona | Workflow count | Touches |
|---|---|---|
| Developer | 9 | FR-086..089 (DX), FR-091 (claude version), `research.md` D-022 (tests), `plan.md` Phase 1 |
| Sysadmin | 12 | US-1, US-7, US-8, FR-081..082, FR-094..096, FR-098, FR-001..006, FR-013..015 |
| Operator | 16 | US-1..US-6, US-8, FR-007..020, FR-023..035, FR-046, FR-051..065, FR-066..080, FR-092..093, FR-099 |

Total: 37 workflows.

---

## Developer workflows

### W-DEV-1 — Cold `nix develop && npm install && npm run dev` produces a working server + PWA

**Persona**: developer
**Touches**: FR-086, FR-089, research.md D-001/D-022
**Trigger**: dev runs `nix develop && npm install --ignore-scripts && npm rebuild better-sqlite3 node-pty && npm run dev` after a fresh clone
**Preconditions**: clean checkout; no `~/.config/tabrunner/config.toml`; no `~/.local/share/tabrunner/` (clean home); Tailscale running; Node 22 from flake
**Bypass paths**: no production install; no systemd unit; the PWA is served from `tsx`-compiled source, not built `dist/`

**Steps**:

1. **Action**: `nix develop` in repo root.
   **Expected stdout**: lines matching `tabrunner devshell — node v22.\d+.\d+, uv \d+\.\d+\.\d+`; `code-review-graph` watcher start lines; no `error:` substrings.
   **Expected network**: none (nix fetches from cache; ok if cached).
   **Negative assertions**: no `command not found`, no `error[E0001]`-style rust errors from nix.

2. **Action**: `npm install --ignore-scripts && npm rebuild better-sqlite3 node-pty`.
   **Expected stdout**: `added \d+ packages` from install; rebuild lines for `better-sqlite3` and `node-pty` mention `gyp info ok`.
   **Negative assertions**: no `EACCES`, no `gyp ERR`, no fallback to a non-pinned Python.

3. **Action**: `tabrunner init` interactive, answer `/tmp/dev-test-project` (create the dir first: `mkdir -p /tmp/dev-test-project`).
   **Expected stdout**: prompts for project path; on completion, lines listing the created files: `~/.config/tabrunner/config.toml`, `~/.local/share/tabrunner/{ca.pem,ca-key.pem,server-cert.pem,server-key.pem,tabrunner.db}`.
   **Expected file system**: those files exist; `ca-key.pem` and `server-key.pem` have mode 0600.
   **Negative assertions**: no `EEXIST`, no half-created files on failure.

4. **Action**: `npm run dev` (this runs `tsx watch src/server.ts` plus the PWA bundle watch).
   **Expected stdout**: `tabrunner listening on https://100.x.y.z:8443`; pino dev-pretty lines (since `TABRUNNER_LOG_DEV=1` is set by `npm run dev`); `FTS initial scan complete (0 sessions indexed)`.
   **Expected network**: server bound to Tailscale IPv4 only; `ss -tlnp` shows the port bound to that IP, not `0.0.0.0`.
   **Negative assertions**: no console error from PWA bundler; no `unhandledRejection` in server logs.

5. **Action**: in a second terminal, `curl --cacert ~/.local/share/tabrunner/ca.pem -k https://100.x.y.z:8443/api/v1/health` (intentionally no client cert).
   **Expected stdout**: TLS handshake fails with `alert handshake failure` or `tlsv13 alert certificate required`. HTTP body is empty (server never sees the request).
   **Expected network**: connection closed at TLS layer; no HTTP response.
   **Negative assertions**: no 200 OK; no JSON response body.

**Edge cases**:
- E1: claude binary not in flake → step 4 fails fast with FR-091 message; W-DEV-7 covers this in detail.
- E2: Tailscale not running → step 4 fails fast with `error: tailscale not running or no IPv4 assigned`; the dev workflow stops here, dev must start tailscale.
- E3: `~/.config/tabrunner/config.toml` already exists from a prior run → step 3 prints `current state: config exists, data dir exists, ...` and exits 0 idempotently.

**Performance budget**: step 1 + step 2 ≤ 120 s cold (cache fill), ≤ 5 s warm. Step 4 listening within 2 s of invocation (SC-007).

**Test command**: `npm run test:e2e -- --grep W-DEV-1`

---

### W-DEV-2 — File edit triggers tsx hot reload

**Persona**: developer
**Touches**: FR-086, research.md D-022
**Trigger**: dev edits a source file while `npm run dev` is running
**Preconditions**: server running via `npm run dev`; an open WS client connected
**Bypass paths**: not testing the PWA bundle watcher (W-DEV-3 covers that)

**Steps**:

1. **Action**: edit `src/lib/logger.ts` to add a `logger.info({ test: "hmr" }, "hmr probe")` at module top.
   **Expected stdout**: `tsx` re-runs server within 2 s; new boot logs include `hmr probe`.
   **Expected network**: existing WS connection drops; PWA reconnects with `client.hello`+`resume`; server replays buffered events.
   **Negative assertions**: no orphan PID; `ps aux | grep tabrunner` count is exactly 1 server process post-reload.

**Edge cases**:
- E1: edit a TS syntax error → tsx prints error, does NOT restart; previous server continues running.

**Performance budget**: edit-to-reload ≤ 3 s.

**Test command**: `npm run test:e2e -- --grep W-DEV-2`

---

### W-DEV-3 — PWA edit triggers esbuild rebuild and SW update prompt

**Persona**: developer
**Touches**: FR-099, research.md D-021
**Trigger**: dev edits a Preact component while PWA bundle watch is running
**Preconditions**: `npm run build:client` watch running; PWA open in a browser with mTLS paired

**Steps**:

1. **Action**: edit `src/pwa/ui/Composer.tsx` to add a `data-testid="hmr-marker"` attribute.
   **Expected file system**: `public/app.js` rebuilt within 1 s.
   **Expected stdout**: esbuild prints `Build success`.
2. **Action**: reload the browser tab.
   **Expected DOM**: `[data-testid="hmr-marker"]` exists.
   **Expected network**: `GET /api/v1/sw-version` returns the new version string; SW posts `update_available` via MessageChannel; PWA shows a banner `role="status"` `name~="New version available"`.
   **Negative assertions**: no stale chunk loaded; no `404` on `/app.js`.

**Performance budget**: edit-to-reload ≤ 5 s including manual reload.

**Test command**: `npm run test:e2e -- --grep W-DEV-3`

---

### W-DEV-4 — `npm run typecheck` is strict and exits 0 on clean source

**Persona**: developer
**Touches**: research.md D-001
**Trigger**: dev runs `npm run typecheck`
**Preconditions**: clean source tree

**Steps**:

1. **Action**: `npm run typecheck`.
   **Expected stdout**: `tsc --noEmit` runs; exit code 0; no warnings.
   **Negative assertions**: no `any` slipped through; no `// @ts-ignore` introduced (lint rule catches these — covered in W-DEV-5).

**Performance budget**: ≤ 15 s on a warm cache.

**Test command**: `npm run typecheck`

---

### W-DEV-5 — `npm run lint` rejects `any`, `@ts-ignore`, and `console.log` outside dev-only files

**Persona**: developer
**Touches**: research.md D-001
**Trigger**: dev runs `npm run lint`

**Steps**:

1. **Action**: `npm run lint`.
   **Expected**: exit 0.
2. **Action**: introduce `const x: any = 1` in `src/lib/logger.ts`, re-run.
   **Expected**: exit non-zero; eslint reports `no-explicit-any` violation with line number.

**Performance budget**: ≤ 5 s.

**Test command**: `npm run lint`

---

### W-DEV-6 — `npm run test` runs all tiers and exits 0 on clean source

**Persona**: developer
**Touches**: FR-T1, FR-T2
**Trigger**: dev runs `npm run test`

**Steps**:

1. **Action**: `npm run test`.
   **Expected stdout**: structured test reporter output (one JSONL row per test); summary line `unit: N pass / 0 fail`, `integration: M pass / 0 fail`, `contract: K pass / 0 fail`. E2E gated to `npm run test:e2e`.
   **Expected file system**: `test-logs/<phase>-<run>.jsonl` exists.
   **Negative assertions**: no `skipped` row counts > 0 except for documented skips with reason.

**Performance budget**: unit ≤ 10 s; contract ≤ 30 s; integration ≤ 120 s (FR-T2).

**Test command**: `npm run test`

---

### W-DEV-7 — Server refuses to start when claude version drifts

**Persona**: developer
**Touches**: FR-091, SC-013, research.md D-017
**Trigger**: dev temporarily shadows `claude` with a wrong-version stub
**Preconditions**: `EXPECTED_CLAUDE_MAJOR_MINOR = "1.0"` in source; flake-pinned claude is 1.0.x

**Steps**:

1. **Action**: prepend a script `~/bin/claude` that prints `claude 2.0.0` and exit 0. Add `~/bin` to PATH ahead of nix.
   **Expected**: `tabrunner serve` exits 78 within 1 s; stderr contains `unexpected claude version 2.0.x; expected 1.0.x. Update tabrunner or pin claude back.`
   **Negative assertions**: no Fastify listener log; no `tabrunner.db` writes after the version check.

**Performance budget**: detect + exit ≤ 1 s (SC-013).

**Test command**: `npm run test:e2e -- --grep W-DEV-7`

---

### W-DEV-8 — `npm run clean` removes only build artifacts; `clean:all` also removes data

**Persona**: developer
**Touches**: FR-086
**Trigger**: dev runs each clean variant

**Steps**:

1. **Action**: `npm run clean`.
   **Expected file system**: `dist/`, `public/app.js`, `public/sw.js`, `public/app.css`, `test-logs/`, `validate/`, `attempts/`, `ci-debug/` removed. `~/.local/share/tabrunner/` UNCHANGED.
2. **Action**: `npm run clean:all`.
   **Expected file system**: everything from `clean` PLUS `~/.local/share/tabrunner/` removed. `~/.config/tabrunner/config.toml` UNCHANGED (config is precious; cleaning means re-running `tabrunner init` to regenerate the CA).

**Test command**: `npm run test:e2e -- --grep W-DEV-8`

---

### W-DEV-9 — Code-review-graph is fresh while editing

**Persona**: developer
**Touches**: D-001 (CLAUDE.md stanza), CLAUDE.md
**Trigger**: dev edits a file while in `nix develop`
**Preconditions**: code-review-graph watcher started by shellHook

**Steps**:

1. **Action**: add a new exported function `export const sentinel = 42` to `src/lib/time.ts`. Wait 2 s for watcher.
2. **Action**: `code-review-graph query --pattern "function:sentinel"` (or the equivalent MCP `query_graph_tool`).
   **Expected stdout**: the new function appears as a node.

**Performance budget**: file change → graph update ≤ 2 s.

**Test command**: manual; documented in RUNBOOK as a smoke test.

---

## Sysadmin workflows

### W-SYS-1 — `tabrunner init` on a clean host

**Persona**: sysadmin
**Touches**: US-1 (precondition), FR-095, FR-096, SC-014
**Trigger**: sysadmin runs `tabrunner init` for the first time
**Preconditions**: no `~/.config/tabrunner/`; no `~/.local/share/tabrunner/`; project dir exists at chosen path; Tailscale running
**Bypass paths**: no pairing yet (W-SYS-3 covers that)

**Steps**:

1. **Action**: `tabrunner init`. At prompt, answer absolute path to a real project directory.
   **Expected stdout**: prompt rendered as `Watched project path: `; on submit, summary lines `Created config at ~/.config/tabrunner/config.toml`, `Created data dir at ~/.local/share/tabrunner`, `Generated CA (ECDSA P-256, 10-year)`, `Generated server certificate (90-day, SAN=100.x.y.z)`, `Initialized SQLite database (schema_version=1)`, `Now run: tabrunner serve`.
   **Expected file system**: `~/.local/share/tabrunner/{ca.pem,ca-key.pem,server-cert.pem,server-key.pem,tabrunner.db}` exist; `ca-key.pem`/`server-key.pem` mode 0600; `tabrunner.db` is valid SQLite with `_meta.schema_version=1`.
   **Negative assertions**: no `0644` on key files; no half-created files; no server listening yet.

**Edge cases**:
- E1: project dir does not exist → prompt re-asks with `error: /not/a/path is not a directory`.
- E2: `~/.config/tabrunner/config.toml` already exists → prints `current state: config exists, data dir exists, ...` and exits 0 (idempotent); use `--force` to overwrite.
- E3: insufficient permissions to create `~/.config/tabrunner/` → exit 78 with `error: cannot write to ~/.config/tabrunner/: permission denied`.

**Performance budget**: ≤ 10 s end-to-end (SC-014). CA generation dominates.

**Test command**: `npm run test:e2e -- --grep W-SYS-1`

---

### W-SYS-2 — `tabrunner serve` fails fast when init has not been run

**Persona**: sysadmin
**Touches**: FR-095
**Trigger**: sysadmin runs `tabrunner serve` without prior init
**Preconditions**: no config, no data dir

**Steps**:

1. **Action**: `tabrunner serve`.
   **Expected stdout**: exit code 78 within 1 s; stderr lines like `error: no config at ~/.config/tabrunner/config.toml. Run 'tabrunner init' to create one.`
   **Negative assertions**: no listener bound; no DB created; no CA created.

**Edge cases**:
- E1: config present but data dir missing → distinct error message: `error: data dir ~/.local/share/tabrunner missing. Run 'tabrunner init'.`
- E2: data dir present but missing `ca.pem` → `error: CA missing at ~/.local/share/tabrunner/ca.pem. Run 'tabrunner init' to regenerate.`
- E3: DB missing → similar.

**Test command**: `npm run test:e2e -- --grep W-SYS-2`

---

### W-SYS-3 — `tabrunner pair` from CLI and successful CSR signing

**Persona**: sysadmin
**Touches**: US-1, FR-007..011, FR-014, SC-001
**Trigger**: sysadmin runs `tabrunner pair`
**Preconditions**: server running; no existing pairing token

**Steps**:

1. **Action**: `tabrunner pair`.
   **Expected stdout**: a QR code rendered to terminal; URL `https://100.x.y.z:8443/pair/<token>`; line `Token valid for 5 minutes or one use.`
   **Expected DB**: a new row in `pairing_tokens` with `expires_at = created_at + 5min`, `used_at IS NULL`.
2. **Action**: from a paired test client (Playwright with WebCrypto), visit the URL.
   **Expected DOM**: pairing page renders; `role="status"` shows `Generating keypair…` → `Awaiting server signature…` → `Pairing complete!`
   **Expected network**: `GET /pair/<token>` returns 200 HTML; `POST /pair/<token>/csr` with CSR body returns 200 JSON with `client_cert_pem`, `ca_cert_pem`, `fingerprint`, `expires_at`.
   **Expected DB**: pairing token `used_at` is now set; `clients` row inserted.
3. **Action**: with the new client cert, `curl --cert client.pem --key client.key --cacert ca.pem https://100.x.y.z:8443/api/v1/health`.
   **Expected response**: 200 JSON `{ok:true, version, tailscale_ip, uptime_s, sessions_running}`.

**Edge cases**:
- E1: token expired (>5 min) → step 2 returns 410 Gone.
- E2: token used twice (re-POST CSR) → second POST returns 410 Gone.
- E3: malformed CSR (RSA instead of P-256) → 422 with `{error:"invalid_csr",message:"expected ECDSA P-256, got RSA"}`.
- E4: two clients race CSR with same token → first 200, second 409 Conflict.

**Performance budget**: pair-to-first-message ≤ 60 s (SC-001), where the bulk is the human walking to a device.

**Test command**: `npm run test:e2e -- --grep W-SYS-3`

---

### W-SYS-4 — `tabrunner clients list` and `revoke`

**Persona**: sysadmin
**Touches**: US-7, FR-014, FR-015, SC-012
**Trigger**: sysadmin lists then revokes a client
**Preconditions**: at least one paired client (from W-SYS-3)

**Steps**:

1. **Action**: `tabrunner clients list`.
   **Expected stdout**: table with columns `FINGERPRINT  COMMON_NAME  ISSUED_AT  EXPIRES_AT  LAST_SEEN  REVOKED`. JSON via `--json`.
2. **Action**: `tabrunner clients revoke <fp>`.
   **Expected stdout**: `Revoked <fp> at <iso-timestamp>`.
   **Expected DB**: `clients.revoked_at` set.
3. **Action**: from the now-revoked device, `curl ... https://.../api/v1/health` within 5 s.
   **Expected**: TLS handshake fails.

**Edge cases**:
- E1: revoke unknown fingerprint → exit 0 with warn line `not found, no-op`.
- E2: revoke an already-revoked fingerprint → exit 0; idempotent.

**Performance budget**: revoke effective within 5 s of command (SC-012).

**Test command**: `npm run test:e2e -- --grep W-SYS-4`

---

### W-SYS-5 — Install systemd user unit and boot at login

**Persona**: sysadmin
**Touches**: FR-081
**Trigger**: sysadmin installs the unit and enables it
**Preconditions**: `tabrunner init` done

**Steps**:

1. **Action**: `mkdir -p ~/.config/systemd/user && cp etc/systemd/tabrunner.service ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now tabrunner`.
   **Expected**: `systemctl --user is-active tabrunner` → `active`.
   **Expected stdout**: `journalctl --user -u tabrunner -n 20` shows `tabrunner listening on https://100.x.y.z:8443`.
2. **Action**: reboot the host (or simulate via `systemctl --user restart tabrunner`).
   **Expected**: service auto-starts; `is-active` → `active`; logs show fresh boot.
3. **Action**: `kill -9 $(pidof tabrunner)` (simulate crash).
   **Expected**: systemd restarts the unit within 5 s; new PID; logs show fresh boot.

**Edge cases**:
- E1: `tailscaled.service` not up at boot → unit waits for it (`After=tailscaled.service`); when tailscale comes up, unit starts.

**Performance budget**: enable → active ≤ 5 s.

**Test command**: covered in `tests/e2e/server-restart.test.ts`; full systemd dance documented in RUNBOOK for manual verification.

---

### W-SYS-6 — Graceful shutdown via SIGTERM

**Persona**: sysadmin
**Touches**: US-8, FR-030, FR-031
**Trigger**: sysadmin sends SIGTERM (e.g., `systemctl --user stop tabrunner`)
**Preconditions**: server running; ≥1 active session

**Steps**:

1. **Action**: open 3 tabs in PWA; each tab has a long-running fake-claude (sleeps then writes).
2. **Action**: `systemctl --user stop tabrunner` (or `kill -TERM <pid>` directly).
   **Expected WS frames** (each active PWA client): `session.shutdown_pending` with `deadline_s: 10`.
   **Expected process tree**: server SIGTERMs each claude PID; PIDs exit within 10 s; if any stalls, SIGKILL at +10 s.
   **Expected DB**: all 3 session rows updated: `status='terminated'`, `exited_at` set, `pid` cleared.
   **Expected exit**: server exits 0.
   **Negative assertions**: no `crashed` status (because we initiated SIGTERM); no orphan PIDs (`pgrep claude` returns nothing after 12 s).

**Edge cases**:
- E1: a claude PID hangs past 10 s → SIGKILL fires; session marked `terminated` with `exit_signal: 'SIGKILL'`.
- E2: shutdown during an in-flight DB write → write completes before close; `tabrunner.db` opens cleanly on next start.

**Performance budget**: 0 → server exit ≤ 12 s with 3 sessions.

**Test command**: `npm run test:e2e -- --grep W-SYS-6` (uses fake-claude harness)

---

### W-SYS-7 — Inspect logs via journalctl

**Persona**: sysadmin
**Touches**: FR-083..085
**Trigger**: sysadmin reads logs

**Steps**:

1. **Action**: `journalctl --user -u tabrunner -f`.
   **Expected stdout**: each line is valid JSON (no pino-pretty in prod); fields include `time`, `level`, `msg`, `connection_id`/`session_id`/`audit_id` when relevant.
2. **Action**: `journalctl --user -u tabrunner | jq 'select(.channel == "audit")'`.
   **Expected stdout**: only audit lines; each has `actor`, `outcome`, optional `tool`/`args`/`reason`.

**Performance budget**: N/A (log inspection).

**Test command**: manual smoke; covered structurally by FR-085 unit tests.

---

### W-SYS-8 — Manual backup and restore of `data/`

**Persona**: sysadmin
**Touches**: FR-050, FR-094
**Trigger**: sysadmin backs up while server is stopped, then restores
**Preconditions**: ≥1 paired client; ≥1 session in history

**Steps**:

1. **Action**: `systemctl --user stop tabrunner && cp -a ~/.local/share/tabrunner /tmp/tabrunner-backup && systemctl --user start tabrunner`.
   **Expected file system**: `/tmp/tabrunner-backup/` contains the same files with the same modes (0600 on key files).
2. **Action**: simulate data loss: `systemctl --user stop tabrunner && rm -rf ~/.local/share/tabrunner && cp -a /tmp/tabrunner-backup ~/.local/share/tabrunner && systemctl --user start tabrunner`.
   **Expected**: server starts; previously-paired client still connects (CA + clients table intact); previous session history visible in PWA.

**Edge cases**:
- E1: backup taken while server is running via `sqlite3 .backup` → restore works; documented in RUNBOOK.

**Performance budget**: N/A.

**Test command**: `npm run test:e2e -- --grep W-SYS-8`

---

### W-SYS-9 — `tabrunner sessions list` and `kill <id>`

**Persona**: sysadmin
**Touches**: US-7, FR-028, FR-029
**Trigger**: sysadmin lists then kills a session from CLI

**Steps**:

1. **Action**: from PWA, start a session; note its UUID.
2. **Action**: `tabrunner sessions list`.
   **Expected stdout**: table includes the new session_id with status=running, PID set.
3. **Action**: `tabrunner sessions kill <uuid>`.
   **Expected**: SIGTERM, 10 s grace, SIGKILL if needed; PWA's WS receives `session.exit` with `reason: "process killed by SIGTERM after 10s grace"` (or earlier if process exits cleanly); DB row `status=terminated`.
4. **Action**: `tabrunner sessions kill <uuid>` again.
   **Expected**: idempotent — exit 0, prints `already exited at <timestamp>`.

**Performance budget**: SIGTERM → DB updated ≤ 11 s.

**Test command**: `npm run test:e2e -- --grep W-SYS-9`

---

### W-SYS-10 — Tailscale interface flap recovery

**Persona**: sysadmin
**Touches**: FR-001, FR-002
**Trigger**: sysadmin restarts tailscale while server is running

**Steps**:

1. **Action**: server is up with bound socket on 100.x.y.z:8443.
2. **Action**: `sudo systemctl restart tailscaled` (or stop tailscale).
   **Expected**: server keeps current socket bound (tcp socket is in kernel; Tailscale flap doesn't immediately kill it). Existing WS clients may drop and reconnect.
3. **Action**: if Tailscale IP changes (rare) → server exits 1 with log line `tailscale IP changed; restart needed`; systemd restarts the unit which rebinds to the new IP.

**Performance budget**: rebind via systemd ≤ 10 s.

**Test command**: documented in RUNBOOK; not automated (requires tailscale daemon control).

---

### W-SYS-11 — Upgrade from one tabrunner version to the next

**Persona**: sysadmin
**Touches**: FR-037 (migrations)
**Trigger**: sysadmin pulls a new tabrunner version with a new migration

**Steps**:

1. **Action**: `systemctl --user stop tabrunner`.
2. **Action**: `git pull && npm install --ignore-scripts && npm rebuild ... && npm run build`.
3. **Action**: `systemctl --user start tabrunner`.
   **Expected stdout**: server boot logs include `applying migration 002_*.sql`; then `schema_version=2`; then `listening on ...`.
   **Expected DB**: `_meta.schema_version=2`; new columns/tables from the migration present.
4. **Action**: pretend a downgrade — re-deploy old code with `schema_version` already at 2.
   **Expected**: server exits 1 with `error: db schema_version=2 newer than supported max=1`.

**Performance budget**: typical upgrade ≤ 30 s.

**Test command**: `npm run test:e2e -- --grep W-SYS-11`

---

### W-SYS-12 — Rotate server cert (auto and manual)

**Persona**: sysadmin
**Touches**: FR-004
**Trigger**: server cert approaches 30-day window OR sysadmin manually rotates

**Steps**:

1. **Action**: time-warp the system clock to a date 60 days before server cert expiry. Restart server.
   **Expected stdout**: `regenerating server cert (expires within 30 days)`; file `server-cert.pem` is overwritten; new cert has new SAN/serial.
2. **Action**: manually: `rm ~/.local/share/tabrunner/server-cert.pem && systemctl --user restart tabrunner`.
   **Expected**: server detects missing cert, regenerates from CA; clients still trust because the CA didn't change.

**Performance budget**: rotation ≤ 2 s of startup.

**Test command**: `npm run test:e2e -- --grep W-SYS-12`

---

## Operator workflows

### W-OP-1 — Pair a new device (mobile Safari emulation) from the PWA pairing flow

**Persona**: operator
**Touches**: US-1, FR-007..011, SC-001
**Trigger**: operator scans pairing QR on a phone
**Preconditions**: server running; sysadmin ran `tabrunner pair`; mobile-emulation browser

**Steps**:

1. **Action**: navigate to `https://100.x.y.z:8443/pair/<token>` (mobile-emulation viewport 390×844, iOS Safari UA).
   **Expected DOM**: page has `role="heading"` `name="Pair this device"`; `role="status"` `name~="Generating keypair"`; CC-2 (Tailwind class on heading has resolved background-color).
   **Expected network**: `GET /pair/<token>` returns 200 HTML; subresources load (app.js, app.css) without 4xx/5xx.
   **Negative assertions**: no console error; no `role="alert"`.

2. **Action**: wait for WebCrypto keygen + CSR + server signature.
   **Expected DOM**: `role="status"` updates `Generating keypair…` → `Awaiting server signature…` → `Pairing complete! Installing certificate…`.
   **Expected network**: `POST /pair/<token>/csr` returns 200 with `{client_cert_pem, ca_cert_pem, fingerprint, expires_at}`.

3. **Action**: cert install is offered by the browser (in test, we use Playwright's `browserContext.addClientCertificates`).
   **Expected DOM**: page redirects to `/`; tab bar renders; pinned Meta tab visible.

**Edge cases**:
- E1: token expired → step 1 returns 410 Gone HTML page with `role="alert"` `name~="Pairing link expired"`.
- E2: browser without WebCrypto (HTTP-only context, never happens here because mTLS=HTTPS) → page shows `role="alert"` `name~="WebCrypto unavailable"`.
- E3: network blip mid-CSR → page shows `Retry` button (`role="button"` `name="Retry"`); clicking retries the POST.

**Performance budget**: pair → PWA loaded ≤ 60 s (SC-001) including human scan time; the automated CSR portion ≤ 5 s.

**Cross-cutting**: CC-1, CC-2.

**Test command**: `npm run test:e2e -- --grep W-OP-1`

---

### W-OP-2 — Open a New Tab and send first prompt

**Persona**: operator
**Touches**: US-2, FR-016..020, FR-072, SC-002
**Trigger**: operator clicks "New Tab" in PWA tab bar
**Preconditions**: PWA paired and loaded; pinned Meta tab present; no other tabs

**Steps**:

1. **Action**: click `role="button"` `name="New tab"`.
   **Expected DOM**: tab bar now has 2 tabs — pinned Meta + a new "New session" tab; new tab is active.
   **Expected network**: `POST /api/v1/sessions` with body `{title:null,resume_id:null}` returns 201; WS frame `session.created` arrives within 200 ms; then `session.status {status:"pending"}` → `session.status {status:"running",pid:<n>}`.
   **Negative assertions**: no `role="alert"`; no 5xx.

2. **Action**: focus the composer textarea (`role="textbox"` `name~="Message"`), type "hello", press Enter.
   **Expected DOM**: textarea clears; user message bubble appears with text "hello".
   **Expected network**: WS frame `client.input` with `payload.text="hello"`, `append_newline:true`; then server-side `session.stdout` frames (raw bytes) and `session.message {role:"user", content:"hello"}` followed by `session.message {role:"assistant", content:"..."}`.

3. **Action**: wait for assistant response.
   **Expected DOM**: assistant message bubble appears with response text; tool calls (if any) render collapsed (`role="button"` `name~="Bash:"` etc.).

**Edge cases**:
- E1: server returns 503 (not ready) → toast `role="alert"` `name~="Server not ready, retry"`.
- E2: WS disconnects mid-response → "reconnecting" banner; on reconnect, missed frames replay via `client.hello.resume`.

**Performance budget**: click → `session.message` first byte ≤ 3 s (SC-002).

**Cross-cutting**: CC-1, CC-2, CC-3.

**Test command**: `npm run test:e2e -- --grep W-OP-2`

---

### W-OP-3 — Open multiple tabs in parallel

**Persona**: operator
**Touches**: US-3, FR-024, FR-025, SC-004
**Trigger**: operator opens 5 tabs and starts a session in each
**Preconditions**: PWA loaded

**Steps**:

1. **Action**: click "New Tab" 5 times rapidly.
   **Expected DOM**: 6 tabs (Meta + 5 new); a running-count badge `role="status"` `name="5 running"` appears once N≥2; clicking it reveals a menu listing 5 session titles.
   **Expected network**: 5 `POST /api/v1/sessions`; 5 `session.created` WS frames; 5 `session.status {status:running}` frames.
   **Expected process tree**: `pgrep -f claude` returns 5 PIDs after a moment.

2. **Action**: in each tab, type a distinct prompt (`tab1 says foo`, `tab2 says bar`, ...).
   **Expected DOM**: each tab's chat area shows only its own messages; switching tabs is < 200 ms.

3. **Action**: leave running for 30 minutes (soak).
   **Expected**: 5 PIDs stable; `tabrunner sessions list` shows 5 running; no `crashed` rows; memory growth bounded (< 100 MB total for the 5 processes).

**Edge cases**:
- E1: host runs out of memory → claude PIDs may crash; tabs show `role="alert"` with `crashed` status.

**Performance budget**: 5 sessions stable over 30 min with no PID leaks (SC-004).

**Cross-cutting**: CC-1.

**Test command**: `npm run test:e2e -- --grep W-OP-3` (soak variant gated to `npm run test:e2e:soak`)

---

### W-OP-4 — Close a tab; reopen from History

**Persona**: operator
**Touches**: US-4, FR-021..023, FR-026
**Trigger**: operator closes a tab and later reopens it
**Preconditions**: one running tab with 3 messages exchanged

**Steps**:

1. **Action**: click the tab's X button.
   **Expected DOM**: confirmation dialog `role="dialog"` `name~="Close tab?"` with text "(Session keeps running in History view until you reopen it)" and a "Don't ask again" checkbox; buttons `role="button"` `name="Close"` and `name="Cancel"`.
2. **Action**: click "Close".
   **Expected DOM**: tab disappears from tab bar.
   **Expected network**: WS frame `client.close_tab`; server SIGTERMs PID; `session.exit {status:"terminated", reason:"operator closed tab"}` within 10 s.
3. **Action**: open History view via sidebar/drawer.
   **Expected DOM**: closed session listed with title (= first user message), project, last_activity, status=`terminated`, message count.
4. **Action**: click the session row.
   **Expected DOM**: a new tab opens, populated with replayed messages (user/assistant/tool_call/tool_result bubbles in order); composer enabled.
   **Expected network**: `POST /api/v1/sessions/<id>/reopen` → 201; WS frame `session.created` then `session.message` replay then `session.status {status:running}`.
   **Expected process tree**: a new claude PID exists; `claude --resume <uuid>` was the spawn invocation (verified via `ps`).
5. **Action**: type "continuing", press Enter.
   **Expected**: assistant response continues the conversation correctly (proves `--resume` worked).

**Edge cases**:
- E1: original claude PID was still alive when reopened → no new spawn; subscribe to existing PID.
- E2: jsonl file deleted manually → reopen still works (creates fresh session under same UUID); operator sees only new messages.

**Performance budget**: close → tab gone ≤ 500 ms; reopen → messages replayed ≤ 3 s.

**Test command**: `npm run test:e2e -- --grep W-OP-4`

---

### W-OP-5 — Ask the meta agent: which session is waiting

**Persona**: operator
**Touches**: US-5, FR-051..065, SC-010
**Trigger**: operator opens Meta tab and asks a question
**Preconditions**: ≥2 sessions running; one stalled (e.g. prompted for input)

**Steps**:

1. **Action**: click the pinned Meta tab.
   **Expected DOM**: Meta tab shows a distinct icon (`role="img"` `name~="Meta"`) and header banner `role="banner"` `name~="Meta agent (read-only)"`.
2. **Action**: type "which session is waiting for input right now? show me the last 30 lines.", press Enter.
   **Expected network**: standard `client.input` WS frame to the meta session; then `meta.tool_call` frames as the meta agent calls `list_running()` and `tail_live()`; then `meta.tool_result` frames; then assistant message with the answer.
   **Expected DOM**: tool calls render collapsed (`role="button"` `name~="list_running"`, `name~="tail_live"`); assistant message identifies the stalled session by title and shows last 30 lines snippet.
3. **Action**: click the tool-call summary `name~="tail_live"`.
   **Expected DOM**: expanded panel shows `args: {session_id: "...", lines: 30}` and result body.

**Edge cases**:
- E1: meta agent tries a forbidden tool (e.g. `spawn_session`) → MCP returns method-not-found; assistant explains.
- E2: meta agent calls `read_project_file("../../etc/passwd")` → 403 + audit log entry; assistant explains.

**Performance budget**: `tail_live` p95 ≤ 200 ms on 10K-line session (SC-010).

**Test command**: `npm run test:e2e -- --grep W-OP-5`

---

### W-OP-6 — Search across all sessions

**Persona**: operator
**Touches**: US-6, FR-046, FR-076, SC-006
**Trigger**: operator searches in History view
**Preconditions**: ≥3 closed sessions, each with distinct content

**Steps**:

1. **Action**: open History view (sidebar item `role="link"` `name="History"`).
   **Expected DOM**: list of sessions in reverse-chronological order; search box `role="searchbox"`.
2. **Action**: type a distinctive phrase that appears in one session's messages; debounce 300 ms.
   **Expected network**: `GET /api/v1/sessions?search=<encoded query>&limit=50` → 200; payload has `sessions` array filtered to FTS5 matches with `next_cursor`.
   **Expected DOM**: result list updates; each row shows a highlighted snippet from the matching message.
3. **Action**: click a result.
   **Expected DOM**: a new tab opens with that session replayed (read-only if process is dead; resume-able if alive).

**Edge cases**:
- E1: query returns 0 matches → DOM shows `role="status"` `name~="No sessions match"`.
- E2: query syntax error (special FTS5 chars) → server returns 422; UI shows `role="alert"` with the parse error.
- E3: FTS index lag — session was just closed and isn't searchable yet → result list omits it; UI shows `role="status"` `name~="Indexing recent sessions"` if `pending_index: true`.

**Performance budget**: FTS lag ≤ 5 s (SC-006); search → result render ≤ 500 ms.

**Test command**: `npm run test:e2e -- --grep W-OP-6`

---

### W-OP-7 — Server restart while tabs are open

**Persona**: operator
**Touches**: US-8, FR-030, FR-032, SC-005
**Trigger**: sysadmin restarts the server while operator has tabs open

**Steps**:

1. **Action**: operator has 3 tabs running; each has streamed several messages.
2. **Action**: sysadmin runs `systemctl --user restart tabrunner`.
   **Expected DOM** (operator's PWA): `role="status"` `name~="Reconnecting"` banner appears; tab bar dims but stays visible; existing message history remains rendered.
   **Expected WS**: each connection drops; PWA retries with exponential backoff (1 s, 2 s, 4 s, 8 s, capped 30 s).
3. **Action**: server reboots within ~5 s; PWA reconnects.
   **Expected DOM**: banner clears; tab bar refreshes to show 0 running sessions (server killed them all on shutdown). Tabs are still visible — they're rendering message history — but their composer is disabled with a "Session ended" badge and a "Reopen" button.
4. **Action**: click "Reopen" on a tab.
   **Expected**: as W-OP-4 from step 4 onward.

**Edge cases**:
- E1: backoff hits 30 s cap because server is genuinely down → operator can manually click "Retry now" button.
- E2: PWA disconnect exceeds 60 s buffer → on reconnect, full state re-fetch via REST (not WS replay); operator sees brief loading state then full sync.

**Performance budget**: reconnect → first new event ≤ 1 s (SC-005); full sysadmin-initiated restart cycle ≤ 15 s.

**Test command**: `npm run test:e2e -- --grep W-OP-7`

---

### W-OP-8 — Reject unauthenticated request at TLS layer

**Persona**: operator (adversarial)
**Touches**: FR-005, FR-006
**Trigger**: operator (or anyone on the tailnet) tries to connect without a paired cert
**Preconditions**: server running

**Steps**:

1. **Action**: from an UN-paired tailnet device, `curl --cacert ca.pem https://100.x.y.z:8443/api/v1/health` (no `--cert`).
   **Expected**: TLS handshake fails; curl prints `alert handshake failure` or equivalent; HTTP body empty.
2. **Action**: `curl --cert wrong-ca-client.pem --key wrong.key --cacert ca.pem https://100.x.y.z:8443/api/v1/health`.
   **Expected**: TLS handshake fails (server rejects cert not signed by our CA).
3. **Action**: with expired client cert (artificially expired): handshake fails.
4. **Action**: with revoked client cert: handshake fails on next attempt (within 5 s of revoke).

**Negative assertions**: no application logs for the rejected requests beyond the TLS-level rejection line.

**Performance budget**: revocation effective within 5 s (SC-012).

**Test command**: `npm run test:e2e -- --grep W-OP-8`

---

### W-OP-9 — Mobile-viewport tab bar drawer behavior

**Persona**: operator
**Touches**: FR-067
**Trigger**: operator uses PWA on mobile (viewport <768 px)

**Steps**:

1. **Action**: emulate iPhone (viewport 390×844).
   **Expected DOM**: top-level tab bar is hidden; a hamburger button `role="button"` `name~="Open tabs"` is present in the header; clicking it opens a drawer (`role="dialog"` `name~="Tabs"`) listing all tabs.
   **Expected computed style**: hamburger button is ≥44px×44px (FR-067 touch target).
2. **Action**: select a tab from the drawer; drawer closes; tab body fills viewport.

**Performance budget**: drawer open animation ≤ 200 ms.

**Cross-cutting**: CC-1, CC-2.

**Test command**: `npm run test:e2e -- --grep W-OP-9`

---

### W-OP-10 — PWA install to home screen

**Persona**: operator
**Touches**: FR-068
**Trigger**: operator triggers Add to Home Screen on supported browser

**Steps**:

1. **Action**: in Chrome (Android emulation), open PWA root. Manifest loads.
   **Expected network**: `GET /manifest.webmanifest` → 200 with `{name:"tabrunner", icons:[...], display:"standalone", theme_color:"..."}`.
   **Expected**: install prompt becomes available via `beforeinstallprompt` event.
2. **Action**: programmatic install.
   **Expected**: PWA appears installable; subsequent launch from home screen loads PWA in standalone mode.

**Performance budget**: N/A.

**Test command**: `npm run test:e2e -- --grep W-OP-10` (Chrome only; Safari install is manual)

---

### W-OP-11 — Tool-call render expand/collapse

**Persona**: operator
**Touches**: FR-093, SC-015
**Trigger**: operator interacts with a tool-call bubble in a session

**Steps**:

1. **Action**: in a session where the assistant called `Bash: ls -la`, observe the rendered bubble.
   **Expected DOM**: a `role="button"` `name="Bash: ls -la"` collapsed bubble; no result text visible.
2. **Action**: click the bubble.
   **Expected DOM**: bubble expands within 100 ms; shows full args and tool result. If result > 50 lines, a "show full" link is present and the displayed result is truncated.
3. **Action**: click again to collapse.
   **Expected DOM**: bubble returns to collapsed state.

**Performance budget**: click → expanded ≤ 100 ms (SC-015).

**Test command**: `npm run test:e2e -- --grep W-OP-11`

---

### W-OP-12 — Composer key bindings (Enter / Shift+Enter / Cmd+Enter)

**Persona**: operator
**Touches**: FR-092, SC-016
**Trigger**: operator types in the composer

**Steps**:

1. **Action**: type "line1", press Enter.
   **Expected**: message sent; composer cleared.
2. **Action**: type "line1", press Shift+Enter, type "line2", press Enter.
   **Expected**: message sent with two lines; composer cleared.
3. **Action** (mobile emulation): type "line1", press Cmd+Enter (or Ctrl+Enter).
   **Expected**: message sent; composer cleared; no newline inserted.
4. **Action**: with empty composer, click the explicit Send button.
   **Expected**: no-op (button disabled when empty).

**Performance budget**: send → echo back ≤ 200 ms.

**Test command**: `npm run test:e2e -- --grep W-OP-12`

---

### W-OP-13 — Show raw stdout toggle

**Persona**: operator
**Touches**: FR-072
**Trigger**: operator toggles "Show raw" in a tab

**Steps**:

1. **Action**: in a running tab, click `role="button"` `name~="Show raw"` toggle.
   **Expected DOM**: chat bubbles are replaced (or supplemented) by a monospace panel showing raw ANSI bytes; ANSI escape codes either rendered (with a terminal style component) or stripped, but never displayed as `^[[` literal.
2. **Action**: click the toggle again.
   **Expected DOM**: returns to chat-bubble view.

**Test command**: `npm run test:e2e -- --grep W-OP-13`

---

### W-OP-14 — PWA reconnect with replay-buffer hit

**Persona**: operator
**Touches**: FR-032, SC-005
**Trigger**: WS disconnects briefly while a session is streaming

**Steps**:

1. **Action**: in a tab streaming a long assistant response, briefly drop WS (test harness disconnects the socket).
   **Expected DOM**: "reconnecting" banner appears.
2. **Action**: wait ~1 s; WS reconnects.
   **Expected network**: `client.hello` sent with `resume: {<session-id>: <last-seq>}`; server replays missed events (`session.message`, `session.stdout`) for that session.
   **Expected DOM**: chat continues; no duplicate messages; banner clears.

**Edge cases**:
- E1: gap > 60 s buffer → server cannot replay; PWA does full re-fetch via REST.

**Performance budget**: reconnect → first replayed event ≤ 1 s (SC-005).

**Test command**: `npm run test:e2e -- --grep W-OP-14`

---

### W-OP-15 — Session crashed (non-zero exit) shown to operator

**Persona**: operator
**Touches**: FR-027, FR-031
**Trigger**: claude crashes mid-session

**Steps**:

1. **Action**: in test, fake-claude is configured to exit 137 (OOM-killer-like) mid-response.
   **Expected WS**: `session.exit {status:"crashed", exit_code:137, exit_signal:"SIGKILL", reason:"claude process killed (signal SIGKILL)"}`.
   **Expected DOM**: tab shows a red banner `role="alert"` `name~="Session crashed"` with exit code and the last 50 lines from `tail_live` snapshot; composer is disabled; a "Reopen with --resume" button is present.
2. **Action**: click the Reopen button.
   **Expected**: new session row entry via `--resume`; tab continues.

**Test command**: `npm run test:e2e -- --grep W-OP-15`

---

### W-OP-16 — PWA service-worker update prompt

**Persona**: operator
**Touches**: FR-099, SC-019
**Trigger**: server build version bumps while PWA is open

**Steps**:

1. **Action**: PWA loaded; SW version = "v1".
2. **Action**: test harness bumps server build version to "v2"; PWA navigates (or 60-second poll fires).
   **Expected network**: `GET /api/v1/sw-version` → `{version:"v2"}`; SW detects mismatch; posts `update_available` via MessageChannel.
   **Expected DOM**: prompt banner `role="status"` `name~="New version available"` with `role="button"` `name="Reload"`.
3. **Action**: click Reload.
   **Expected**: `skipWaiting()` runs; page reloads; new SW active; version now "v2".

**Performance budget**: bump → prompt ≤ 60 s (SC-019).

**Test command**: `npm run test:e2e -- --grep W-OP-16`

---

## Cross-cutting assertions

Things every workflow asserts, referenced by `[CC-N]` from steps where relevant:

- **CC-1**: No console errors or warnings throughout the workflow. (Captured via Playwright `page.on('console')`.)
- **CC-2**: At least one CSS class on the first rendered page has a resolved non-`rgba(0,0,0,0)` computed background-color. (Catches "PostCSS dropped" / "stylesheet not built" regressions.)
- **CC-3**: No request to `/api/error` or any URL containing `internal-error` fires. No 5xx response from any server endpoint during the workflow.
- **CC-4**: Every request that the workflow expects MUST present a valid client certificate (except `/pair/*` endpoints).
- **CC-5**: Every WS frame from server includes a `seq` monotonic per session_id; PWA never receives a frame with `seq` ≤ a previously-seen frame for the same session_id (except during replay-buffer resume, where the gap is documented in the resume request).
- **CC-6**: All HTTP responses include the 5 mandatory security headers (FR-097). Verified in W-OP-2 step 1 and asserted globally via a `tests/contract/http-shapes.test.ts`.

---

## Coverage cross-check against spec.md

Every user story is covered by at least one operator workflow:
- US-1 → W-OP-1 (and W-SYS-3 for the CLI portion)
- US-2 → W-OP-2
- US-3 → W-OP-3
- US-4 → W-OP-4
- US-5 → W-OP-5
- US-6 → W-OP-6
- US-7 → W-SYS-4, W-SYS-9
- US-8 → W-OP-7, W-SYS-6

Every spec.md "Edge Cases & Failure Modes" entry is referenced by at least one workflow's edge cases block:
- Pairing edges → W-OP-1 E1..E3, W-SYS-3 E1..E4.
- TLS edges → W-OP-8.
- Session lifecycle edges → W-OP-2 E1..E2, W-OP-15, W-SYS-6 E1..E2, W-SYS-9.
- WebSocket edges → W-OP-7, W-OP-14.
- Meta agent edges → W-OP-5 E1..E2.
- FTS indexing edges → W-OP-6 E3.
- Disk/DB edges → W-SYS-8 (backup/restore covers corruption recovery via restore); schema downgrade in W-SYS-11.
- Operational edges → W-SYS-3 E1..E4, W-SYS-4 E1..E2, W-SYS-9.
