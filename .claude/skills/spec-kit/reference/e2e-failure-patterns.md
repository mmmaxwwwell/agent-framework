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

## Signature: stale-android-apk-after-source-fix (Android)

**Match:** A bug fix to a Flutter or Android source file landed (committed
or staged). A subsequent `flutter build apk --debug` (or `gradlew
assembleDebug`) reports exit 0 and "Built app-debug.apk" / "BUILD
SUCCESSFUL". `adb install -r` then succeeds. But the bug's `verify.sh`
still fails — the running app behaves like the pre-fix code.

Concretely: the APK file mtime predates the fix commit, OR
`unzip -p <apk> assets/flutter_assets/kernel_blob.bin | strings | grep
<post-fix-symbol>` returns empty, OR `adb shell dumpsys package <pkg> |
grep lastUpdateTime` shows a timestamp older than the latest build.

**Typical root cause:** Gradle's incremental build cache hit. The source
file changed but the task's cache key didn't invalidate (most often: the
edit only touched a string literal Gradle considered semantically equal
to the prior build's input, or the worktree's mtime is older than the
last-known-good cache snapshot, or a parent task's "UP-TO-DATE" verdict
short-circuited the dependency chain). Gradle then reuses the pre-fix
artifact. `adb install -r` accepts the valid APK and reports success,
but it's the same broken binary as before.

The build agent and the verify agent both see "exit 0" signals and
naturally conclude the fix shipped. Multiple fix iterations in a row
will hit this same cache and reach the same wrong conclusion. The kanix
T099 case ran 4 iterations × multiple agents × ~2 hours of wall-clock
before one agent finally typed `flutter clean`.

**Diagnostic commands:**

```bash
APK=$(find <build-root>/build/app/outputs -name '*-debug.apk' | head -1)
ls -l "$APK"                                 # mtime — compare to fix commit
git log -1 --format='%ci %h %s' -- <source>  # when did the fix land?
unzip -p "$APK" assets/flutter_assets/kernel_blob.bin | strings | \
  grep '<post-fix-symbol>'                   # empty = pre-fix code in APK
adb shell dumpsys package <pkg> | grep lastUpdateTime
                                              # device install timestamp
```

If APK mtime > fix commit AND grep finds the post-fix symbol AND
device lastUpdateTime > APK mtime, the fix is genuinely deployed. If
ANY of those three fails, the cache lied to you.

**Fix (mandatory — do not skip the clean step):**

```bash
cd <flutter-app> && flutter clean && \
  flutter build apk --debug && \
  adb install -r build/app/outputs/flutter-apk/app-debug.apk
```

For pure Gradle: `./gradlew clean assembleDebug` then `adb install -r`.

**`flutter clean` is mandatory after any source change** — the project's
build scripts (`scripts/e2e-install-apks.sh` and `test/e2e/setup.sh`)
already detect staleness and run it automatically; if you are
building outside those scripts (e.g. directly via `flutter build apk`),
you must run `flutter clean` first whenever any source file is newer
than the existing APK.

**Verify the install actually applied** — every Android `verify.sh`
for a code-fix bug must grep the installed APK's content, not just
the build log. Sample:

```bash
#!/usr/bin/env bash
set -eu
APK=$(find admin/build/app/outputs -name '*-debug.apk' | head -1)
if unzip -p "$APK" assets/flutter_assets/kernel_blob.bin 2>/dev/null \
     | strings | grep -q '/api/admin/fulfillment-tasks'; then
  echo "STATUS: FIXED"
  echo "EVIDENCE: APK kernel_blob.bin contains post-fix URL"
  exit 0
else
  echo "STATUS: STILL_BROKEN"
  echo "EVIDENCE: APK does not contain post-fix URL — Gradle cache hit"
  exit 1
fi
```

**Anti-patterns:**

- **Trusting build-log mtime > fix-commit epoch as proof of recompilation.**
  The build log writes whether or not the cache hit. Mtime of the log
  tells you the build *ran*, not that it *recompiled*.
- **Trusting Gradle's "exit 0 / Built app-debug.apk" output.** Cache
  hits print these too.
- **Trusting `adb install -r` to mean "new code on device."** It will
  happily reinstall the same APK with no observable change.
- **Re-running `flutter build apk` without `flutter clean` and expecting
  different output.** Guaranteed to hit the same cache; this is the
  literal loop the kanix T099 case got stuck in for 4 iterations.

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

---

## Signature: mcp-launch-failed

**Match:** Boot diagnostics show `_e2e_services_started: True` AND `_booted runtimes: []` with services (Postgres / SuperTokens / API / Astro) listening on their ports. setup.sh exited 0. The failure is specifically that the Claude CLI could not spawn the MCP server.

**Typical root cause:** The MCP server binary itself can't launch, and the Claude CLI's stderr is invisible to the runner so the only visible signal is "no runtimes booted."

Common causes:

- **bwrap sandbox + `nix run`.** When `.mcp.json` is configured as `{"command": "nix", "args": ["run", ".#mcp-android"]}`, `nix run` needs write access to `/nix/var/nix/db/big-lock`. The runner launches Claude inside a bwrap sandbox with `--ro-bind /nix/store /nix/store`, making the nix store read-only. `nix run` fails with "Permission denied" and the MCP server never starts.
- **Placeholder binary.** The `nix-mcp-debugkit` flake input resolved to a placeholder store path (either from a stale cache or a build that silently fell through). The binary exists on PATH but immediately exits or prints an unrelated help message.
- **Missing shared library.** The binary launched in the runner's shell (where the devShell packages are on PATH) but the Claude CLI spawns it in a reduced env where LD_LIBRARY_PATH or similar isn't populated.
- **MCP protocol mismatch.** The server speaks an older MCP version than the Claude CLI expects (e.g. `2024-05-15` vs. `2024-11-05`). Server launches, CLI sends `initialize`, server rejects and exits.

**Diagnostic commands:**

```bash
# Read the probe's captured stderr — this is the authoritative error.
cat .specify/mcp/android.stderr
cat .specify/mcp/android.stdout

# Reproduce the launch outside the sandbox. If this works but the probe fails,
# the issue is sandbox/env-related.
nix develop --command mcp-android --emulator < /dev/null &

# Reproduce inside bwrap to confirm the sandbox is the constraint.
# (The runner's probe does this automatically — see cost-reporting.md § Prompt-caching strategy.)
```

**Fix options (ranked):**

1. **Direct binary on PATH instead of `nix run`.** In the project flake's devShell, add the MCP binary itself (`mcp-android`, `mcp-browser`) to `packages`, then change `.mcp.json` to `{"command": "mcp-android"}` with no `nix run` wrapper. The binary is on PATH after `nix develop` and the Claude CLI can spawn it inside the sandbox without needing write access to the nix store.
2. **Refresh the flake input.** If `nix-mcp-debugkit` evaluates to a placeholder: `nix flake update nix-mcp-debugkit` in the project, then re-enter `nix develop`.
3. **Upgrade the MCP server.** If the stderr shows a protocol-version rejection, bump `nix-mcp-debugkit` to a commit that speaks the CLI's version.

**Anti-patterns:**

- Editing `test/e2e/setup.sh`. setup.sh is not the failure path — services are up. Agents that chase setup.sh logs waste 2-4 attempts before noticing.
- Raising the boot timeout. The MCP server either launches in <1s or doesn't launch at all; time is not the variable.
- Re-running `nix develop` from inside the runner without re-entering the sandbox. The devShell the runner sees is frozen at runner start.

## Signature: mcp-exits-clean-within-5s (fixed — historical)

**Match:** MCP server exits with code 0 within 5s of receiving `initialize`, stdout contains a valid JSON-RPC `initialize` response, probe labels it `crashed`.

**This is NOT a bug in the MCP server.** The MCP stdio transport spec says a compliant server shuts down cleanly when stdin closes (client disconnect signal). If you see `exit code 0` within 5s of a successful `initialize` response, the server is doing the right thing — something closed stdin on it.

**Historical root cause (now fixed in `parallel_runner.py`):** `probe_mcp_launch` used `subprocess.communicate(input=init_req, timeout=5)`, which closes stdin after writing. Spec-compliant servers (Playwright MCP v0.0.56 and any other well-behaved MCP server) respond to the `initialize`, then exit cleanly on the stdin close. The probe read `exit 0 within 5s` as a crash.

**Current probe behavior:** `probe_mcp_launch` now writes `initialize`, keeps stdin open, reads one response line with a 5s deadline, then checks `poll()` for liveness. A server that exits during this window has genuinely crashed. A server still running at `t+5s` with a valid JSON-RPC response on stdout is healthy.

**If this signature re-appears:**

1. Confirm you're running a version of `parallel_runner.py` that contains the `selectors`-based read loop. Search for `import selectors` in the file; if absent, the runner is pre-fix.
2. Do NOT add per-repo keepalive wrappers (delayed-stdin-close shims in `flake.nix`, `.mcp.json`, or a `scripts/mcp-*-keepalive.js`). They papered over the runner bug; they are not needed once the runner is fixed and they make debugging harder by making one repo's `mcp-browser` behave differently from every other consumer's.
3. Do NOT patch `nix-mcp-debugkit` or the upstream MCP server to delay stdin-close handling — that would break spec compliance for every other consumer.

**Residual risk:** A real crash (the server genuinely dies mid-init) is still reported as `crashed` — the fixed probe distinguishes clean-disconnect-on-stdin-close from unexpected-exit by not closing stdin during the liveness window. If you see a crash claim and are suspicious, check the probe's captured `stderr` file — a real crash leaves a real error there.
