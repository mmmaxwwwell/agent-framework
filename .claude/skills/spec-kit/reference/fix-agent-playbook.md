# Fix-Agent Playbook

General debugging heuristics for agents spawned to repair a specific failure.
These are not task-specific — they apply to every fix-agent, every time.
They exist because cold-start agents default to "explore the repo and guess,"
which burns tokens and often fixes the wrong thing.

## Core principle: reproduce before hypothesizing

Do not form a hypothesis from logs alone. Logs are frozen snapshots and may
not reflect current state. Before editing any code:

1. Run the failing command yourself and watch it fail *live*.
2. Capture the live output. Compare it to the diagnostic you were given —
   if they differ, the diagnostic is stale and you must start over.
3. Only form a hypothesis after you've seen the failure with your own eyes.

If reproducing would take >5 minutes (e.g. a full CI run), prefer a minimal
repro: isolate the failing command and run just that.

## When a health check disagrees with a log

If `wait_for_port` / `curl` / `nc` / readiness probe says "not ready" but the
service's log says "started," **the disagreement is the bug, not the timeout**.
Do not raise the timeout. The service is reachable on some interface/path/auth
mode that the check isn't using. Diagnose:

- **Interface binding**: `ss -tlnp | grep :PORT` or `netstat -tlnp | grep :PORT`.
  If bound to `[::1]` (IPv6) but check uses `127.0.0.1` (IPv4), fix the bind
  flag (`--host 127.0.0.1` or `--host 0.0.0.0`) or the check.
- **Path**: check the exact URL the probe hits. Some services serve only on
  a subpath (`/api/health`, `/kanix/`) and return 404 on `/`.
- **Auth**: if the probe expects 200 but gets 401, add auth or pick a
  public endpoint.
- **Protocol**: HTTP vs HTTPS, HTTP/1 vs HTTP/2.

## Stale processes poison diagnostics

Idempotent setup scripts typically guard starts with `if ! nc -z PORT`. If a
prior attempt left the service running, your script skips the restart and you
debug against a **stale process with a stale log**. Before debugging any
"setup timeout," run:

```bash
# Find processes on the failing ports
for p in PORT1 PORT2 ...; do lsof -ti tcp:$p; done | xargs -r kill -9
# Remove PID files
rm -f .dev/e2e-state/*.pid
```

Then re-run setup from a clean slate. If the failure only happens after a
clean restart, it's a real bug. If it only happens after a stale restart,
fix the teardown, not the setup.

## Read the *failed* log, not all logs

When a multi-service setup fails, the diagnostic should already identify
which service failed. Open that one log first. Stop at the first line
containing `ERROR`, `FATAL`, `panic`, `Config validation failed`, or
`missing required`. That line is almost always the root cause. Do not
scan sibling services' logs until you've ruled out the named one.

## Check prior fix attempts before editing

Run `git log --oneline -20` and `git diff HEAD~N..HEAD -- <suspect-files>`
to see what prior fix-agents changed. If the last attempt already tried
your hypothesis and it failed, pick a different approach. Re-applying a
known-failed fix is the #1 way this loop wastes 10 attempts.

If the project tracks attempt history (e.g. `test/e2e/.state/fix-history.md`,
`.state/attempts/`), read it. Each entry should tell you what was tried
and what still failed.

## Verify by cold re-run, not guarded re-run

"Exit 0" is not proof of a fix. Many setup scripts have `if ! nc -z PORT`
guards that short-circuit when a service is already up — including when
it's up in a broken state. Verify by:

1. Stop all related processes.
2. Clear `.state` / `.pid` files.
3. Run the full command from scratch.
4. Confirm exit 0 *and* the thing you fixed actually behaves correctly.

If verification requires destructive cleanup you're not authorized to do
(dropping databases, removing checked-in state), say so explicitly in your
final message — don't silently skip verification.

## Default fix preference order

When multiple fixes are plausible:

1. **Fix the root cause, not a symptom.** Raising a timeout, adding a retry,
   widening a wildcard — these usually hide bugs.
2. **Prefer smaller diffs.** A one-line bind-address fix beats a 50-line
   refactor of the wait-for-port helper.
3. **Prefer upstream-compatible changes.** Don't fork config schemas,
   rename public fields, or rewrite interfaces if a targeted patch works.
4. **Make test-mode defaults obvious.** If a secret is missing for E2E,
   populate `.env` with a clearly-fake test value (`sk_test_e2e_placeholder`),
   not a real-looking one.

## Runtime dependencies should be prefetched, not downloaded mid-test

An E2E run should not trigger ad-hoc downloads of its own tooling. If a
test step tries to install a browser, SDK, emulator image, or container
image on first use, you have three problems: the download can silently
hang inside the agent sandbox (no TTY for prompts), it pollutes per-user
caches with non-reproducible artifacts, and it makes the first run of
every fresh machine much slower than subsequent runs.

When you diagnose a hang on `playwright install`, `flutter precache`,
`gcloud components install`, `docker pull`, or anything analogous,
**fix the packaging, not the test.** Declare the dependency as a flake
input, a devShell package, or a Docker image baked into the base layer.
The rule of thumb: if the user's first local run takes N seconds, a
fresh CI run should take roughly N seconds too — no surprise downloads.

## Do NOT use curl / wget / fetch as a substitute for E2E drivers

E2E validation means driving the real app through its real platform —
a browser, an Android emulator, an iOS simulator. Shell HTTP clients
are acceptable only for:

- Pre-flight checks on backend services (`curl -sf
  http://127.0.0.1:3000/health`).
- Reading a raw API response to cross-check what the UI displayed.

They are never a substitute for a click, a form submit, or a
navigation. If MCP tools aren't working, write a finding and stop — do
not curl the backend and claim the flow is validated.

## What NOT to do

- Do not write `BLOCKED.md`, `DEFER-*.md`, or any file that asks the user
  to intervene. The runner decides when to give up.
- Do not disable tests, mark them `.skip`, or delete assertions to make
  the pipeline green.
- Do not modify the `specs/` directory or mark tasks complete.
- Do not add long sleeps (`sleep 30`) to paper over a race.
- Do not commit generated `.env` files with real secrets — use obvious
  test placeholders.
- Do not expand scope: if the bug is in setup.sh, don't also refactor the
  API config loader "while you're here."

## Finishing

Your final message should be short and structured:

```
## Root cause
One paragraph.

## Fix
What you changed (files + one-line summary each).

## Verification
How you confirmed it works (command you ran + the exit 0 evidence).

## Residual risk
Anything that might still fail, or that you couldn't verify.
```

The runner reads this to decide whether to re-attempt and to seed the
next fix-agent if you didn't fully solve it.
