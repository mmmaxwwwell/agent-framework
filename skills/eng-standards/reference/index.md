# Engineering standards — reference index

This index lets you read the right standard at the right moment without scanning every file. **Do not read every file** — read only what matches the task in front of you. Reads are cheap on cache hits; missing the right one costs a rework loop.

Paths are relative to `skills/eng-standards/reference/`.

> These references were distilled from a spec-driven-development workflow, so a few of them mention that workflow's roles or artifacts (e.g. "the validator", "phase-fix", "learnings.md"). Ignore that framing — the engineering content stands on its own. Read a file for its rules, not its process assumptions.

## Step 1 — Classify the task and files BEFORE reading anything

Before you Read any reference beyond what the task obviously needs, classify the work. Pick **one** task-kind tag and **all** applicable file-domain tags. The classifications drive the Step 2 lookup.

**Task-kind tags** (pick exactly one):

| Tag | Meaning |
|-----|---------|
| `task:implement` | Writing new code or a feature |
| `task:fix-bug` | Repairing a specific failing test or reported bug |
| `task:fix-build` | Repairing a broken build/lint/typecheck |
| `task:fix-infra` | Repairing service bringup, env propagation, devshell, container |
| `task:fix-ci` | Repairing a CI workflow run |
| `task:plan` | Designing an approach / writing a spec or plan before coding |
| `task:review` | Reviewing a diff for bugs, security, or spec conformance |

**File-domain tags** (pick all that apply):

| Tag | Files this matches |
|-----|--------------------|
| `domain:test` | `*.test.*`, `*_test.*`, `__tests__/`, `test/`, `tests/`, `spec/` |
| `domain:api` | HTTP / RPC / GraphQL handlers, routes, controllers |
| `domain:data-model` | DB models, schemas, ORM definitions, migrations |
| `domain:migration` | Schema/data/config migration files |
| `domain:auth` | Authentication, session, OAuth, JWT, password / token handling |
| `domain:payment` | Stripe (or other payment SDK), webhook handlers |
| `domain:config` | Config loading, env parsing, secrets, `.env*`, `config/*` |
| `domain:logging` | Logger init, log calls, formatters |
| `domain:observability` | Metrics, traces, error reporting, OTel, Sentry |
| `domain:errors` | Error hierarchy, propagation, custom Error subclasses |
| `domain:health` | `/health`, `/ready`, healthcheck, readiness probe |
| `domain:shutdown` | Signal handlers, graceful drain, cleanup hooks |
| `domain:idempotency` | Setup scripts, retry logic, "safe to re-run" steps |
| `domain:rate-limit` | Throttling, backpressure, queue bounds, external-call timeouts |
| `domain:security` | Input validation, sanitization, CORS, headers, secrets |
| `domain:ui` | Components, screens, routes, navigation, forms |
| `domain:ui-flow-doc` | `UI_FLOW.md`, screen/state-transition docs |
| `domain:devshell` | `flake.nix`, `shell.nix`, `process-compose.yml`, `docker-compose.yml`, `setup.sh` |
| `domain:ci` | `.github/workflows/`, `.gitlab-ci.yml`, CI scripts |
| `domain:nix` | Any `*.nix` file, `flake.lock`, sandbox config |
| `domain:dx` | Dev setup, one-command bootstrap, contributor onboarding |
| `domain:readme` | `README.md` |
| `domain:spec` | Spec / plan / task documents you're authoring |
| `domain:interface-contract` | Inter-module data contracts, producer/consumer schemas |

State your classifications explicitly (e.g. `task:fix-bug + domain:auth + domain:api`) — even if only in your own thinking. They're inputs to Step 2, not decoration.

## Step 2 — Use the classifications to look up reads

Read every row whose **Tags** column intersects your active tags. A row tagged `*` always applies. Read the cited section if one is named, else the whole file. Two-tag matches are stronger than one — prioritize them. If your classification produces zero matches, you probably misclassified — re-check the task-kind.

| If you are... | Read | Why | Tags |
|---|---|---|---|
| Doing any implementation or fix work | `coding-behavior.md` | Behavioral floor: think-before-coding, simplicity-first, surgical-changes, goal-driven-execution | `*` |
| Writing or fixing tests, or unsure what tier something belongs in | `testing.md` § Test tier taxonomy, § Zero-skips rule, § Stub detection | The rules a good test suite must satisfy; stubs and skips are silent failures | `task:implement, task:fix-bug, task:fix-build, domain:test` |
| Setting up structured test output / coverage | `testing.md` § Structured test output, § Code coverage collection | Conventions for machine-readable results and mandatory coverage | `task:implement, domain:test` |
| Touching CI workflows or fixing CI | `cicd.md` § Pipeline stages, § Non-vacuous CI validation, § Skip-as-failure CI validation | What CI must run; how to detect silent passes | `task:fix-ci, task:implement, domain:ci` |
| Running `nix` in CI / sandbox | `nix-ci.md` | Daemon flags, devshell rules, `nix flake check` pattern | `task:fix-ci, task:fix-infra, task:fix-build, domain:nix, domain:ci, domain:devshell` |
| Building or running a pre-PR gate | `pre-pr.md` § The `pre-pr` target, § Non-vacuous assertion | Single-command quality gate; what it must check | `task:implement, domain:ci, domain:devshell` |
| Touching payment flows, Stripe webhooks, live keys | `stripe.md` (full file) | Webhook listener lifecycle, key delivery, guardrails | `task:implement, task:fix-bug, domain:payment` |
| Implementing retries, webhooks, or any "safe to re-run" step | `idempotency.md` | Every setup step must be re-runnable; readiness before use | `task:implement, task:fix-infra, domain:idempotency, domain:devshell` |
| Adding or changing a health check | `health.md` | Required endpoints/commands; what "healthy" must verify | `task:implement, task:fix-bug, domain:health` |
| Implementing graceful shutdown / signal handling | `shutdown.md` | Signal handling, drain semantics, deadline behavior | `task:implement, task:fix-bug, domain:shutdown` |
| Implementing structured logging | `logging.md` | Levels, format, field conventions | `task:implement, domain:logging` |
| Adding metrics, tracing, or error reporting | `observability.md` | Hook surface; what must be instrumented | `task:implement, domain:observability` |
| Implementing rate limiting / backpressure | `rate-limiting.md` | Patterns and required surface | `task:implement, domain:rate-limit, domain:api` |
| Writing or extending error handling | `errors.md` | Error hierarchy; no silent swallowing; no stringly-typed errors | `task:implement, task:fix-bug, domain:errors` |
| Adding config, env-var handling, or secrets | `config.md` | Centralized config module; validation at startup | `task:implement, task:fix-infra, domain:config, domain:security` |
| Adding API endpoints (REST/RPC/GraphQL) | `api-contracts.md` | Per-endpoint depth requirements | `task:implement, domain:api, domain:spec` |
| Modifying or extending the data model | `data-model.md` | Required field-level depth, not just a list | `task:implement, domain:data-model, domain:spec` |
| Designing inter-module data flow | `interface-contracts.md` | Producer/consumer contracts; when to formalize | `task:implement, domain:interface-contract, domain:spec` |
| Doing a schema/API/config migration | `migration.md` | Versioning strategy; backward-compat rules | `task:implement, task:fix-bug, domain:migration, domain:data-model, domain:config` |
| Touching developer setup (one-command dev, devshell) | `dx.md` | One-command setup is mandatory | `task:implement, task:fix-infra, domain:dx, domain:devshell` |
| Updating the project README | `readme.md` § Cognitive funneling principle | Human-facing doc rules | `task:implement, domain:readme` |
| Updating UI flows or screen documentation | `ui-flow.md` | UI_FLOW.md is the living source of truth for screens/routes/state | `task:implement, domain:ui, domain:ui-flow-doc` |
| Considering a security-relevant change (input, auth, secrets) | `security.md` | Secure-by-default, non-negotiable rules | `task:implement, task:fix-bug, task:review, domain:security, domain:auth, domain:api, domain:config` |
| Enumerating edge cases for a spec or feature | `edge-cases.md` | Required Edge Cases & Failure Modes coverage | `task:implement, task:plan, domain:spec` |
| Numbering functional requirements / wiring traceability | `traceability.md` | FR numbering, requirement→test traceability | `task:implement, task:plan, domain:spec, domain:test` |
| Justifying an added-complexity decision | `complexity.md` | Complexity Tracking table when you break simplicity | `task:implement, task:plan, domain:spec` |
| Declaring phase parallelization in a plan | `phase-deps.md` | Phase Dependencies section for parallel work | `task:plan, domain:spec` |

## Worked examples

**Fixing a failing auth integration test.** `task:fix-bug + domain:test + domain:auth + domain:api`. Read: `testing.md`, `security.md`, `coding-behavior.md`.

**Implementing a Stripe webhook endpoint.** `task:implement + domain:api + domain:payment + domain:idempotency + domain:errors + domain:logging`. Read: `stripe.md`, `api-contracts.md`, `idempotency.md`, `errors.md`, `logging.md`, `coding-behavior.md`.

**Planning a new public API.** `task:plan + domain:api + domain:spec + domain:security`. Read: `api-contracts.md`, `edge-cases.md`, `traceability.md`, `security.md`.

## How to use this index

1. **Classify first.** Write the tag set down before reading beyond the obvious.
2. **Look up matching rows.** Read every row whose tags intersect yours.
3. Read only the cited section unless context shows you need more.
4. If two rows point to the same file, read it once.
5. If no row matches, re-check your classification — most real tasks match 3–6 rows.
