# E2E Failure Patterns

Known failure signatures for E2E platform-runtime boot and their typical root
causes. The runner matches the failure against these signatures and injects
only the matching sections into the fix-agent prompt.

Entries follow this shape:

```
## Signature: <short name>
**Match:** <regex or string the runner greps setup-failure.log / service logs for>
**Typical root cause:** <one paragraph>
**Diagnostic commands:** <shell commands to confirm>
**Fix options:** <ranked preferences>
**Anti-patterns:** <common wrong fixes>
```

Add a new entry every time a fix-agent diagnoses a new class of failure.
Keep each entry under ~40 lines — precision beats prose.

---

## Signature: port-timeout-but-service-ready

**Match:** `setup-failure.log` shows `ERROR: <service> did not start within Ns on port P`
AND `.dev/e2e-state/<service>.log` shows "ready" / "listening" / "started" within that window.

**Typical root cause:** The service is up, but on a different interface than
the health check. Most common: service binds to `[::1]` (IPv6 loopback) while
`nc -z 127.0.0.1 PORT` only checks IPv4. Less common: service binds to a
specific subpath, or the probe hits `/` but the service only responds on
`/health`, `/kanix/`, etc.

**Diagnostic commands:**

```bash
ss -tlnp | grep :PORT      # what interface is the port bound to?
curl -sv http://127.0.0.1:PORT/ 2>&1 | head -5
curl -sv http://[::1]:PORT/ 2>&1 | head -5
curl -sv http://localhost:PORT/ 2>&1 | head -5
```

If `ss` shows `[::1]:PORT` but `127.0.0.1` curl fails, it's IPv4/IPv6 mismatch.

**Fix options (ranked):**

1. Add `--host 127.0.0.1` (or `--host 0.0.0.0`) to the service's start command.
   Astro: `astro dev --host 127.0.0.1`. Vite: `vite --host 127.0.0.1`.
2. Change `wait_for_port` / `nc -z 127.0.0.1` to try both IPv4 and IPv6.
3. Use `curl` against a known-good path instead of `nc`.

**Anti-patterns:**

- Raising the timeout. The service was ready in <1s; waiting longer won't help.
- Switching from `nc` to `sleep N` — sleeps mask races, they don't fix them.
- Rebinding everything to `0.0.0.0` in prod configs. Limit the bind change
  to dev/E2E scripts.

---

## Signature: config-validation-missing-required

**Match:** `.dev/e2e-state/api.log` (or equivalent service log) contains
`Config validation failed` or `missing required config: <KEY>`.

**Typical root cause:** `.env` has placeholder values (`REPLACE_ME`,
`sk_test_REPLACE_ME`) for keys the config loader treats as required.
`.env.example` was copied verbatim into `.env` without filling in test
values. The config loader does not distinguish "required for prod" from
"required for E2E smoke test."

**Diagnostic commands:**

```bash
grep -E '=REPLACE_ME|=sk_test_REPLACE_ME|=$' .env | head -20
# Compare against what the loader requires:
grep -rE 'requireEnv|required.*true|missing required' api/src/config
```

**Fix options (ranked):**

1. Populate `.env` with obvious test-mode values for the missing keys.
   Use clearly-fake placeholders so nobody mistakes them for real secrets:
   `STRIPE_SECRET_KEY=sk_test_e2e_placeholder_not_real`,
   `GITHUB_OAUTH_CLIENT_ID=e2e-github-client-id`, etc.
2. In the config loader, mark keys as optional when `NODE_ENV=test` or
   when a dedicated `E2E_MODE=1` flag is set. Preserve prod strictness.
3. Add a `test/e2e/.env.e2e` that setup.sh merges into `.env` before
   starting services.

**Anti-patterns:**

- Committing real API keys to `.env` in the repo.
- Disabling the whole config validator — that masks legitimate missing-key
  bugs in production.
- Removing the keys from `config.ts` so validation passes — you break the
  feature that needs them.

---

## Signature: service-crash-on-boot

**Match:** Service log shows a stack trace, `panic`, `Error:`, or exits
before `ready`. `wait_for_port` times out but NOT because of a health-check
mismatch — the port is never actually bound.

**Typical root cause:** Runtime error in the service — missing dependency,
bad config value, port already in use, DB migration not applied, etc.
The error is in the service log; read it.

**Diagnostic commands:**

```bash
tail -100 .dev/e2e-state/<service>.log
ss -tlnp | grep :PORT   # confirm port is NOT bound
lsof -i tcp:PORT        # is something else holding it?
```

**Fix options:** depends entirely on the stack trace. Read it, then fix it.

**Anti-patterns:**

- Restarting the service in a loop hoping it "works this time."
- Killing whatever is on the port without understanding why — you may
  kill the user's legitimate dev server.

---

## Signature: stale-process-guard-skipped-restart

**Match:** Setup script has an `if ! nc -z 127.0.0.1 PORT; then start; fi`
guard, the port is already up (from a prior broken attempt), and the current
attempt's log says nothing new was started.

**Typical root cause:** Previous setup attempt left a broken service
running. The idempotency guard short-circuits the restart, so you're
debugging against the old broken state.

**Diagnostic commands:**

```bash
ps -p $(cat .dev/e2e-state/<service>.pid 2>/dev/null) -o pid,etime,cmd
# If elapsed time is > a few minutes, it's stale.
tail -20 .dev/e2e-state/<service>.log
# Old timestamp = stale log.
```

**Fix options (ranked):**

1. Kill the stale process and its PID file, then re-run setup.
2. Improve teardown script so it always runs at the start of setup (not
   just on failure).
3. Make the guard check readiness, not just port binding (`curl -f health`
   instead of `nc -z`).

**Anti-patterns:**

- Removing the idempotency guard entirely — setup should still be re-runnable.
- Adding `sleep 10` before the guard check.

---

## Signature: migration-already-applied

**Match:** `migrate.log` shows `duplicate key`, `already exists`,
`relation "X" already exists`, or Liquibase `unexpected checksum`.

**Typical root cause:** Migration is being re-run against a DB that already
has the changes, but the migration isn't idempotent, OR a prior run applied
only part of the migration and left the tracking table inconsistent.

**Diagnostic commands:**

```bash
tail -50 .dev/e2e-state/migrate.log
psql -h 127.0.0.1 -U kanix -d kanix -c "SELECT * FROM databasechangelog ORDER BY dateexecuted DESC LIMIT 5;"
```

**Fix options (ranked):**

1. Make the migration idempotent (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN
   IF NOT EXISTS`).
2. If the tracking table is inconsistent: wipe `.dev/pgdata` and re-run from
   scratch. Only safe in dev/E2E — never in prod.
3. Tolerate migration failure in setup.sh (already done by some projects):
   log a warning but continue. Valid only if a subsequent verification
   step confirms the schema is correct.

**Anti-patterns:**

- Skipping migration step entirely.
- Deleting rows from `databasechangelog` to force re-application.

---

## Signature: browser-install-hang

**Match:** explore-agent's jsonl log shows a tool call to
`mcp__mcp-browser__browser_install` (or the MCP server spawns a child
process running `playwright ... install chrome`) that makes no progress
for >2 minutes. `ps` shows the install process sleeping with 0 network
connections; no `chrome*.zip` lands in `~/.cache/ms-playwright/`.

**Typical root cause:** upstream `@playwright/mcp` defaults to
`--browser chrome` (Google Chrome, branded). Playwright refuses to
accept Nix's `chromium` as a substitute for the `chrome` channel and
tries to download Chrome into `~/.cache/ms-playwright/`. Inside the
agent's bubblewrap sandbox there is no stdin TTY for any confirmation
prompt, so the download silently hangs forever. The runner's idle
watchdog eventually kills it, costing 10-15 minutes per retry.

**Diagnostic commands:**

```bash
ps -ef | grep 'playwright.*install' | grep -v grep
ls -la ~/.cache/ms-playwright/ 2>/dev/null
ss -tnp | grep -E '(chrome|playwright)'  # any active connections?
cat .specify/mcp/browser.json  # is --executable-path configured?
```

**Fix options (ranked):**

1. **Fix at the Nix-packaging layer (preferred, durable):** the
   `mcp-browser` wrapper in `nix-mcp-debugkit/browser/default.nix`
   should inject `--browser chromium --executable-path <path to
   chromium inside playwright-driver.browsers>` by default, and
   export `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`. See the `nix-mcp-debugkit`
   repo for the canonical implementation — the wrapper globs
   `$PLAYWRIGHT_BROWSERS_PATH/chromium-*/chrome-linux*/chrome` at launch.
2. **If the Nix wrapper can't be updated right now (e.g. you're
   blocked on a flake-input bump):** edit the project's MCP config
   (commonly `.specify/mcp/browser.json`) to pass explicit args:
   ```json
   {
     "mcpServers": {
       "mcp-browser": {
         "command": "/path/to/mcp-browser",
         "args": [
           "--browser", "chromium",
           "--executable-path", "/nix/store/.../chromium-<rev>/chrome-linux64/chrome"
         ]
       }
     }
   }
   ```
   Resolve the chromium path from `nix eval nixpkgs#playwright-driver.browsers`
   plus a glob.
3. **Never** commit a fix that tells Claude to keep retrying
   `browser_install` with a different channel. The download will hang
   the same way.

**Anti-patterns:**

- Raising the agent's idle watchdog — the download is never going to finish.
- Preinstalling Chrome into `~/.cache/ms-playwright/` on the host —
  works once, then breaks when the cache is gc'd or the host changes.
- Bundling `google-chrome` as an unfree Nixpkgs input — licensing aside,
  it adds a heavy input for no gain over `chromium`.

---

## Signature: emulator-boot-timeout (Android)

**Match:** Android platform boot: `start-emulator` times out, `adb devices`
shows no devices or only `offline`.

**Typical root cause:** No AVD configured, KVM not enabled, emulator headless
mode flag missing, or host hardware doesn't support KVM.

**Diagnostic commands:**

```bash
emulator -list-avds
ls /dev/kvm && lsmod | grep kvm
adb devices
cat /proc/cpuinfo | grep -E 'vmx|svm'
```

**Fix options:** project-specific — check `scripts/start-emulator.sh` or the
Nix flake for expected AVD name.

**Anti-patterns:**

- Running an emulator without `-no-window -no-audio -no-snapshot` on CI.
- Ignoring missing `/dev/kvm` — emulation will be unusably slow.
