## When to read which reference

This index lets you read the right reference file at the right moment, without having to scan all of them. **Do not read every file** — read only what matches the situation in front of you. Cache hits make these reads cheap; missing the right one wastes a fix-loop iteration.

Paths are relative to `.claude/skills/spec-kit/reference/`.

## Step 1 — Classify the task and files BEFORE reading anything else

Before you Read any reference file beyond the ones your role mandates as Tier-1, classify what you're about to work on. Pick **one** task-kind tag and **all** applicable file-domain tags. The classifications drive Step 2 (the lookup table); skipping classification means you'll read the wrong things.

**Task-kind tags** (pick exactly one — what shape of work is this?):

| Tag | Meaning |
|-----|---------|
| `task:implement` | Writing new code or features per a task description |
| `task:fix-bug` | Repairing a specific failing test, validation, or reported bug |
| `task:fix-build` | Repairing a broken build/lint/typecheck (compile-level failure) |
| `task:fix-infra` | Repairing service bringup, env propagation, devshell, container, sandbox |
| `task:fix-platform-runtime` | Repairing emulator / browser / simulator / MCP launch (E2E platform layer) |
| `task:fix-ci` | Repairing CI workflow run (separate from local build) |
| `task:explore-e2e` | Driving the running app via MCP to find bugs |
| `task:plan-e2e` | Producing a step list for an E2E executor |
| `task:execute-e2e` | Walking a pre-written E2E plan step-by-step |
| `task:verify-e2e` | Re-testing bugs and writing structured evidence |
| `task:research` | Read-only investigation of a bug; producing a research report |
| `task:supervise` | Reviewing prior attempts; deciding direction (DIRECT_FIX / REDIRECT_RESEARCH / ESCALATE / CONTINUE / STOP) |
| `task:validate` | Running the build/test/lint/security gate at a phase boundary |
| `task:review` | Reviewing a diff for bugs/security/spec-conformance |

**File-domain tags** (pick all that apply — what kinds of files are you about to edit or read?):

| Tag | Files this matches |
|-----|--------------------|
| `domain:test` | `*.test.*`, `*_test.*`, `__tests__/`, `test/`, `tests/`, `spec/` (excluding spec-kit specs) |
| `domain:test-reporter` | Custom test reporter / formatter, JUnit/JSON output writer |
| `domain:api` | HTTP / RPC / GraphQL handlers, route definitions, controllers |
| `domain:data-model` | DB models, schemas, ORM definitions, migrations |
| `domain:migration` | Schema/data/config migration files |
| `domain:auth` | Authentication, session, OAuth, JWT, password / token handling |
| `domain:payment` | Stripe (or other payment SDK) usage, webhook handlers, listener lifecycle |
| `domain:config` | Config loading, env var parsing, secrets handling, `.env*`, `config/*` |
| `domain:logging` | Logger initialization, log calls, log formatters |
| `domain:observability` | Metrics, traces, error reporting, OTel, Sentry, etc. |
| `domain:errors` | Error hierarchy, error propagation, custom Error subclasses |
| `domain:health` | `/health`, `/ready`, healthcheck command, readiness probe |
| `domain:shutdown` | Signal handlers, graceful drain, cleanup hooks |
| `domain:idempotency` | Setup scripts, retry logic, "safe to re-run" steps, dedup keys |
| `domain:rate-limit` | Throttling, backpressure, queue bounds, timeouts on external calls |
| `domain:security` | Input validation, sanitization, CORS, headers, secret management |
| `domain:ui` | Components, screens, routes, navigation, forms |
| `domain:ui-flow-doc` | `UI_FLOW.md`, screen/state-transition docs |
| `domain:e2e-test` | E2E test files, MCP-driven test runners, test/e2e/ contents |
| `domain:platform-runtime` | Emulator scripts, browser-launch wrappers, MCP server configs |
| `domain:devshell` | `flake.nix`, `shell.nix`, `process-compose.yml`, `docker-compose.yml`, `setup.sh` |
| `domain:ci` | `.github/workflows/`, `.gitlab-ci.yml`, CI scripts |
| `domain:nix` | Any `*.nix` file, `flake.lock`, sandbox / bwrap config |
| `domain:dx` | Dev setup, one-command bootstrap, contributor onboarding |
| `domain:readme` | `README.md` (project root, public-facing) |
| `domain:spec` | Spec-kit specs (`spec.md`, `plan.md`, `tasks.md`, `data-model.md`, `contracts/*`) |
| `domain:interface-contract` | Inter-task data contracts, producer/consumer schemas |

State your classifications explicitly (e.g., `task:fix-bug + domain:auth + domain:api`) — even if it's only in your own thinking. The classifications are inputs to Step 2, not decoration.

## Step 2 — Use the classifications to look up additional reads

Find every row whose **Tags** column contains at least one of your active tags. Read those files (cited section if specified, full file otherwise). Two-tag matches are stronger than one-tag matches — prioritize accordingly.

**Lookup rules:**

- **Read every row whose tag set intersects your active tags.** If you have `task:fix-bug + domain:auth + domain:api`, read every row tagged `task:fix-bug`, every row tagged `domain:auth`, and every row tagged `domain:api`.
- **A row tagged `*` matches every classification** — those are universally applicable and should always be read.
- **If two rows would have you read the same file, read it once.** Subsequent reads of the same path within 5 minutes are cache hits anyway, but don't waste turns on duplicate Reads.
- **If your classification produces zero matches, you probably misclassified.** Re-check task-kind: most fix work falls into `fix-bug`, `fix-build`, `fix-infra`, `fix-platform-runtime`, or `fix-ci`. Most implementation work is `implement` plus several `domain:*` tags.

| If you are... | Read | Why | Tags |
|---|---|---|---|
| Writing or reading ANY file that another agent will consume (findings.json, plan.md, handoff.md, blocker.md, research-N.md, verify-evidence-{iter}.md, supervisor-N-decision.md, claims/*.json, validate/{N}.md, review-{cycle}.md, attempt-N-*.md, bug_history.json, fix-history.md, etc.) | `agent-file-schemas.md` (find the matching `## IC-AGENT-NNN` entry) | Required field names, anchor headings the runner parses, status enums, and JSON shapes. Mismatched output silently breaks downstream agents. | `task:implement, task:fix-bug, task:explore-e2e, task:plan-e2e, task:execute-e2e, task:verify-e2e, task:research, task:supervise, task:validate, task:fix-ci, task:fix-platform-runtime` |
| Writing or fixing tests, or unsure what test tier something belongs in | `testing.md` § Test tier taxonomy, § Zero-skips rule, § Stub detection | Validators reject for these rules; agents who skip them lose the next VR cycle | `task:implement, task:fix-bug, task:fix-build, task:validate, domain:test` |
| Setting up structured test output for a project (any language) | `testing.md` § Structured test output + `templates/EXAMPLE-OUTPUT.md` + `templates/test-reporter-<runner>` | Drop-in reporter templates; EXAMPLE-OUTPUT.md is the canonical schema | `task:implement, domain:test, domain:test-reporter` |
| Diagnosing failing tests in a phase-fix task | `test-logs/summary.json` + `failures/<name>.log` (in the project) + `templates/EXAMPLE-OUTPUT.md` for schema | Structured output is the primary signal; read the schema once to know the shape | `task:fix-bug, task:fix-build, domain:test` |
| Adding a new test command or coverage tooling | `testing.md` § Code coverage collection | Coverage is mandatory; missing tools must be installed, not skipped | `task:implement, domain:test, domain:devshell` |
| Diagnosing a platform-runtime / service-bringup failure | `e2e-failure-patterns.md` (find the matching `## Signature: <name>`) | Library of known failure shapes with proven root causes | `task:fix-infra, task:fix-platform-runtime, domain:platform-runtime, domain:devshell` |
| Doing any fix-agent work (platform, services, integration, E2E bug) | `fix-agent-playbook.md` § Core principle, § Default fix preference order, § What NOT to do | Falsification rule, anti-patterns, claim format | `task:fix-bug, task:fix-build, task:fix-infra, task:fix-platform-runtime, task:fix-ci` |
| Writing or following an MCP-driven E2E session | `mcp-e2e.md` § The explore-research-fix-verify loop, § Findings format | Defines findings.json shape, evidence format, platform tool semantics | `task:explore-e2e, task:plan-e2e, task:execute-e2e, task:verify-e2e, domain:e2e-test` |
| Debugging an MCP launch failure (probe red, agent can't reach tool) | `mcp-e2e.md` § Platform runtimes + `e2e-failure-patterns.md` § mcp-launch-failed | Probe stderr is authoritative; sandbox/path issues are most common | `task:fix-platform-runtime, domain:platform-runtime` |
| Working with a real platform runtime (Android/iOS/web) | `e2e-runtime.md` | Why host-side tests are insufficient; what readiness means per platform | `task:explore-e2e, task:execute-e2e, task:verify-e2e, task:fix-platform-runtime, domain:platform-runtime, domain:e2e-test` |
| Touching CI workflows or fixing CI failures | `cicd.md` § Pipeline stages, § Non-vacuous CI validation, § Skip-as-failure CI validation | Defines what CI must run, how to detect silent passes | `task:fix-ci, task:implement, domain:ci` |
| Running `nix` commands in CI / inside the sandbox | `nix-ci.md` | Daemon flags, devshell rules, `nix flake check` background pattern | `task:fix-ci, task:fix-infra, task:fix-build, domain:nix, domain:ci, domain:devshell` |
| Building or running the pre-PR gate command | `pre-pr.md` § The `pre-pr` target, § Non-vacuous assertion | Single-command quality gate; what it must check | `task:validate, task:implement, domain:ci, domain:devshell` |
| Marking a task complete or evaluating a completion claim | `verification.md` § Completion claim format, § Verification rules by task type | Runner verifies; agents propose. Claim shape is enforced. | `task:implement, task:fix-bug, task:fix-build, task:fix-infra, task:fix-platform-runtime, task:fix-ci, task:verify-e2e` |
| Touching payment flows, Stripe webhooks, or live keys | `stripe.md` (full file) | First-class dependency; webhook listener lifecycle, key delivery, guardrails | `task:implement, task:fix-bug, domain:payment` |
| Implementing retries, webhooks, or any "safe to re-run" step | `idempotency.md` | Every setup step must be re-runnable; readiness checks before use | `task:implement, task:fix-infra, domain:idempotency, domain:devshell` |
| Adding or changing a health check | `health.md` | Endpoints/commands required; what "healthy" must verify | `task:implement, task:fix-bug, domain:health` |
| Implementing graceful shutdown / signal handling | `shutdown.md` | Signal handling, drain semantics, deadline behavior | `task:implement, task:fix-bug, domain:shutdown` |
| Implementing structured logging | `logging.md` | Log levels, format, field conventions | `task:implement, domain:logging` |
| Adding metrics, tracing, or error reporting | `observability.md` | Hook surface, what must be instrumented | `task:implement, domain:observability` |
| Implementing rate limiting or backpressure | `rate-limiting.md` | Patterns and required surface | `task:implement, domain:rate-limit, domain:api` |
| Writing or extending error handling | `errors.md` | Error hierarchy, no silent swallowing, no stringly-typed errors | `task:implement, task:fix-bug, domain:errors` |
| Adding configuration, env-var handling, or secrets | `config.md` | Centralized config module, validation at startup | `task:implement, task:fix-infra, domain:config, domain:security` |
| Adding API endpoints (REST/RPC/GraphQL) | `api-contracts.md` | Per-endpoint depth requirements | `task:implement, domain:api, domain:spec` |
| Modifying or extending the data model | `data-model.md` | Required field-level depth; not just a list | `task:implement, domain:data-model, domain:spec` |
| Designing or modifying inter-task data flow | `interface-contracts.md` | Producer/consumer contracts; when to formalize | `task:implement, domain:interface-contract, domain:spec` |
| Doing a schema/API/config migration | `migration.md` | Versioning strategy; backward-compat rules | `task:implement, task:fix-bug, domain:migration, domain:data-model, domain:config` |
| Touching the developer setup (one-command dev, devshell) | `dx.md` | One-command setup is mandatory | `task:implement, task:fix-infra, domain:dx, domain:devshell` |
| Updating the project README | `readme.md` § Cognitive funneling principle | Human-facing doc rules | `task:implement, domain:readme` |
| Updating UI flows or screen documentation | `ui-flow.md` | UI_FLOW.md is the living source of truth for screens/routes/state | `task:implement, task:execute-e2e, task:verify-e2e, domain:ui, domain:ui-flow-doc` |
| Considering a security-relevant change (input handling, auth, secrets) | `security.md` | Secure-by-default, non-negotiable rules | `task:implement, task:fix-bug, task:review, domain:security, domain:auth, domain:api, domain:config` |
| Enumerating edge cases for a spec or new feature | `edge-cases.md` | Required Edge Cases & Failure Modes section | `task:implement, domain:spec` |
| Numbering functional requirements / wiring traceability | `traceability.md` | FR numbering, requirement→test traceability | `task:implement, domain:spec, domain:test` |
| Justifying a Constitution Check violation | `complexity.md` | Complexity Tracking table is mandatory when violations occur | `task:implement, domain:spec` |
| Declaring or evaluating phase parallelization | `phase-deps.md` | Phase Dependencies section is required in plan.md | `task:implement, domain:spec` |
| Reading or writing the cost report | `cost-reporting.md` § Prompt-caching strategy | What gets logged; how cache costs are computed | (do not read during normal task work — out-of-band human/runner concern) |

## Worked examples

**Example 1 — fixing a failing auth integration test.**
Classification: `task:fix-bug + domain:test + domain:auth + domain:api`.
Matched rows: "Diagnosing failing tests in a phase-fix task" (`task:fix-bug, domain:test`), "Doing any fix-agent work" (`task:fix-bug`), "Writing or fixing tests" (`task:fix-bug, domain:test`), "Considering a security-relevant change" (`task:fix-bug, domain:auth`), "Touching CI workflows" no — only matches `task:fix-ci`. So you Read: `testing.md`, `fix-agent-playbook.md`, `security.md` — plus the project-side `test-logs/summary.json` once it exists.

**Example 2 — implementing a new Stripe webhook endpoint.**
Classification: `task:implement + domain:api + domain:payment + domain:idempotency + domain:errors + domain:logging`.
Matched rows: "Touching payment flows" (`domain:payment`), "Adding API endpoints" (`domain:api`), "Implementing retries, webhooks" (`domain:idempotency`), "Writing or extending error handling" (`domain:errors`), "Implementing structured logging" (`domain:logging`), "Writing or fixing tests" (`task:implement`), plus `verification.md` for the claim format.

**Example 3 — Android emulator won't boot during E2E.**
Classification: `task:fix-platform-runtime + domain:platform-runtime + domain:devshell`.
Matched rows: "Diagnosing a platform-runtime / service-bringup failure" (`task:fix-platform-runtime`), "Doing any fix-agent work" (`task:fix-platform-runtime`), "Working with a real platform runtime" (`task:fix-platform-runtime, domain:platform-runtime`), "Debugging an MCP launch failure" (`task:fix-platform-runtime`), and "Running nix commands" if Nix project (`domain:devshell`). Read: `e2e-failure-patterns.md`, `fix-agent-playbook.md`, `e2e-runtime.md`, `mcp-e2e.md` § Platform runtimes, `nix-ci.md` (if Nix).

## How to use this index

1. **Classify first** (Step 1). Write the tag set down before reading anything beyond your role's Tier-1 reads.
2. **Look up matching rows** (Step 2). Read every row whose tag set intersects yours.
3. When you do read a file, read only the cited section unless context shows you need the rest.
4. If two rows direct you to the same file, read it once — Claude Code's Read cache makes the second Read cheap, but the prompt clutter is unnecessary.
5. If no row matches your tags, re-check the classification. Most real tasks match 3–6 rows.
6. Cache hits make these reads ~10% of fresh-input cost — err on the side of reading, not guessing.
