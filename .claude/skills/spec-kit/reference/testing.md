# Integration Testing Requirements

Every spec-kit project MUST include comprehensive integration tests that validate all user flows end-to-end. This is non-negotiable — without working tests, the autonomous fix-validate loop that powers implementation is blind.

## Test tier taxonomy (READ THIS FIRST)

Three tiers, strict boundaries. Writing a test at the wrong tier is a common failure that wastes validation cycles and hides bugs. Use this table when deciding where a new test goes.

| Tier | What it tests | What it runs against | Infrastructure | File convention | Runs when |
|---|---|---|---|---|---|
| **Unit** | A single function, class, or module in isolation | In-process only — no network, no DB, no services. Pure logic. | None beyond the language runtime. | `*.test.ts` / `*_test.go` / etc. | Every build / pre-commit / CI |
| **Integration** | A complete app-layer flow end-to-end *inside one process boundary* (e.g. HTTP request → handler → real DB → real auth → response) | Live services — real Postgres, real auth server, real API — brought up by the project's service harness (`test/e2e/setup.sh` or equivalent) | Service stack (DB, auth, API) — **NOT** the mobile emulator, browser, or UI runtime | `*.integration.test.ts` / `*_integration_test.go` / etc. | Every build, with service stack live. Gates the E2E tier. |
| **E2E** | The *user-visible* behavior across runtime boundaries (mobile app → API → DB; browser → API → DB). Driven via MCP / Playwright / Patrol. | Full stack *plus* the platform runtime (Android emulator, iOS simulator, browser) | Everything integration needs **plus** the runtime | `*.e2e.test.ts` / `test/e2e/*.ts` / etc. | Only after integration tier is green (see "Pre-E2E gate" below) |

### Key rules that follow from the taxonomy

1. **Integration tests never touch the emulator / simulator / browser.** If a test needs to drive UI, it's E2E, not integration. Put it under `test/e2e/` or `*.e2e.test.ts`.
2. **E2E tests never substitute for integration tests.** An MCP-driven test exercising the login flow through the app does not count as coverage for the `/auth/signin` endpoint — write the integration test too. E2E is ~100× slower to diagnose; integration catches the same bugs ~100× faster.
3. **Unit tests never substitute for integration tests.** A unit test with a mock DB verifies that your code *calls* the DB correctly; it doesn't verify that the *query actually works* against real Postgres. Cross-boundary bugs (schema mismatch, transaction isolation, query plan errors) are invisible to unit tests.
4. **No mocking inside a tier's boundary.** Integration tests don't mock the DB or the auth server — those are *inside* the integration tier boundary. Unit tests don't mock internal modules — those are *inside* the unit tier boundary. Mocks are only appropriate at the boundary of the tier itself (e.g. a unit test may mock a third-party HTTP client; an integration test may stub a third-party SaaS API that costs money per call).
5. **File-name convention is load-bearing.** The runner uses it to decide which tier to run when. `*.integration.test.ts` runs in the pre-E2E gate (needs live services). Pure unit `*.test.ts` runs in the implement-phase validator. Miscategorizing files breaks the gate.
6. **Tests that can't run in the standard environment go in their own tier.** If a test genuinely requires something the project can't auto-provision (paid third-party API, hardware security key), put it in a separate file pattern (`*.external.test.ts`) and exclude it from the default test run via `include`/`exclude` config — **not** via runtime skip guards. See "Zero-skips rule" below.
7. **Every E2E flow has a user-flow integration-test mirror.** For every task in the E2E tier (`[needs: e2e-loop]` tasks), there MUST be a corresponding user-flow integration test under `src/flows/<flow-name>.integration.test.ts` (or equivalent) that walks the same multi-step business flow via direct API calls. Same flow the E2E drives through the UI, same steps, same assertions on final state — just without the emulator/browser. These mirror tests are faster (seconds vs minutes), they are the first place to look when the E2E fails (the mirror tells you whether the bug is in the API layer or past it), and they close the gap where an E2E passes but the underlying flow has a subtle bug only a multi-step integration test would catch. When generating the task list during the `tasks` phase, every E2E task description SHOULD be paired with a `flows/*` integration-test task that precedes it.
8. **Integration-tier *tasks* run sequentially, but integration-tier *tests* usually run concurrently.** Integration tests share one live service stack (DB, auth, message bus, cache — brought up once by `test/e2e/setup.sh` or equivalent); task scheduling keeps implementation work serial so fixture authorship doesn't collide. But the test *runner* (vitest `pool: forks`, `pytest-xdist`, `go test` per-package, `cargo test` threads, JUnit parallel) will execute the resulting test files across concurrent workers against that one shared stack by default. This is the condition that creates shared-runtime hazards — two workers writing to the same DB in the same millisecond — and it is the norm, not the exception. Never mark an integration-test *task* with `[P]` (authorship is serial), but assume the *tests you write* will be run concurrently with every sibling file (authoring must be concurrency-safe). See "Shared-runtime authoring rules" below for the mandatory authoring constraints, and "Shared-runtime review checks" for the review-time enforcement.

### Pre-E2E gate

Before any `[needs: e2e-loop]` task's MCP crawl, the runner automatically:

1. Brings up the backend service stack via `test/e2e/setup.sh`. Setup.sh MUST write `test/e2e/.state/env.sh` with `export` statements for every var the tests need (`DATABASE_URL`, `SUPERTOKENS_CONNECTION_URI`, etc.); the gate sources this file before running tests. See `reference/mcp-e2e.md` § "Backend service connection info" for the file format.
2. If setup fails, spawns a dedicated **services-fix agent** (independent budget, scoped to infra files — `setup.sh`, `flake.nix`, config files, version pins; NOT app code) that retries until the stack is healthy.
3. Runs the project's integration test command (discovered from `package.json`, `Makefile`, etc.) against the live services, with `env.sh` sourced into the test subprocess.
4. On test failure or skip, synthesizes INFRA findings and spawns an **integration-test fix agent** that edits app code or test code to resolve them. The loop keeps going as long as each round makes progress (reduces open-bug count OR changes the failure shape).
5. **Escalation ladder on stall:** `regular fix agent → meta-fix agent (structural redesign) → BLOCKED.md`. Same shape as the platform-init loop. The meta-fix agent gets the full gate log, `setup.sh` source, prior claims, and is told to attack the structural cause — not the surface symptom.
6. Only after the gate is green does the emulator boot, the APK build, and the MCP crawl start.

This means an agent whose tests pass at the integration tier gets fast feedback. An agent whose tests fail at the integration tier never burns emulator minutes discovering the same bug. An agent who wrote their integration test with a skip guard, or put it at the wrong tier, will trip the gate immediately rather than having it discovered by a downstream E2E.

**Corollary: integration-tier coverage is how you get E2E to run.** If the integration tier doesn't exercise the feature, the E2E gate can't verify its preconditions, and the feature never gets to the crawl. Agents who try to skip straight to E2E will be blocked by the gate.

### Structural causes to investigate when the integration-test fix loop stalls

When the regular fix agent has tried multiple rounds without making the gate green, the meta-fix agent is invoked with a broader charter. The common structural causes — the ones the regular fix agent chronically misses because they're one layer up from the immediate error — are:

1. **Env propagation gap between setup.sh and the test subprocess.** `setup.sh` exports `DATABASE_URL` into its own shell; that shell exits; the runner spawns `pnpm test` with an environment that doesn't have the var; every test fails with "X is required." Fix: write `test/e2e/.state/env.sh` and let the runner source it. This is the #1 cause of new-project stalls.
2. **Service version vs client library version mismatch.** The library speaks protocol N+1; the service speaks N. Bump the service pin in `scripts/<service>-setup.sh` / `flake.nix` or downgrade the library in `package.json`.
3. **Wrong tier placement.** A file under `*.integration.test.ts` actually requires a UI runtime / emulator / paid external API. Move it to `*.e2e.test.ts` / `*.external.test.ts` / a separate `include` pattern.
4. **Test helper reading from the wrong source.** `requireDatabaseUrl()` reads `process.env["DATABASE_URL"]`, but the runner passes it as a config object or `.env` file. Align the two sides.
5. **Stale cached state.** Liquibase migration history doesn't match the DB; `.dev/pgdata/` has schema from an older run; `runner-verified.json` carries false green; `findings.json` has entries for bugs that no longer exist. Clearing the specific cache is a valid fix when justified.
6. **Schema drift between app version and DB state.** Fresh `api/src/db/schema/*.ts` adds a column that the migration in `api/migrations/*.xml` forgot. Add the missing changelog OR re-seed the DB.
7. **Services running but the API they serve is broken.** Postgres + SuperTokens are both healthy, but the API fails to boot because of a TypeScript compile error, missing env var, or missing dependency. Symptom looks like "integration tests can't connect"; root cause is the API process, not the service stack. Check `test/e2e/.state/api.log` for the API startup error.
8. **Port conflict from a prior run.** A ghost process holds port 3000 / 3567 / 5432; setup.sh's idempotent start thinks the port is "in use, probably mine" and skips, but the ghost is from a crashed prior session. Fix: `teardown.sh` must kill on port, not just on PID file.

The meta-fix agent should state ONE structural hypothesis, apply ONE fix, and verify by running the failing test command manually. Chasing multiple hypotheses in parallel is exactly what the regular fix agent was doing — that approach is what the meta-fix is escalating *away* from.

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

The fix-validate loop depends on **structured, machine-readable test output**. Without it, the implementing agent can't diagnose failures efficiently.

> **Canonical schema and reference reporters live in [`templates/`](templates/).**
> Do NOT invent a new schema. Drop in the template that matches your test runner
> and customise the `RUN_TYPE` — don't fork the schema.
>
> - **Schema contract (read first):** [`templates/EXAMPLE-OUTPUT.md`](templates/EXAMPLE-OUTPUT.md)
> - **Vitest (Node/TS):** [`templates/test-reporter-vitest.ts`](templates/test-reporter-vitest.ts)
> - **pytest (Python):** [`templates/test-reporter-pytest.py`](templates/test-reporter-pytest.py)
> - **Go:** [`templates/test-reporter-go.go`](templates/test-reporter-go.go)
>
> Agents diagnosing failures read `test-logs/summary.json` (the schema) and
> the pointed-to `failures/<name>.log` files. They do NOT parse raw stdout,
> and they do NOT read reporter source to learn the schema — the example
> output is the contract.

Every project MUST implement:

1. **Test log directory**: `test-logs/<type>/<timestamp>/` (gitignored), plus a latest pointer at `test-logs/summary.json`
2. **`summary.json`** per run with the canonical schema (see [`templates/EXAMPLE-OUTPUT.md`](templates/EXAMPLE-OUTPUT.md)): `{ timestamp, duration_ms, type, pass, fail, skip, total, command, failures: string[], results: object[] }`
3. **`failures/<test-name>.log`** per failing test: assertion details (expected vs actual), full stack trace, and relevant context (server logs, captured stderr, request/response bodies). Filename sanitization rules in EXAMPLE-OUTPUT.md.
4. **Passing tests**: one-line summary only (name + duration) — don't clutter output
5. **Custom test reporter**: use the drop-in template for your runner. If your runner isn't covered, follow the schema contract in EXAMPLE-OUTPUT.md exactly.
6. **Non-vacuous assertion**: after producing `summary.json`, the test harness or CI step MUST verify that `pass + fail > 0`. A summary reporting 0 passed / 0 failed means tests didn't run — this MUST be treated as a failure, not a pass. See `reference/cicd.md` § "Non-vacuous CI validation" for the CI-level enforcement pattern.
7. **Skip-as-failure assertion**: a test run that contains any skipped tests MUST be treated as a failure, not a pass. Skipped tests mean the environment is broken or a dependency is missing — the test suite is giving false confidence. If a test genuinely cannot run on a platform (e.g., iOS tests on Linux), it should not be included in the test list for that platform at all — use conditional test registration, not runtime skips. The test harness MUST enforce this: if `skip > 0`, the run fails. See `reference/cicd.md` § "Skip-as-failure CI validation" for the CI-level enforcement pattern.

### Zero-skips rule (MANDATORY — no exceptions, no opt-outs)

**If a test did not run, it is a skip. Skips fail the build. There is no escape hatch.**

The harness MUST have **one mode only**: skips fail. There is no "strict mode" flag, no `--allow-skips`, no env var that loosens the rule in dev. A reporter that only fails on skips when a flag is set is the same loophole as not having the rule — agents disable the flag and the silent-skip returns.

**Banned patterns (non-exhaustive):**

| Banned | Why it fails the rule |
|---|---|
| `describe.skip(...)` / `it.skip(...)` in source that ships | Test is unreachable at runtime — silent skip |
| `const canRun = X; const d = canRun ? describe : describe.skip` | Conditional runtime skip — exactly what the rule forbids |
| `async beforeAll() { if (!await svcUp()) return; }` | Setup bails silently; the `it()` blocks run against an uninitialized fixture and pass vacuously (or skip) |
| `if (!flag) return;` at the top of every `it()` | Body never executes; test reports pass with no assertions |
| `try { ...setup... } catch { /* log and return */ }` in beforeAll | Setup failure is swallowed; tests that follow pass vacuously |
| `t.Skip("requires GPU")` in committed code | Runtime skip; see CI rule |
| `@pytest.mark.skipif(cond, ...)` | Same class of loophole; remove the condition |
| `STRICT_TEST_MODE`-style flags that gate skip enforcement | The permissive mode is the problem. Delete the flag, make strict the only mode. |

**Correct pattern — fail-fast asserts in setup:**

```ts
beforeAll(async () => {
  // Throw instead of skip. Loud failure. No silent pass.
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL required; start services with `process-compose up`");
  if (!(await fetch("http://localhost:3567/hello")).ok) {
    throw new Error("SuperTokens must be running on :3567");
  }
  // ... real setup ...
});
```

If a test would have been skipped for a missing service, the fix is to **make the service available** (start it in the harness, add it to the dev environment, provision test credentials) — not to gate the test.

**Platform gap, not runtime skip:** If a test physically cannot run in a given environment (iOS tests on Linux, emulator-only Android tests on PR runners), it must be excluded at test-list-building time, not skipped at runtime. Options:

- Separate file pattern (e.g. `*.integration.test.ts` vs `*.ios.test.ts`) with different `vitest --include` / CI matrix
- Separate test script (`pnpm test` vs `pnpm test:ios`)
- Build-time feature flags that omit the test source entirely from the target environment's build

The distinction: a test that's **absent from the test list** isn't a skip. A test that's **in the list but didn't execute** is a skip and fails the build.

**Runner-enforced:** The spec-kit runner sets `skip > 0` to a phase-validation FAIL regardless of what the reporter says. Even if a project's harness gets a permissive mode smuggled back in, the runner refuses to accept skips. A test that depends on a live service must cause a loud failure when the service isn't reachable — not a silent pass.

Minimal `summary.json` (canonical schema — see [`templates/EXAMPLE-OUTPUT.md`](templates/EXAMPLE-OUTPUT.md) for the full schema with `results[]`):
```json
{
  "timestamp": "2026-04-20T14:03:17.412Z",
  "duration_ms": 12340,
  "type": "integration",
  "pass": 42,
  "fail": 2,
  "skip": 1,
  "total": 45,
  "command": "pnpm test",
  "failures": [
    "session-lifecycle: start → blocked → resume",
    "ssh-bridge: sign request timeout"
  ],
  "results": []
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

## Shared-runtime authoring rules (MANDATORY — applies to every integration and E2E test)

Your test is one of hundreds sharing one live service stack (DB, auth, message bus, cache, filesystem, object store). The runner — whatever it is — will execute test files across concurrent workers by default. **Assume concurrent writers, assume arbitrary prior state, assume arbitrary test ordering.**

Any value you hardcode is a collision waiting to happen. Any global state you read is a time-of-check-to-time-of-use race. Any cleanup that isn't scoped to identifiers *this test created* is sabotage of sibling tests. These are not theoretical concerns — they are the dominant cause of flaky-integration-test incidents, and they cost the fix-validate loop multiple cycles per collision because the failure symptom (unique-constraint violation, FK violation, off-by-N count, 404 on a deleted fixture) never points at the real author-time mistake.

The rules below are language-agnostic. Every mainstream ecosystem has equivalents for each pattern. Apply them whether your stack is Postgres + Kafka + S3, MySQL + RabbitMQ + Redis, DynamoDB + SQS, or anything else.

1. **Never hardcode a value that participates in a uniqueness or identity constraint.** Generate it at test time. This applies to: row primary keys, foreign-key sentinels, user emails, usernames, slugs, SKUs, order numbers, tenant IDs, queue names, topic names, exchange names, stream names, bucket keys, object prefixes, filesystem paths, container names, DNS labels, TLS SNI hosts — anything the system enforces uniqueness on. A hardcoded `"test@example.com"` in file A collides with the same literal in file B the first time both run in the same session. A hardcoded `"KNX-001"` order number is indistinguishable from a sibling file's order in any assertion that matches on that string. The correct form is a cryptographically-random suffix: `` `user-${randomUUID()}@example.com` ``, `` `orders-${uuid}` ``, `` `/tmp/emails-${uuid}.jsonl` ``. Any time the value appears twice in the repo, assume collision.

2. **Randomness must have enough entropy to survive concurrent workers.** Wall-clock timestamps (`Date.now()` in ms, `time.time_ns()` where two workers can sample within one tick, `System.currentTimeMillis()`) collide when two workers enter the same generator in the same tick. Per-process counters collide across processes. Use a CSPRNG-backed UUID/ULID, or a hash of process-id + monotonic-counter + random — whatever your ecosystem's standard unique-ID primitive is. A `Date.now()`-suffixed fixture is not safe under parallelism; it is safer than a hardcoded literal but is not correct.

3. **Never read "the first row" or "any existing" from a resource you share.** Patterns like `rows[0]`, `SELECT ... LIMIT 1` without a predicate you control, `fs.readdir(shared_dir)[0]`, `list_objects(bucket)[0]`, `kafka.list_topics()[0]` — all of these return whatever a sibling test happened to create most recently. If that sibling's cleanup runs between your read and your use, you hold a stale ID and your next insert/read fails with a FK violation or 404. Always either (a) insert your own fixture in setup and reference its ID, or (b) filter by a property only this test sets (`WHERE test_run_id = <my-uuid>`), never by position or insertion order.

4. **Scope cleanup to identifiers this test created.** In every `afterAll`/`afterEach`/`tearDown`/`t.Cleanup(...)`/equivalent, delete/drop/evict only the IDs you captured during setup. Maintain a list (`createdOrderIds`, `createdTopicNames`, `createdS3Keys`) and iterate that list. Never delete by type, status, time window, name prefix, event kind, or any other predicate that can match rows a sibling test is actively using. A broad cleanup like `DELETE FROM events WHERE event_type IN ('order.placed', 'payment.succeeded')` or `rm /tmp/test-*` destroys in-flight data for every test running concurrently.

5. **Filter every assertion by an identifier you own.** Never count, list-length, or aggregate against an unscoped query. `SELECT COUNT(*) FROM orders` is unsafe; `SELECT COUNT(*) FROM orders WHERE contributor_id = $testContributorId` is safe. The same applies to `list.length`, `len(results)`, `rows.size()`, message-queue depth, object count. If you can't name the ID your test owns that makes the result deterministic, you don't have a deterministic assertion — you have a flake.

6. **Prefer `>= baseline + N` to `== baseline + N` on any metric you don't exclusively own.** Exact-equality deltas on counters, aggregates, or global metrics break whenever a sibling test moves the counter between your baseline capture and your action. If the metric is genuinely global (system-wide event count, total orders today, queue depth across all tenants), use `>=`. If the metric is scoped to an ID this test created, exact equality is fine — but double-check the scope.

7. **Each test case must be self-contained.** Any single test case (`it(...)`, `test(...)`, `func TestX(t *testing.T)`, `def test_x`, `@Test`) must pass when run alone. Cross-case state dependencies — "test B only works if test A ran first and left the salesCount at 3" — break under test filtering (`--only`, `-run`, `-k`, `-t`), random ordering, re-runs, fail-fast mode, and any future parallelization of cases within a file. Lift shared setup into `beforeAll`/fixture/`setUpClass`, or have each case bring its state to the required value from scratch. If you catch yourself writing "the previous test left us at…," stop and refactor.

8. **Never assume seed data, default singletons, or migration-provided rows exist in a specific shape.** Do not hardcode the ID of "the admin role," "the default tenant," "the system user," or any row that a migration/seed creates. Look it up by a stable property (name, tag, slug you control) and use the returned ID. Migrations change; seed data changes; running the tests against a freshly-migrated DB vs. a re-used DB must produce the same result.

9. **Shared external resources need per-test namespacing, same as DB rows.** Filesystem paths, message-queue topics/queues, cache key prefixes, DNS records, object-store prefixes, container/pod names, temporary TLS hostnames, socket paths, named pipes — every shared resource needs a test-owned suffix. A hardcoded `/tmp/emails.log` or `topic: "orders"` or `redis_key: "cart:session"` is the same hazard as a hardcoded primary key, just on a different substrate. Generate a per-test namespace in setup and feed it into whatever code-under-test needs it (via config, env var, constructor arg, whatever seam exists).

10. **Account for the runner's concurrency model when you author.** Read the runner config (`vitest.config.*`, `pytest.ini`/`conftest.py`, `go test` defaults, `Cargo.toml`, JUnit parallel settings, build-tool parallelism) and know three things: (a) does it parallelize across files, (b) does it parallelize across cases within a file, (c) what's the default worker count. Write for the strictest model the project could ever enable — if parallelism is currently off but the runner supports it, the project will turn it on the moment test time becomes painful, and your serial-assuming tests will start failing that day. Treat "works only in serial" as a latent bug.

### Cross-ecosystem translation table

If the illustrative examples above lean on one stack, translate them. The rule is the same; only the substrate differs:

| Hazard class | SQL | Message bus | Object store | Filesystem | In-memory cache |
|---|---|---|---|---|---|
| Hardcoded unique identifier | row PK, email, slug | topic, queue, consumer-group | key, prefix | file path | cache key |
| "First row" / "any existing" | `LIMIT 1` without `WHERE` | `list_topics()[0]` | `list_objects()[0]` | `readdir()[0]` | first key in scan |
| Overbroad cleanup | `DELETE WHERE type=X` | `delete_topic` by pattern | `delete` by prefix | `rm -rf` by glob | `FLUSHDB` / wildcard evict |
| Unscoped aggregate assertion | `COUNT(*)` no `WHERE` | total message count | total object count | total file count | total key count |
| Hardcoded singleton assumption | "the admin role" row | "the default topic" | "the default bucket" | "the root config file" | "the sentinel key" |

## Shared-runtime review checks (MANDATORY — reviewers read every test file in the diff with this checklist)

When reviewing an integration or E2E test diff, actively hunt for the hazard patterns below. Any violation is a bug — fix it in this review pass, same as a null-pointer dereference or a missing auth check. Do not defer.

Authors tend to hit these hazards because the test passes locally in isolation; the bug only manifests when the test joins the shared-runtime suite. A reviewer who only checks "does it test the feature" will ship every one of these bugs into the fix-validate loop. Your job is to read the test *as if it were running concurrently alongside every other integration test in the repo*.

Detection heuristics, each of which should trigger a closer read:

1. **Literal values that look like canonical defaults.** Fingerprints of author-time shortcuts include: zero-padded or all-same-digit IDs (`00000000-…`, `11111111-…`, `id: 1`, `id: 42`); low round numbers (`"order-1"`, `"KNX-001"`, `"user-001"`); domain-English singletons (`"default"`, `"admin"`, `"system"`, `"root"`, `"main"`, `"Modules"`); common-placeholder emails (`test@`, `user@`, `admin@`, `foo@`, `bar@`); generic names (`"Test User"`, `"Sample Product"`). Every one of these is a collision candidate. Verify whether the value participates in any uniqueness constraint (DB unique index, message-bus name, filesystem path, external service ID). If yes, require a random suffix.

2. **Position-based access on shared collections.** Any `[0]`, `.first()`, `.head`, `LIMIT 1 OFFSET 0`, `take(1)`, iterator `.next()` applied to a query or listing of a resource the test did not just create. Ask: "what guarantees that the row this test gets is one it owns?" If the answer is "it's the one we just inserted two lines up" (file-scoped), safe. If the answer is anything about "there should only be one" or "the seed data has…," reject.

3. **Unscoped aggregates and list-length assertions.** Any `expect(x.length).toBe(N)`, `assert len(x) == N`, `assertEquals(n, x.size())` — ask whether the query/listing filters by an identifier the test owns. Same for counts: `SELECT COUNT(*)` without a predicate tied to test-owned state. A test that asserts a global count is a test that breaks the moment a sibling file writes a row of the same kind.

4. **Exact-equality deltas on non-owned metrics.** Any `after == before + N` pattern. Confirm the metric is scoped to an identifier the test owns. If the metric is global (total orders, event count, queue depth, cache-miss rate, audit-log length), the assertion must be `>=`, not `==`. Exact deltas on global metrics are the most common source of "works locally, fails in CI" flakes.

5. **Cleanup predicates that aren't ID lists.** Any teardown that deletes by `WHERE type = X`, `WHERE status = Y`, `WHERE created_at < T`, `WHERE name LIKE '%foo%'`, glob patterns, prefix matches, or "all rows I think I own." The only acceptable teardown shape is iterating a list of IDs captured at setup time. A broad `DELETE ... WHERE event_type IN (...)` or `rm /tmp/test-*` in a test file is a bug regardless of whether the current suite happens to pass — the next time a sibling test writes a matching row, things break mysteriously.

6. **Cross-case state references within a file.** Any test case whose setup or assertion references state "left over" from an earlier case in the same file. Fingerprints: comments like `// from previous test`, numeric continuations like "count is now 3, add 5 to get 8," setup that only works if a sibling `it` ran first. Require each case to be self-contained or have all shared state in a `beforeAll` / fixture.

7. **Shared external-resource names as literals.** Hardcoded filesystem paths (`/tmp/foo.log`), message-queue names (`topic: "orders"`), cache keys (`"cart:session"`), bucket prefixes (`"test-uploads/"`), DNS names, socket paths, container names — any string literal naming a resource outside the DB that the test reads or writes. Each needs a per-test suffix threaded in via config.

8. **Runner configuration vs. test assumptions.** Skim the runner config for this project (`vitest.config.*`, `pytest.ini`, `go.mod` + package layout, `Cargo.toml`, `[Test]` attributes, JUnit parallel config). If the runner runs files or cases in parallel and any test in the diff assumes it owns the stack, that test is broken — even if it currently passes. Call it out. If the runner is currently serial, note in the review whether the diff could survive parallelism; if not, the tests carry a latent failure that surfaces the next time someone enables parallelism.

9. **Uniqueness-constraint values generated from low-entropy sources.** `Date.now()`, `new Date().getTime()`, process-start timestamp, monotonically-increasing counters that aren't process-safe, hostname-based suffixes in CI (often shared across jobs). Under concurrent workers, two processes can sample in the same millisecond or use the same hostname. Require a CSPRNG-backed primitive (UUID/ULID/nanoid or ecosystem equivalent).

10. **Seed-data assumptions.** Any test that references a row/topic/key that wasn't created inside the test's setup. Includes: looking up "the admin role" by hardcoded ID, trusting that migration 0003 left a specific user in the DB, assuming a default tenant/project/org exists. Require an explicit setup insert or a property-based lookup (by name/tag/slug), never an ID literal.

Finding any of these in the diff means the test is an author-time error, even if the suite passes today. Fix by editing the test (add the random suffix, scope the predicate, capture IDs in cleanup). Do not waive, do not defer. A comment like `// TODO: make test-safe` is equivalent to committing the bug.

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

## Acceptance scenario exerciser

The spec's acceptance scenarios (Given/When/Then) are documentation during planning — but after implementation, they become **executable validation criteria**. The post-CI observable output validation phase (see `reference/cicd.md § Observable output validation` and `phases/implement.md § Phase 4`) must attempt to verify each one.

### Classification

For each acceptance scenario in the spec, classify by verifiability:

| Type | Examples | Action |
|------|----------|--------|
| **Automatically verifiable** | "badge shows MIT" → fetch URL, check SVG; "artifact is downloadable" → `gh run download`; "job fails with ::error::" → `gh run view --log` and grep | Execute and report PASS/FAIL |
| **CI-verifiable** | "job exits non-zero when 0 tests run" → examine CI run conclusion and logs | Check most recent CI run's logs/artifacts |
| **Manual** | "biometric prompt appears", "user sees loading state" | List in completion report |

### Execution rules

- Automatically verifiable scenarios are run in a fix-validate loop (10 iterations per scenario)
- CI-verifiable scenarios are checked against the most recent CI run — if the scenario can't be verified from the run (e.g., the failure condition wasn't triggered), note it as "not exercised in current run" rather than PASS
- Manual scenarios are listed with specific instructions for human verification
- A scenario that was verifiable at spec time but can't be verified after implementation (e.g., requires a state that CI doesn't produce) should trigger investigation — the implementation may have missed the requirement

### Integration with post-CI validation

The acceptance scenario exerciser runs as Step 4 of the observable output validation phase (see `phases/implement.md`). It is NOT a replacement for automated tests — it's a final verification that the spec's promises are actually met by the delivered system. Automated tests verify internal correctness; the exerciser verifies external promises.

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

**Pattern 10: NixOS VM and systemd service testing**

When a project uses NixOS VM tests (`nixpkgs.testers.nixosTest`) or relies on systemd services, tests MUST verify that services are **healthy after startup**, not just that `systemctl start` returns. A unit can enter `activating` → `active` → `failed` in under a second — checking only the start command misses crash-on-startup bugs entirely.

Required verification for every systemd service in a VM test:

1. **Wait for the unit with fail-fast crash detection**: Do NOT use bare `wait_for_unit` — its 900s default timeout means a crash-looping service wastes 15 minutes before the test fails. Instead, use a polling loop that detects the `failed` state immediately and dumps journal output for diagnosis.
2. **Check for fatal log messages**: After verifying the unit is active, grep the journal for fatal/error indicators: `journalctl -u service-name.service --no-pager -p err`. If there are error-level messages, the test should fail or at minimum log a warning.
3. **Verify the service's functional readiness**: Don't just check the process is alive — verify it's actually serving. For a web server, hit its health endpoint. For a gRPC server, make a test RPC. For a coordination server (like headscale), verify its API responds. A process that is `active (running)` but stuck in a startup loop or missing critical config is not ready.
4. **Use short timeouts on `wait_for_open_port`**: If the service is confirmed active, the port should open within seconds. Use `timeout=30` instead of the 900s default.

Common failure patterns this catches:
- **Crash-loop restart**: Service starts, crashes, systemd restarts it — `wait_for_unit` sees `active` during the brief restart window and passes, but the service is never actually healthy. The fail-fast loop catches this because it sees `failed` state between restarts.
- **Missing configuration**: Service starts, reads config, finds a required field empty (e.g., `initial DERPMap is empty`), logs `FTL`, and exits with code 1 — all within 1 second of starting
- **Dependency ordering**: Service A starts before Service B is ready, fails to connect, and crashes
- **Permission errors**: Service runs as wrong user, can't read its data directory, exits immediately
- **Port conflicts**: Two services bind the same port, second one crashes on startup

NixOS VM test example (Python test script):
```python
# BAD — waits 900s if the service crash-loops
host.wait_for_unit("headscale.service")
host.wait_for_open_port(8080)

# ALSO BAD — sleep(2) can miss crash-loops where systemd restarts fast enough
host.wait_for_unit("headscale.service")
host.sleep(2)
host.succeed("systemctl is-active headscale.service")

# GOOD — fails fast on crash-loop, dumps journal for diagnosis
host.succeed(
    "for i in $(seq 1 30); do "
    "  state=$(systemctl is-active my-service.service); "
    "  if [ \"$state\" = \"active\" ]; then exit 0; fi; "
    "  if [ \"$state\" = \"failed\" ]; then "
    "    echo 'my-service.service entered failed state:'; "
    "    journalctl -u my-service.service --no-pager -n 20; "
    "    exit 1; "
    "  fi; "
    "  sleep 2; "
    "done; "
    "echo 'my-service.service did not become active within 60s'; "
    "journalctl -u my-service.service --no-pager -n 20; "
    "exit 1"
)
host.wait_for_open_port(8080, timeout=30)
# Verify functional readiness
host.succeed("curl -sf http://localhost:8080/health")
```

**Why not `wait_for_unit` with a shorter timeout?** Because `wait_for_unit` polls for `active` state — and a crash-looping service IS `active` for a fraction of a second on each restart. It never returns `failed` to `wait_for_unit`, it just keeps restarting and hitting `active` briefly. The explicit `systemctl is-active` check catches the `failed` state between restart attempts.

This pattern applies beyond NixOS — any test that starts a background service (Docker container, `systemctl start`, `supervisord`, background process) must verify the service is **alive and functional**, not just that the start command returned 0.

### What makes these different from per-boundary tests

| Per-boundary integration test | User-flow integration test |
|-------------------------------|---------------------------|
| Tests ONE boundary (spawn, socket, API) | Tests the CHAIN of boundaries a user flow crosses |
| Fails if the boundary contract is wrong | Fails if ANY step in the chain is wrong |
| Uses stubs for adjacent systems | Uses real systems with deterministic inputs |
| Catches: "the protocol is wrong" | Catches: "the protocol works but the data from step 3 isn't what step 7 expects" |
| Fast, targeted, easy to debug | Slower, broader, catches cascade failures |

Both are needed. Per-boundary tests catch interface bugs quickly. User-flow tests catch the integration gaps that per-boundary tests miss.

## Pre-PR gate

Every project MUST include a single `make pre-pr` (or equivalent) command that runs all quality gates before creating a pull request. This is the repeatable developer action that runs on every future change — not just during initial implementation. See `reference/pre-pr.md` for the complete specification: multi-build-system discovery, non-vacuous assertions, CI workflow validation, E2E integration, and preset behavior.

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

## Concurrency safety verification

Race conditions are the highest-impact bugs that normal testing misses — they cause silent data corruption, intermittent crashes, and security vulnerabilities that only manifest under production load. Every project with concurrent code (goroutines, threads, async tasks, coroutines) MUST enable runtime race detection in CI.

### When race detection is mandatory

Enable race detection for any project that:
- Handles concurrent requests (servers, daemons, agents)
- Spawns goroutines, threads, or async tasks
- Uses shared mutable state (maps, registries, connection pools, caches)
- Has shutdown/cleanup logic that races with in-flight operations

### Language-specific tools

**Go — `-race` flag (zero false positives):**

```bash
# CI command — always use -count=1 to disable caching of race-detected runs
GORACE="halt_on_error=1 atexit_sleep_ms=0 history_size=2" \
  go test -race -count=1 -timeout 10m ./...
```

| GORACE option | Value | Why |
|--------------|-------|-----|
| `halt_on_error` | `1` | Fail immediately on first race — don't accumulate |
| `atexit_sleep_ms` | `0` | Skip the 1s post-test sleep (saves time in CI) |
| `history_size` | `2` | Doubles memory for stack traces — reduces "failed to restore the stack" errors |

Performance overhead is 2-20x CPU and 5-10x memory. This is acceptable in CI. Never ship a `-race`-instrumented binary. Split CI into parallel jobs if the slowdown is prohibitive:

```yaml
jobs:
  test-unit-race:
    steps:
      - run: go test -race -short -count=1 ./...
  test-integration-race:
    steps:
      - run: go test -race -run Integration -count=1 -timeout 10m ./...
```

Go's race detector uses ThreadSanitizer under the hood and requires `CGO_ENABLED=1`. If your project builds with `CGO_ENABLED=0`, you still MUST run tests with CGO enabled for race detection.

**Rust — choose by scenario:**

| Scenario | Tool | Command |
|----------|------|---------|
| `unsafe` code, single-threaded UB | Miri | `cargo +nightly miri test` |
| Lock-free data structures, custom sync | Loom | `RUSTFLAGS="--cfg loom" cargo test --release` |
| FFI / C interop with threads | ThreadSanitizer | `RUSTFLAGS="-Z sanitizer=thread" cargo +nightly test --target x86_64-unknown-linux-gnu` |
| Safe Rust with `Mutex`/`RwLock` only | Compiler prevents data races | Loom for logical correctness if complex |

Always pass `--target` explicitly with ThreadSanitizer to prevent sanitizer flags from applying to build scripts and proc macros.

**Java/Kotlin/Android — static analysis:**

Use Facebook's Infer/RacerD for static race detection: `infer run --racerd-only -- ./gradlew assembleDebug`. Annotate concurrent code with `@GuardedBy` and `@ThreadSafe` to improve analysis accuracy. No mature dynamic race detector exists for Kotlin coroutines — `@GuardedBy` annotations and RacerD are the best static option.

### Common race patterns in daemon/server code

These patterns are especially relevant to long-running services:

- **Shutdown vs. in-flight requests** — `Close()` sets a flag and closes listeners while goroutines still read shared state. Fix: `context.Context` cancellation + `sync.WaitGroup`.
- **Hot config reload** — daemon reads config on startup, a goroutine reloads it periodically. Readers see partially-updated config. Fix: `atomic.Value` or copy-on-write with a mutex.
- **Connection pool/registry mutations** — adding/removing entries from a shared map during concurrent request handling. Fix: `sync.RWMutex` or channel-based serialization.
- **Lazy initialization** — singleton initialized on first use without synchronization. Fix: `sync.Once`.
- **Test-only races** — parallel subtests sharing setup variables or writing to `*testing.T` from the wrong goroutine.

### Plan phase requirements

During the plan phase, for every project with concurrent code:
1. Add `-race` (or equivalent) to the default test command in the Makefile/CI config
2. Document the expected overhead and whether to split CI jobs
3. If the project has lock-free or wait-free data structures, plan Loom (Rust) or stress tests with high goroutine counts (Go)

## Adversarial flow tests

User-flow integration tests verify that the system works correctly for legitimate users. **Adversarial flow tests** verify that the system correctly *rejects* illegitimate users. This is a distinct test category because the gap between "code checks the cert" and "the deployed system rejects the connection" is where real security breaches occur.

### Why unit-level security tests are insufficient

Unit tests validate **code logic**. Adversarial E2E tests validate **deployed configuration**. Common gaps:

- **TLS library defaults** — Go's `crypto/tls` defaults to `NoClientCert`. A `VerifyPeerCertificate` callback is never called if `ClientAuth` isn't set to `RequireAndVerifyClientCert`. A unit test mocking the TLS layer can't catch this.
- **Middleware ordering** — a health-check endpoint registered before an auth interceptor bypasses mTLS. Only an E2E test hitting that endpoint from a rogue node catches this.
- **Firewall rules** — a daemon that should only accept connections on a Tailscale interface might also be reachable on a raw network interface. Unit tests can't verify firewall configuration.
- **systemd sandboxing** — `PrivateNetwork=true`, `ProtectSystem=strict` only apply when the service is started via systemd, not when launched manually in tests.
- **Certificate chain validation** — TLS implementations frequently disagree on whether mutant certificates should be accepted (Frankencerts research, IEEE S&P 2014). The full deployed TLS stack must be tested.

### Adversarial test scenarios

For every security boundary in the spec, plan an E2E test that verifies rejection from the **outside**:

**Certificate validity attacks:**

| Scenario | What to generate | Expected result |
|----------|-----------------|-----------------|
| Expired client cert | Cert with `NotAfter` in the past | TLS handshake fails |
| Not-yet-valid cert | Cert with `NotBefore` in the future | TLS handshake fails |
| Self-signed, not in trust store | `openssl req -x509 ...` | TLS handshake fails |
| Cert signed by different CA | Second CA signs cert | TLS handshake fails |
| Valid CA, wrong CN/SAN | Correct CA, wrong identity | Handshake OK, identity check rejects |
| Cert pinning bypass | Valid cert, different SPKI hash | Application-layer rejection |
| Wrong EKU | Server EKU instead of client EKU | TLS handshake fails |

**Infrastructure attacks:**

- **Non-Tailscale interface access** — connect via raw `eth0` IP instead of Tailscale overlay. Must be rejected by firewall or bind address.
- **Unpaired device connection** — a device on the same network but without paired state attempts to use the service.
- **Token replay after consumption** — reuse a one-time pairing token. Must get 401 or connection refused.
- **Connection reuse after cert rotation** — long-lived connections must be re-authenticated after certificate changes.

### Structuring adversarial tests in VM environments

**Pattern: Add a `rogue` node alongside legitimate nodes.** In NixOS VM tests, each `nodes.<name>` is a separate QEMU VM on the same virtual network — a genuinely separate machine, not a mock.

Key principles:
- Use `host.fail(...)` (not `succeed`) for adversarial assertions — you're testing that connections are **rejected**
- **Enable the firewall** in adversarial tests (unlike functional tests that may disable it for convenience) to verify only expected ports accept traffic
- **Test via systemd** for at least one scenario to validate sandboxing (`PrivateNetwork`, `ProtectSystem`, socket permissions)
- **Pre-generate adversarial cert fixtures** deterministically (in `test/fixtures/gen/`) rather than generating certs inside VMs at test time
- **Verify error opacity** — when a rogue connection is rejected, assert that the error leaks no internal details

### Plan phase requirements

During the plan phase, for every project with security boundaries (mTLS, auth tokens, network ACLs):
1. Identify all trust boundaries from the spec's security requirements
2. For each boundary, plan at least one adversarial E2E test with a rogue actor
3. Plan deterministic adversarial cert fixture generation (expired, wrong-CA, wrong-SAN, wrong-EKU)
4. Decide whether to test via systemd or manual launch — at least one adversarial test should use the real systemd service

## Hardware-dependent and emulator-gated test coverage

When a test suite requires hardware or an emulator (Android instrumented tests, iOS simulator tests, hardware token tests), running it on every PR may be impractical. This creates a coverage gap that must be explicitly managed — not silently ignored.

### The problem

Some test suites physically cannot run in standard CI: Android instrumented tests need an emulator, iOS tests need a simulator, hardware security tests need a physical token, GPU compute tests need a GPU. These environments are slow to boot, flaky, and resource-intensive. Many teams skip them entirely, leaving critical layers untested in CI. This is acceptable **only** if the gap is documented, mitigated, and tracked.

### Architecture for testability

The most impactful mitigation is separating pure logic from platform-dependent code:

1. **Shared libraries** (e.g., cross-platform code compiled for multiple targets) — test with standard language tooling on the host. Full coverage achievable with no device/emulator.
2. **Platform-independent layers** (ViewModels, repositories, state management, business logic) — test with platform stubs that run on the host (Robolectric for Android, XCTest without simulator for iOS, mock HAL for embedded). 10x faster than device tests.
3. **Thin platform wrappers** (hardware keystore, biometrics, NFC, camera, GPU, sensors) — define interfaces, keep implementations to 5-10 lines per method. Test via fakes in unit tests. The real implementations are the coverage gap.

### CI strategy tiers

| Tier | When to run | What to run | Coverage tool |
|------|-------------|-------------|---------------|
| Every PR | Always | Host-side tests + platform stubs + unit tests | Standard coverage tools for each language |
| Nightly/weekly | Schedule | Device/emulator instrumented tests | Platform-specific coverage (JaCoCo, xcresult, etc.) |
| On-demand | Manual or release | Physical device / hardware tests | Device-specific coverage or manual checklist |

For mobile emulator-in-CI: use KVM-accelerated runners (GitHub Actions ubuntu-latest supports this since 2024), cache device snapshots, use lightweight test images (ATD for Android). For hardware tests: consider cloud device farms (Firebase Test Lab, AWS Device Farm) on a scheduled basis.

### Coverage gap documentation

Maintain an explicit record of what is and isn't tested in CI. This can live in `specs/` or the plan:

```
## Coverage Boundaries

### Fully tested in CI (every PR)
- Host-side daemon/server (unit + integration): target 85%
- Shared cross-platform library: target 85%
- Platform-independent layers (via stubs): target 70%

### Tested on schedule only (nightly/weekly)
- Device/emulator instrumented tests
- Hardware-dependent integration (real crypto hardware, real network stack)

### Not tested in CI (manual only)
- Hardware-specific operations (secure enclave, biometrics, NFC)
- Physical device connectivity
- Platform-specific edge cases requiring real hardware

### Mitigations for untestable code
- Hardware operations behind interfaces (tested via fakes)
- Protocol tested end-to-end in shared library tests
- Manual test checklist in specs/manual-test-plan.md
```

### Multi-language coverage merging

For projects with multiple tech stacks (Go + Kotlin, Rust + TypeScript, etc.), track coverage per language with separate flags/components. Use Codecov flags or separate `coverage/<language>/` directories. Set different thresholds per component — don't block PRs on emulator-gated coverage:

- **Host-side / primary language**: target 85%, hard gate
- **Secondary language unit tests (platform stubs)**: target 70%, hard gate
- **Device/emulator instrumented tests**: informational only (use `carryforward: true` in Codecov to retain data between scheduled runs)

### Plan phase requirements

During the plan phase, for every project with hardware-dependent tests:
1. Identify which test suites require hardware/emulator
2. Choose a CI tier for each (every PR, scheduled, manual)
3. Plan the interface boundaries that make platform code testable via fakes
4. Create a coverage gap document with explicit boundaries and mitigations
5. Configure per-component coverage thresholds that reflect what actually runs in CI

## Performance and benchmark testing

When the spec defines performance goals (latency budgets, throughput targets, resource limits), those goals must be encoded as tests — not just documented and hoped for. Two layers of testing serve different purposes.

### Layer 1: E2E latency assertions (system-level)

These are regular test functions (not benchmarks) that assert the spec's hard requirements against the real system:

```go
func TestSignRequestLatency(t *testing.T) {
    if testing.Short() {
        t.Skip("skipping latency test in short mode")
    }

    const specBudget = 2 * time.Second
    const runs = 20

    var durations []time.Duration
    for i := 0; i < runs; i++ {
        start := time.Now()
        _, err := client.Sign(ctx, signRequest)
        elapsed := time.Since(start)
        require.NoError(t, err)
        durations = append(durations, elapsed)
    }

    sort.Slice(durations, func(i, j int) bool {
        return durations[i] < durations[j]
    })
    p95 := durations[int(float64(len(durations))*0.95)]

    t.Logf("p50=%v p95=%v max=%v",
        durations[len(durations)/2], p95, durations[len(durations)-1])

    require.Less(t, p95, specBudget,
        "p95 sign latency %v exceeds spec budget %v", p95, specBudget)
}
```

Key design choices:
- Use `*testing.T` (not `*testing.B`) — this asserts a hard requirement, not a relative comparison
- Run multiple iterations and assert on p95, not a single sample
- Add headroom for CI runner noise (if spec says 2s, test might use 2.5s in CI but log actual values)
- Skip with `-short` for fast local iteration; run in CI

### Layer 2: Microbenchmarks (component-level)

These track performance characteristics over time, catching regressions before they compound into a spec violation:

```go
func BenchmarkSigningOperation(b *testing.B) {
    signer := setupTestSigner(b)
    payload := generateTestPayload()
    b.ResetTimer()
    for b.Loop() {
        _, err := signer.Sign(payload)
        if err != nil {
            b.Fatal(err)
        }
    }
}
```

Microbenchmarks detect *relative* regressions via baseline comparison. Use `benchstat` (Go), `criterion` (Rust), or `pytest-benchmark` (Python) for statistical rigor — run with `-count=10` or more for significance.

### CI integration

| Signal | Action | Rationale |
|--------|--------|-----------|
| E2E latency exceeds spec budget | **Fail the build** | Spec contract violated |
| Microbenchmark regresses >150% | **Warn via PR comment** | Could be noise; needs human judgment |
| Microbenchmark regresses >300% | **Fail the build** | Catastrophic regression, unlikely noise |

For continuous tracking, use `github-action-benchmark` (supports Go, Rust, Python, JS — stores results on `gh-pages`, configurable alert thresholds) or `benchstat` with cached baselines.

### Budget decomposition

When the spec defines a single end-to-end budget (e.g., "sign request < 2 seconds"), decompose it into sub-budgets per component during the plan phase:

| Component | Sub-budget | Measured by |
|-----------|-----------|-------------|
| mTLS handshake | < 200ms | Microbenchmark |
| gRPC round-trip overhead | < 100ms | Microbenchmark |
| Phone signing operation | < 1500ms | E2E (includes phone simulator) |
| Margin | 200ms | — |

Each sub-budget becomes its own test assertion, making it clear *where* time is being spent when the overall budget is at risk.

### Plan phase requirements

During the plan phase, for every project with performance goals in the spec:
1. Identify all latency/throughput/resource targets from the spec
2. Decompose end-to-end budgets into per-component sub-budgets
3. Plan E2E latency assertion tests for each spec target (`*testing.T` style)
4. Plan microbenchmarks for performance-critical components (`*testing.B` style)
5. Choose a CI benchmarking tool and configure regression thresholds
6. Decide whether microbenchmark regressions block merges or just warn

## Real-runtime E2E testing

When a project targets a platform with its own runtime (Android, iOS, web browser, desktop), E2E tests MUST exercise the real app on the real (or emulated) runtime — not a simulated environment (Robolectric, jsdom, etc.). See `reference/e2e-runtime.md` for the complete guide: runtime selection table, side-by-side architecture, readiness checks, test bypass mechanisms for hardware features, UI automation patterns, multi-runtime orchestration, flakiness handling, and CI infrastructure per runtime.

The `e2e-runtime.md` reference is **mandatory reading** for any project that targets Android, iOS, web/PWA, or desktop platforms. Load it during the plan phase when designing the E2E test strategy.

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

## Security scan validation in the fix-validate loop

Security scanning is integrated into the same phase validation lifecycle as tests and lint. The validation agent runs **build → test → lint → security scan** as a single validation pass. If any step fails, the phase doesn't pass.

### Validation command sequence

The validation agent runs these in order (stopping on first failure category):

1. **Build** — `go build ./...`, `npm run build`, etc.
2. **Test** — `go test ./...`, `npm test`, etc. (writes to `test-logs/`)
3. **Lint** — `golangci-lint run`, `npm run lint`, etc.
4. **Security scan** — runs all project-relevant scanners (writes to `test-logs/security/`)

If tests fail, the validation agent reports test failures — it doesn't also run security scans on broken code. Security scans run only after build + test + lint pass. This prevents noise from scanners flagging code that's about to be rewritten anyway.

### Security scan output directory

```
test-logs/
  security/
    summary.json          # aggregated pass/fail + finding counts per scanner
    trivy.json            # raw Trivy JSON output
    semgrep.json          # raw Semgrep JSON output
    gitleaks.json         # raw Gitleaks JSON output
    govulncheck.json      # raw govulncheck JSON output
    <ecosystem>.json      # npm-audit, pip-audit, cargo-audit, etc.
```

Fix agents read `summary.json` first to understand scope, then drill into individual scanner files for finding details (file path, line number, rule ID, severity, description).

### Security fix-validate vs test fix-validate

The mechanics are identical — same task appending, same iteration cap, same BLOCKED.md. The only difference is what the fix agent reads:

| Failure type | Fix agent reads | Fix agent does |
|-------------|----------------|----------------|
| Test failure | `test-logs/<type>/<timestamp>/failures/*.log` | Fix code to pass tests |
| Security finding | `test-logs/security/<scanner>.json` | Fix vulnerable code pattern or update dependency |

Both types produce a validation record in `validate/<phase>/N.md` with PASS or FAIL. A phase passes validation only when ALL steps (build + test + lint + security) are clean.

See `reference/security.md` for the full scanner command list and `reference/cicd.md` for how this integrates with CI SARIF uploads.
