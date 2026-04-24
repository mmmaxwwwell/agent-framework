# Fix-Agent Playbook

General debugging heuristics for agents spawned to repair a specific failure.
These are not task-specific — they apply to every fix-agent, every time.
They exist because cold-start agents default to "explore the repo and guess,"
which burns tokens and often fixes the wrong thing.

## Read the MCP launch probe first (platform-init failures only)

When the runner spawns you for a `platform_init_fail`, the diagnostic block starts with a section labeled `## MCP launch probe:` with one of four outcomes:

- **✅ launched and responded to initialize** — the MCP server itself is fine, and the runner confirms this by omitting the setup.sh / service-log / port / pid-file sections from the diagnostic entirely. Do **not** go looking for service-health issues: services are up. The failure is at the runtime layer — the emulator/browser/simulator binary is reachable but misbehaving. Work the "Runtime-layer checks when the probe is green" section below *before* anything else.
- **⚠ launched but never responded** — the binary starts but doesn't complete the JSON-RPC handshake within 5s. Usually a placeholder binary, a protocol-version mismatch (server speaks an older MCP version), or a bug where the server wedges during `initialize`. Check the stderr block; if it's empty, run the binary yourself under the same shell and feed it an `initialize` request manually.
- **❌ crashed on launch** — this is the root cause. The stderr excerpt in the probe section *is* the error. Fix that; do not chase setup.sh, service logs, or pid files. Common culprits: `nix run` blocked by bwrap's read-only `/nix/store`, missing shared libraries, or a missing env var that the Claude CLI scrubs but the runner's parent shell had.
- **⚠ no-config** — the runner never reached `start_mcp_server`, meaning the failure was earlier in the boot path (setup.sh or emulator boot). Treat like a non-MCP failure and work the service logs.

The probe is a *lazy re-launch*: the runner re-runs the MCP binary under the same sandbox constraints as the Claude CLI at diagnostic-build time. That makes its stderr authoritative in a way that setup.sh logs are not — setup.sh reports "MCP did not boot" but has no visibility into *why*.

If the probe section contradicts any other section of the diagnostic (a matched pattern, a prior-attempt claim, etc.), **trust the probe**. The other sections are heuristics built from setup.sh's external view; the probe has the actual process stderr.

## Runtime-layer checks when the probe is green

When the probe is ✅ but `platform_init_fail` still fires, the failure is at the runtime layer — the emulator/browser/simulator CLI is reachable but misbehaving. The service stack is known-good; skip it. Work these checks in order:

1. **Read the PATH diagnostics at the top of the diagnostic.** The runner prints the resolved path for `start-emulator`, `emulator`, and `adb`, and flags any binary that has multiple matches in PATH. If a wrapper (e.g. `emulator-wrapper` from a devshell) is supposed to win but a raw SDK binary is first, that is almost certainly the bug — PATH shadowing makes `-list-avds` return empty and makes the runner conclude "not booted." Fix PATH ordering (`flake.nix` shellHook, direnv, `.envrc`, etc.) before anything else.

2. **Run the runtime CLI yourself and compare.** For Android: `emulator -list-avds`, `adb devices`, `adb -s emulator-5554 shell getprop sys.boot_completed`. For browser: `playwright --version`, `node -e 'require("playwright").chromium.launch().then(b=>b.close())'`. If the CLI hangs, errors, or returns empty where populated output is expected, that is the failure — not setup.sh.

3. **Compare with the wrapper, if there is one.** If the project ships a wrapper script (`emulator-wrapper`, `start-emulator`, etc.), run both the wrapper and the raw binary. Divergent output between them *is* the bug.

4. **Only after 1–3 come up empty**, consider races between "MCP responded" and "runner marks booted." These are rare; do not reach for them first.

The one mistake to avoid in this mode: treating the absence of service-log / pid-file sections as a gap to fill by hand. The runner omitted them on purpose because they are noise for this failure class. Don't shell out to read them yourself.

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

## Mtime check before claiming "STILL_BROKEN"

Before writing "fix didn't work" / `verify_status=still_broken` / re-filing the same infra blocker, run this check — it takes five seconds and catches the most common wrong answer:

```bash
# When did the fix commit land?
git log -1 --format=%ct HEAD
# When was each service started? (mtime of the service log)
stat -c '%Y  %n' .dev/e2e-state/*.log 2>/dev/null
```

If **any service log is older than the fix commit**, the running process predates the fix. You are debugging a ghost. The correct response is:

1. `test/e2e/teardown.sh` (or kill the stale pids manually)
2. `test/e2e/setup.sh` (cold restart with the fixed code)
3. Re-probe the behavior
4. Only then write your conclusion

The runner's `reset_e2e_services` does this automatically on the next iteration, but you may be called *inside* an iteration — don't trust service state you didn't start yourself.

The Kanix `supertokens-cdi-mismatch` incident was five spawns of wasted work because this check wasn't run: the fix landed, the fix agent verified with `signup → 200`, but the subsequent verify-executor agents probed the orphaned pre-fix supertokens process and wrote "still broken" five times in a row. Every spawn's service logs were older than the fix commit; nobody looked.

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

## Writing `verify.sh` (MANDATORY when closing an E2E bug)

When you close an E2E bug, also write
`specs/<feature>/validate/e2e/bugs/<BUG-ID>/verify.sh`. The runner
executes this script before deciding whether to spawn a verify agent.
A good `verify.sh` saves ~$12 per bug per iteration — see
`cost-guardrails.md` § "Scripted verify first".

**Contract**

- Runner invokes: `bash verify.sh`, cwd = project root.
- Runner sources `test/e2e/.state/env` before invoking (you can use
  `$API_URL`, `$ADMIN_COOKIE`, `$DATABASE_URL`, etc.).
- Runner enforces a 30 s timeout.

**Exit codes**

| Code | Meaning | Runner action |
|---|---|---|
| `0` | Verified fixed | Finding → `fixed`; runner writes evidence from stdout |
| `1` | Verified still broken | Finding → `verified_broken`; runner writes evidence |
| `2` | Inconclusive | Falls through to verify-agent spawn |
| other / timeout | Treated as inconclusive | Falls through to verify-agent spawn |

**Stdout format** (the runner parses the first 3 lines):

```
STATUS: FIXED | STILL_BROKEN
EVIDENCE: <one-line concrete delta — e.g. "POST /api/checkout returned 200 with order_id=ord_xxx">
COMMAND: <command(s) used to verify>
```

**Authoring tips**

- Reproduce `steps_to_reproduce` at the **lowest layer possible**. A
  UI flow becomes a curl call; a widget test becomes a `grep` of a
  build log; a crash becomes a `head -20` of a stderr capture.
- Keep it to shell + curl + jq + grep. If you need the UI, let the
  runner spawn a verify agent instead.
- Exit 2 (inconclusive) is legitimate when a bug genuinely can't be
  scripted — prefer it over a flaky `exit 0`.
- A `verify.sh` that always `exit 0`s lies. The runner can't
  distinguish "fix worked" from "author was lazy" — treat this as a
  correctness contract with future cycles.

## When you cannot apply the fix (out-of-scope target)

Sometimes the file that needs the change is **outside your writable scope**:
the most common case is that your sandbox bind-mounts the target as
read-only (e.g. you are a fix-agent running under bwrap and the bug is in
`parallel_runner.py` itself, or in a `/nix/store` artifact, or in another
repo mounted `--ro-bind`). Touching the file with `Edit` or `Write` fails
with `EROFS` / "permission denied" / "read-only file system."

**When this happens: STOP. Do not invent workarounds.** In particular do
NOT try to patch the target via `verify.sh`, a generated build step, a
runtime self-modification, an environment shim, or any other indirection.
Those workarounds either fail silently or land a fragile hack that the
next cycle has to unwind.

Instead, emit an **out-of-scope claim** in your final-message trailer and
end the turn. The runner reads this, writes a rich `BLOCKED.md` that
includes your proposed diff verbatim, and stops spawning fix-agents for
this bug. A human (or a host-side agent with write access to the target)
applies the patch.

```
<claim>
{
  "out_of_scope": true,
  "out_of_scope_reason": "parallel_runner.py is on a read-only bind mount inside the agent sandbox (EROFS on Edit); fix must be applied from the host",
  "target_path": "/home/max/git/agent-framework/.claude/skills/spec-kit/parallel_runner.py",
  "root_cause": "proc.stdin was manually close()d but proc.stdin was not nulled before proc.communicate(timeout=2), causing ValueError on the implicit flush inside communicate()",
  "proposed_diff": "--- a/.claude/skills/spec-kit/parallel_runner.py\n+++ b/.claude/skills/spec-kit/parallel_runner.py\n@@ -5811,6 +5811,7 @@\n                     proc.stdin.close()\n                 except OSError:\n                     pass\n+                proc.stdin = None\n                 try:\n                     leftover_out, leftover_err = proc.communicate(timeout=2)",
  "files_changed": [],
  "verified": false,
  "evidence": "attempted Edit on target path returned 'read-only file system'; /proc/mounts confirms target is bound with --ro-bind"
}
</claim>
```

**Rules for an out-of-scope claim:**

- `out_of_scope: true` is the trigger — the runner uses this field alone.
- `proposed_diff` MUST be a real unified diff that, applied with `patch -p1`
  at the repo root containing `target_path`, produces the fix. Not pseudo-code,
  not a prose description — a diff. Include 2–3 lines of context on either side.
- `target_path` is the absolute path of the file to edit, so the human/host
  agent knows where the diff lands even if they don't have the same cwd.
- `out_of_scope_reason` is one sentence naming the write barrier concretely
  (mount type, errno, path). "Cannot edit" is not enough — say *why*.
- `files_changed` is `[]` because you did not change anything. `verified: false`.
- Do NOT commit empty placeholder files, do NOT write a partial patch, do NOT
  attempt a verify.sh workaround. The point of escalation is that the loop
  stops trusting its own fix surface and asks for help.

**Signals you are in this situation** (any one is sufficient):

- `Edit` or `Write` returns an error mentioning `read-only`, `EROFS`, or
  "permission denied" on a path you expected to be writable.
- `/proc/mounts` (or `mount | grep <path>`) shows the target under `ro,` or
  a `--ro-bind` entry.
- The target is under `/nix/store/`, `/run/`, or any path that is a
  read-only bind in the current sandbox config.
- You just spent multiple turns writing a build step whose only purpose is
  to mutate a file the runner itself owns. That is the workaround smell;
  stop and emit the out-of-scope claim instead.

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

End with a `<claim>{...}</claim>` JSON trailer (see
`agent-file-schemas.md` IC-AGENT-016 for the normal-fix schema and the
out-of-scope variant documented above). The runner reads this to decide
whether to re-attempt, seed the next fix-agent, or escalate to a human
via `BLOCKED.md`.
