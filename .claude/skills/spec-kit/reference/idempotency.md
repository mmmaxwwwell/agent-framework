# Idempotency & Readiness Checks

In agentic workflows, agents crash, get rate-limited, hit context limits, and get restarted constantly. Every setup step must be safe to re-run, and every dependency must be verified before use.

## Idempotency requirements

Any setup, initialization, or bootstrapping flow MUST be specified as idempotent — "if already done, skip gracefully." This applies to:
- Project initialization (git init, dependency install, config generation)
- Database/schema creation
- Cryptographic material generation (keypairs, certificates, tokens)
- External service registration (API keys, webhook subscriptions)
- File/directory creation
- Environment setup (flake generation, tool installation)

The rule: **check before mutating**. If the resource exists, reuse it. If the operation already ran, skip it. Never overwrite, double-initialize, or re-generate something that downstream steps already reference.

**In the spec (Phase 2)**: Specify setup flows as idempotent — "if already done, skip gracefully."

**In the plan (Phase 5)**: Call out the idempotency requirement for every setup task. Describe what "already done" looks like (e.g., "if `flake.nix` exists, skip generation").

**In implementation**: Every setup function must implement existence checks before mutating state. Example patterns:
- `if (existsSync(path)) return;` before file creation
- `CREATE TABLE IF NOT EXISTS` for database schemas
- `git init` only if `.git/` doesn't exist
- Keypair generation only if keypair file doesn't exist

## Readiness checks for external dependencies

When a task depends on an external service (emulator, database, dev server, message queue, etc.), the agent MUST NOT proceed until the dependency is verified ready. The project MUST provide **blocking readiness scripts** that:

1. **Block until the dependency is available** (polling with timeout)
2. **Return instantly if already up** (idempotent check)
3. **Exit non-zero with a clear message if the dependency can't be reached** (after timeout)

Example patterns:
- `npm run emulator:wait` — blocks until Android emulator is booted
- `npm run db:wait` — blocks until database accepts connections
- `npm run dev:wait` — blocks until dev server responds to health check

These scripts MUST be:
- Defined in the project's task runner as named scripts
- Called by agents before any task that depends on the service
- Included in the task list as explicit steps
