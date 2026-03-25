# Integration Testing Requirements

Every spec-kit project MUST include comprehensive integration tests that validate all user flows end-to-end. This is non-negotiable — without working tests, the autonomous fix-validate loop that powers implementation is blind.

## Philosophy: real servers, real processes, no mocks at system boundaries

Tests MUST exercise the real system wherever possible. The hierarchy of preference:

1. **Real server implementations** — spin up the actual server, hit real endpoints, verify real responses. For protocols like SSH, use a real SSH server (e.g., Node.js `ssh2` library with test keypairs) rather than mocking the protocol.
2. **Real processes** — if the feature spawns child processes, test with real child processes. If it reads files, use real temp directories with real files.
3. **Mock only what requires human interaction** — biometric prompts, hardware tokens, manual UI actions. Everything else should be real.
4. **Never mock internal boundaries** — don't mock the database, don't mock service-to-service calls within the same process. Integration tests exist precisely to catch the bugs that unit tests with mocks miss.
5. **Dev/prod parity** — use the same backing services in development, testing, and production. Never use SQLite in dev when production runs PostgreSQL. Never use an in-memory cache in tests when production uses Redis. Differences between environments are where bugs hide — code that passes tests in dev fails in production because the backing service behaves differently. Nix flakes make running production-equivalent services locally trivial and reproducible — pin exact versions in `flake.nix` so every developer and CI runner uses identical toolchains. When Nix is available, prefer it over Docker for dev environment parity.

## External process boundary testing

When the system spawns external processes (CLI tools, agents, workers, scripts), integration tests MUST verify the **actual process interface** — not just that the command was constructed correctly, and not just that the internal wiring passes data around. The test must prove that:

1. **The spawned process actually starts and runs** — use a lightweight stub binary/script that accepts the same flags and protocols as the real tool (e.g., a shell script that accepts `--input-format stream-json --output-format stream-json` and echoes back structured responses). This catches flag mismatches, missing arguments, and incorrect stdin/stdout formats that unit tests on the command builder will never find.
2. **Stdin/stdout protocols are exercised end-to-end** — if the system writes JSON to a process's stdin and reads JSON from its stdout, the integration test must send real messages through the real pipe and verify real responses come back. Testing that "stdin.write was called" is a unit test; testing that "the process received the message and responded correctly" is an integration test.
3. **The contract between builder and consumer is verified** — if one module builds the command args and another module reads the process output, the integration test must connect them through an actual process spawn. This catches the class of bug where both sides are internally correct but incompatible with each other.

**Stub process pattern**: Create a minimal test harness script (e.g., `tests/fixtures/mock-claude.sh`) that accepts the same CLI flags as the real tool and implements just enough of the protocol to validate the interface. The stub should:
- Parse and validate the flags it receives (reject unknown flags)
- Accept input in the expected format (stream-json, text, etc.)
- Produce output in the expected format
- Exit with appropriate codes

This is NOT the same as mocking — the stub runs as a real child process with real pipes, exercising the full spawn → stdin → stdout → exit lifecycle.

## Structured test output for agent-readable failure logs

The fix-validate loop depends on **structured, machine-readable test output**. Without it, the implementing agent can't diagnose failures efficiently. Every project MUST implement:

1. **Test log directory**: `test-logs/<type>/<timestamp>/` (gitignored)
2. **`summary.json`** per run: `{ pass: number, fail: number, skip: number, duration: number, failures: string[] }`
3. **`failures/<test-name>.log`** per failing test: assertion details (expected vs actual), full stack trace, and relevant context (server logs, captured stderr, request/response bodies)
4. **Passing tests**: one-line summary only (name + duration) — don't clutter output
5. **Custom test reporter**: use the test runner's reporter API (Node.js native test runner custom reporter, JUnit RunListener, pytest plugin, etc.) to produce this format

Example `summary.json`:
```json
{
  "pass": 42,
  "fail": 2,
  "skip": 1,
  "duration": 12340,
  "failures": [
    "session-lifecycle: start → blocked → resume",
    "ssh-bridge: sign request timeout"
  ]
}
```

Example failure log (`failures/ssh-bridge-sign-request-timeout.log`):
```
TEST: ssh-bridge: sign request timeout
FILE: tests/integration/ssh-agent-bridge.test.ts:142

ASSERTION: Expected session state to be "failed" after 60s timeout
  Expected: "failed"
  Actual:   "running"

STACK:
  at Object.<anonymous> (tests/integration/ssh-agent-bridge.test.ts:158:5)
  at async TestContext.run (node:internal/test_runner:123:9)

CONTEXT:
  Server log: [14:23:01] SSH bridge socket created at /tmp/test-abc123/agent.sock
  Server log: [14:23:01] Sign request forwarded, waiting for client response
  Server log: [14:24:01] Timeout — no client response after 60000ms
  Request: { requestId: "req-1", messageType: 13, data: "AAAA..." }
```

## Code coverage collection

Every test run MUST collect and report code coverage. Coverage is not optional — it's how the fix-validate loop confirms that new code is actually exercised by tests, not just present.

### Setup requirements

During plan/implementation, configure the project's test command to collect coverage automatically:

| Language | Tool | Command pattern |
|----------|------|-----------------|
| Node.js (native test runner) | `c8` | `c8 --reporter=text --reporter=json node --test` |
| Node.js (Vitest) | Built-in | `vitest run --coverage` (uses `@vitest/coverage-v8` or `@vitest/coverage-istanbul`) |
| Node.js (Jest) | Built-in | `jest --coverage` |
| Python (pytest) | `pytest-cov` | `pytest --cov=src --cov-report=term --cov-report=json` |
| Go | Built-in | `go test -coverprofile=coverage.out ./...` |
| Rust | `cargo-llvm-cov` | `cargo llvm-cov --json` |

### Output requirements

1. **Terminal summary** — always print a human-readable coverage table to stdout so it appears in agent logs and the terminal. This is the primary feedback mechanism.
2. **JSON report** — write a machine-readable coverage report to `coverage/coverage-summary.json` (or language equivalent) so downstream tools can parse it.
3. **The test command in `CLAUDE.md` and `package.json` (or equivalent) MUST include coverage flags** — coverage should be collected on every `npm test` / `pytest` / etc., not require a separate command.

### What agents must do

- **Plan phase**: choose the coverage tool and add it to dev dependencies. Add the coverage command to the project's test script.
- **Implementation phase**: when writing tests, verify coverage output appears. If a test file is added but coverage doesn't increase for the corresponding source file, investigate — the test may not be exercising the code it claims to.
- **Validation phase**: coverage output is part of the test run. The validation agent reads the terminal output to confirm coverage was collected. If the coverage command is missing or broken, the validation agent must fix it before proceeding.

### .gitignore

Coverage output directories (`coverage/`, `.nyc_output/`, `htmlcov/`, `coverage.out`) are already listed in the SKILL.md `.gitignore` conditional entries — ensure they're added when coverage is configured.

## How the fix-validate loop works at runtime

The loop operates at **phase boundaries**, not per-task. It's a **disk-based state machine** driven by the task runner:

1. Agents implement tasks T007, T008, T009 (all in Phase 3). Each agent marks its task done and commits.
2. The agent completing the **last task in Phase 3** runs the project's test suite.
3. Validation fails → agent writes failure state to `specs/<feature>/validate/phase3/1.md` (command, exit code, structured test output from `test-logs/`, list of tasks completed in this phase)
4. Agent appends `- [ ] phase3-fix1 Fix phase validation failure: read validate/phase3/ for failure history` to `tasks.md` at the end of Phase 3
5. **Next runner iteration** picks up `phase3-fix1` with fresh context — reads the full failure history from `validate/phase3/`, reads `test-logs/`, diagnoses and fixes across all files touched by the phase
6. The fix agent re-runs validation. If it still fails → writes `validate/phase3/2.md`, appends `phase3-fix2`
7. After 10 failed fix attempts → writes `BLOCKED.md` and the runner stops

Key properties:
- **Validation is per-phase, not per-task** — avoids wasting runs on intermediate states
- **Each fix gets a fresh agent** with full context budget — no degradation from prior attempts
- **Failure history accumulates on disk** in `validate/<phase>/` — nothing is lost between runs
- **Tests are the spec** — fix the code, not the tests (unless a test is genuinely wrong)
- **Structured test output** (`test-logs/summary.json` + `test-logs/<type>/<timestamp>/failures/`) is the primary feedback mechanism
