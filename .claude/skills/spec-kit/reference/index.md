## When to read which reference

This index lets you read the right reference file at the right moment, without having to scan all of them. **Do not read every file** — read only what matches the situation in front of you. Cache hits make these reads cheap; missing the right one wastes a fix-loop iteration.

Paths are relative to `.claude/skills/spec-kit/reference/`.

| If you are... | Read | Why |
|---|---|---|
| Writing or fixing tests, or unsure what test tier something belongs in | `testing.md` § Test tier taxonomy, § Zero-skips rule, § Stub detection | Validators reject for these rules; agents who skip them lose the next VR cycle |
| Setting up structured test output for a project (any language) | `testing.md` § Structured test output + `templates/EXAMPLE-OUTPUT.md` + `templates/test-reporter-<runner>` | Drop-in reporter templates; EXAMPLE-OUTPUT.md is the canonical schema |
| Diagnosing failing tests in a phase-fix task | `test-logs/summary.json` + `failures/<name>.log` (in the project) + `templates/EXAMPLE-OUTPUT.md` for schema | Structured output is the primary signal; read the schema once to know the shape |
| Adding a new test command or coverage tooling | `testing.md` § Code coverage collection | Coverage is mandatory; missing tools must be installed, not skipped |
| Diagnosing a platform-runtime / service-bringup failure | `e2e-failure-patterns.md` (find the matching `## Signature: <name>`) | Library of known failure shapes with proven root causes |
| Doing any fix-agent work (platform, services, integration, E2E bug) | `fix-agent-playbook.md` § Core principle, § Default fix preference order, § What NOT to do | Falsification rule, anti-patterns, claim format |
| Writing or following an MCP-driven E2E session | `mcp-e2e.md` § The explore-research-fix-verify loop, § Findings format | Defines findings.json shape, evidence format, platform tool semantics |
| Debugging an MCP launch failure (probe red, agent can't reach tool) | `mcp-e2e.md` § Platform runtimes + `e2e-failure-patterns.md` § mcp-launch-failed | Probe stderr is authoritative; sandbox/path issues are most common |
| Working with a real platform runtime (Android/iOS/web) | `e2e-runtime.md` | Why host-side tests are insufficient; what readiness means per platform |
| Touching CI workflows or fixing CI failures | `cicd.md` § Pipeline stages, § Non-vacuous CI validation, § Skip-as-failure CI validation | Defines what CI must run, how to detect silent passes |
| Running `nix` commands in CI / inside the sandbox | `nix-ci.md` | Daemon flags, devshell rules, `nix flake check` background pattern |
| Building or running the pre-PR gate command | `pre-pr.md` § The `pre-pr` target, § Non-vacuous assertion | Single-command quality gate; what it must check |
| Marking a task complete or evaluating a completion claim | `verification.md` § Completion claim format, § Verification rules by task type | Runner verifies; agents propose. Claim shape is enforced. |
| Touching payment flows, Stripe webhooks, or live keys | `stripe.md` (full file) | First-class dependency; webhook listener lifecycle, key delivery, guardrails |
| Implementing retries, webhooks, or any "safe to re-run" step | `idempotency.md` | Every setup step must be re-runnable; readiness checks before use |
| Adding or changing a health check | `health.md` | Endpoints/commands required; what "healthy" must verify |
| Implementing graceful shutdown / signal handling | `shutdown.md` | Signal handling, drain semantics, deadline behavior |
| Implementing structured logging | `logging.md` | Log levels, format, field conventions |
| Adding metrics, tracing, or error reporting | `observability.md` | Hook surface, what must be instrumented |
| Implementing rate limiting or backpressure | `rate-limiting.md` | Patterns and required surface |
| Writing or extending error handling | `errors.md` | Error hierarchy, no silent swallowing, no stringly-typed errors |
| Adding configuration, env-var handling, or secrets | `config.md` | Centralized config module, validation at startup |
| Adding API endpoints (REST/RPC/GraphQL) | `api-contracts.md` | Per-endpoint depth requirements |
| Modifying or extending the data model | `data-model.md` | Required field-level depth; not just a list |
| Designing or modifying inter-task data flow | `interface-contracts.md` | Producer/consumer contracts; when to formalize |
| Doing a schema/API/config migration | `migration.md` | Versioning strategy; backward-compat rules |
| Touching the developer setup (one-command dev, devshell) | `dx.md` | One-command setup is mandatory |
| Updating the project README | `readme.md` § Cognitive funneling principle | Human-facing doc rules |
| Updating UI flows or screen documentation | `ui-flow.md` | UI_FLOW.md is the living source of truth for screens/routes/state |
| Considering a security-relevant change (input handling, auth, secrets) | `security.md` | Secure-by-default, non-negotiable rules |
| Enumerating edge cases for a spec or new feature | `edge-cases.md` | Required Edge Cases & Failure Modes section |
| Numbering functional requirements / wiring traceability | `traceability.md` | FR numbering, requirement→test traceability |
| Justifying a Constitution Check violation | `complexity.md` | Complexity Tracking table is mandatory when violations occur |
| Declaring or evaluating phase parallelization | `phase-deps.md` | Phase Dependencies section is required in plan.md |
| Reading or writing the cost report | `cost-reporting.md` § Prompt-caching strategy | What gets logged; how cache costs are computed |

## How to use this index

1. Match your situation to a row. If two rows match, read both.
2. If no row matches, you probably don't need a reference — proceed with the task.
3. When you do read a file, read only the cited section unless context shows you need the rest.
4. Cache hits make these reads ~10% of fresh-input cost — err on the side of reading, not guessing.
