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

**This applies to every language and test suite in the project.** If a project uses Go on the host and Kotlin on Android, both need coverage. If it has a Python CLI and a Rust library, both need coverage. Do not skip a language just because it isn't listed in an example table.

### Setup requirements

During plan/implementation, configure coverage for **every test command** in the project:

1. **Identify all test suites** — look at every `make` target, `package.json` script, Gradle task, or CI step that runs tests. Each one needs coverage.
2. **Research the standard coverage tool** for that language/framework if you don't already know it. Every mainstream ecosystem has one (JaCoCo for JVM/Android, c8/istanbul for Node, coverage.py for Python, go tool cover for Go, cargo-llvm-cov for Rust, SimpleCov for Ruby, dotCover for C#, etc.).
3. **Wire coverage into the default test command** so it runs automatically — not as a separate step the developer has to remember. Coverage should be collected on every `make test` / `npm test` / `./gradlew test` / etc.

### Output requirements

Every coverage tool MUST produce **both** of these outputs:

1. **Terminal summary** — a human-readable coverage table printed to stdout so it appears in agent logs and the terminal. This is the primary feedback mechanism during implementation.
2. **File report** — a machine-readable coverage report written to `coverage/` (e.g., `coverage/coverage-summary.json`, `coverage/report.xml`, `coverage/lcov.info`). The specific format depends on the ecosystem, but it MUST be a file that agents and CI tools can read without parsing terminal output. Common formats: JSON summary, Cobertura XML, LCOV, JaCoCo XML.

The `coverage/` directory is the canonical location. Language-specific subdirectories are fine (e.g., `coverage/go/`, `coverage/android/`) when a project has multiple tech stacks.

### What agents must do

- **Plan phase**: for every language/framework in the project, choose the coverage tool, add it to dev dependencies, and wire it into the test command. Create a task for each tech stack that needs coverage — do not assume a single coverage task covers a multi-language project.
- **Implementation phase**: when writing tests, verify coverage output appears and that the file report is written to `coverage/`. If a test file is added but coverage doesn't increase for the corresponding source file, investigate — the test may not be exercising the code it claims to.
- **Validation phase**: coverage output is part of the test run. The validation agent reads both the terminal output and the file report to confirm coverage was collected. If coverage is missing for any test suite in the project, the validation agent must fix it before proceeding.

### .gitignore

Coverage output directories (`coverage/`, `.nyc_output/`, `htmlcov/`, `coverage.out`) are already listed in the SKILL.md `.gitignore` conditional entries — ensure they're added when coverage is configured.

## User-flow integration tests

Per-boundary integration tests (process spawn, protocol, database) catch interface mismatches. But the bugs that waste the most human time are **cross-boundary cascade failures** — where each boundary works in isolation but the chained user flow breaks. These are the bugs where the user clicks a button, ten things happen in sequence, and step 7 fails because step 3 produced output in a slightly wrong format, or step 5 needs a resource that step 2 was supposed to download but didn't cache properly.

**Every project MUST include user-flow integration tests that exercise the real end-to-end path a user would take.** These are not unit tests with mocks. They are not per-boundary integration tests. They are tests that simulate a complete user action and verify the final observable result.

### What user-flow tests cover

Map each primary user flow from the spec (functional requirements, user stories, or UI flows) to a test that:

1. **Starts from the user's entry point** — the CLI command, the button click, the API call, the voice command — whatever initiates the flow
2. **Exercises every system boundary in sequence** — process spawns, socket connections, model loading, file I/O, network calls, IPC messages — all real, none mocked
3. **Verifies the user-visible result** — the text that appears, the file that's written, the response that's returned, the state change that's observable

### How to design them

For each user flow in the spec:

1. **Identify the chain**: What happens when the user does X? List every system boundary crossed, in order. Example: "User clicks mic → extension spawns sidecar → sidecar creates socket → extension connects → extension sends config → sidecar loads VAD model → sidecar loads whisper model → sidecar loads wake word model → sidecar opens mic → sidecar detects speech → sidecar transcribes → sidecar sends transcript → extension receives transcript → extension delivers to target"
2. **Identify injectable seams**: Where can you provide deterministic input without mocking? Audio file instead of mic. Test fixture instead of network download. Local model instead of remote fetch. Pre-cached resources instead of first-run downloads. The goal is deterministic input, not fake boundaries.
3. **Identify the observable output**: What does the user see at the end? A transcript in a text field. A file on disk. An API response. A status bar change. Test for this.
4. **Write the test**: Wire the real system together with deterministic inputs and verify the observable output. The test should fail if ANY link in the chain breaks.

### Tech-stack-agnostic patterns

These patterns apply regardless of language, framework, or runtime:

**Pattern 1: Audio/media pipeline testing**
- Provide a pre-recorded fixture file instead of live capture (WAV, MP4, etc.)
- Exercise the full processing pipeline with the fixture
- Verify the output matches expected results (transcript text, detected objects, etc.)
- Test with multiple fixtures: valid input, silence, noise, edge-case formats

**Pattern 2: Process lifecycle testing**
- Spawn the real child process (not a stub — this is different from boundary tests)
- Connect via the real IPC mechanism (socket, pipe, HTTP)
- Send a real sequence of messages that represents a user flow
- Verify the process transitions through expected states and produces expected output
- Verify cleanup on shutdown (socket deleted, temp files removed, exit code correct)

**Pattern 3: Extension/plugin host testing**
- Use the host platform's test harness (VS Code Extension Test Host, browser test runners, IDE test frameworks)
- Activate the extension in a real host instance
- Trigger commands programmatically
- Verify UI state changes (status bar, notifications, output channels)
- If the extension has a backend process: verify the backend starts, connects, and responds

**Pattern 4: Multi-service flow testing**
- Start all services the user flow touches (database, cache, API server, worker)
- Execute the user action against the entry service
- Verify the action propagated correctly through all services
- Use polling/retry for async flows (not sleep — poll for the expected state with a timeout)

**Pattern 5: First-run / cold-start testing**
- Test the flow with NO cached state (empty cache dirs, no downloaded models, no saved config)
- Verify that first-run setup (model downloads, config creation, dependency installation) completes successfully
- Then test the flow AGAIN to verify cached state is used on subsequent runs
- This catches the class of bug where the system works after manual setup but fails on first use

**Pattern 6: Configuration change testing**
- Start with default config, verify the flow works
- Change a config value while the system is running
- Verify the system picks up the change without restart (if hot-reload is supported)
- Verify the changed behavior is correct

**Pattern 7: Packaging and distribution testing**
- Build the distributable artifact (VSIX, wheel, npm tarball, binary, container image)
- Install it into a CLEAN environment (not the dev environment — a fresh directory, a fresh venv, a different machine profile)
- Run the same user-flow tests against the INSTALLED artifact, not the source tree
- This catches: missing files in the package manifest, hardcoded dev paths, dependencies that exist in the dev environment but aren't declared, resource files that aren't bundled, native libraries that aren't linked
- Common failures: `.vscodeignore` / `.npmignore` / `MANIFEST.in` excluding files the runtime needs; `pyproject.toml` missing a dependency that was installed globally; child process spawning from the installed path where source files don't exist; venv/node_modules created in the installed location with different package versions than dev

**Pattern 8: Dependency compatibility testing**
- Pin exact versions of ML models, binary dependencies, and native libraries in the project (not just `>=` ranges)
- Test with the ACTUAL versions that will be used in production, not whatever happens to be cached in the dev environment
- Verify model file format compatibility: if a model file has versioned input/output schemas (ONNX input tensor names, TFLite ops, protobuf schemas), the test must load the model and verify the interface matches what the code expects
- Test library API surface: if the project depends on a library that has removed/renamed APIs across versions (e.g., `setuptools` removing `pkg_resources`, `numpy` deprecating `np.float`), write a smoke test that imports and calls the specific APIs used
- For projects with native extensions (C/C++/Rust via pip/npm): test on the target Python/Node version, not just the dev version. Wheels may not exist for all platform+version combinations.

**Pattern 9: Cross-application integration testing**
- When the project integrates with another application it doesn't control (IDE extensions talking to other extensions, plugins communicating with host apps, microservices calling third-party APIs), test the REAL integration path
- Identify what the target application actually exposes: public APIs, command IDs, IPC protocols, clipboard, file watchers. Document which ones work and which are sandboxed/blocked.
- Write a test that exercises the real delivery path — if clipboard is the only viable mechanism, test clipboard write + programmatic paste. If an API exists, test the API. If nothing works reliably, document the limitation and test up to the boundary.
- Don't assume OS-level input simulation (xdotool, wtype, AppleScript) works in all environments — display server differences (X11 vs Wayland vs macOS), sandbox restrictions, and compositor-specific behavior make this fragile. Test on the actual target platform.

### What makes these different from per-boundary tests

| Per-boundary integration test | User-flow integration test |
|-------------------------------|---------------------------|
| Tests ONE boundary (spawn, socket, API) | Tests the CHAIN of boundaries a user flow crosses |
| Fails if the boundary contract is wrong | Fails if ANY step in the chain is wrong |
| Uses stubs for adjacent systems | Uses real systems with deterministic inputs |
| Catches: "the protocol is wrong" | Catches: "the protocol works but the data from step 3 isn't what step 7 expects" |
| Fast, targeted, easy to debug | Slower, broader, catches cascade failures |

Both are needed. Per-boundary tests catch interface bugs quickly. User-flow tests catch the integration gaps that per-boundary tests miss.

### When to write them

- **Test infrastructure phase (Phase 1)**: Set up fixtures, test harnesses, and helper utilities needed by user-flow tests
- **Each feature phase**: After per-boundary tests pass, write user-flow tests for the user stories implemented in that phase
- **Late phase (end-to-end validation)**: Run ALL user-flow tests together to catch cross-feature interactions

### Failure debugging

When a user-flow test fails, the failure log MUST include:
- Which step in the chain failed (not just the final assertion)
- Logs/stderr from all processes involved in the flow
- The state of IPC messages exchanged (protocol messages sent/received)
- Timing information (to catch timeout/race conditions)

This is why structured test output matters — the fix-validate agent needs to see the chain, not just "expected X, got Y."

## E2E test harness requirements

E2E tests are the most infrastructure-heavy tests in a project. They fail most often not because of code bugs but because of missing infrastructure: an APK that wasn't built, an emulator that wasn't configured, a UI interaction that can't be automated. Every E2E test MUST have its prerequisites decomposed into separate, independently testable tasks.

### The harness decomposition rule

Never combine "set up the test environment" and "write the test" in a single task. Instead:

1. **Artifact build task** — build whatever the E2E test installs (binary, APK, container image, VSIX). This task should produce a verified artifact: installable, runnable, `--help` works.

2. **Environment setup task** — create the test environment (emulator, VM, sandbox, containers). This task should produce a verified environment: boots, accepts connections, tools are available. For flaky environments (Android emulator, browser automation), include timeout + retry in the setup script itself.

3. **Test bypass tasks** — for features that can't be automated in the test environment (camera scanning, biometrics, NFC, Bluetooth, GPS), create a test-mode bypass. Examples:
   - Deep link or intent that accepts the same data the camera scanner would produce
   - Mock biometric provider that auto-succeeds
   - Test GPS location provider
   - File-based input instead of hardware capture
   These MUST be separate tasks because they require changes to the app code (conditional test-mode paths), not just test code.

4. **UI automation helper task** — if the E2E test drives a UI, create a reusable helper library with named methods for each user action. Each method should include its own wait + retry logic. This prevents the E2E test from being a fragile wall of raw selectors and clicks.

5. **The E2E test itself** — uses all of the above. By this point, every prerequisite is proven working. The test focuses on the business logic flow, not infrastructure setup.

### CI-specific harness requirements

When E2E tests run in CI, they need additional infrastructure that local tests don't:

- **Structured test output upload** — `test-logs/` directory uploaded as workflow artifact on failure (not just stdout). This is the link between the structured test reporter (Phase 1) and the fix-validate loop in CI.
- **CI failure summary** — a machine-readable `ci-summary.json` with per-job pass/fail and failure names. Fix-validate agents read this instead of parsing raw workflow logs.
- **Retry wrapper** — E2E tests in CI get 2-3 attempts with cooldown between them. One flaky failure shouldn't fail the pipeline or waste a fix-validate iteration.
- **Timeout budget** — explicit per-attempt and total timeouts. If an emulator boot takes 120s, the E2E test gets 120s + test time, not a default 10-minute CI timeout.

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
