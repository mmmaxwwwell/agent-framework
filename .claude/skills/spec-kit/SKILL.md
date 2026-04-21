---
name: spec-kit
description: Initialize and drive a spec-kit (Specification-Driven Development) project using the `specify` CLI. Handles install, init, and walks the user through the full SDD workflow — constitution, specify, clarify, plan, tasks, implement. Enforces end-to-end integration testing with real server implementations, structured agent-readable test output, a fix-validate loop after every phase, and per-phase code review with review/validate cycling until clean. Use when the user wants to start or continue a spec-kit project.
user-invocable: true
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, WebFetch
argument-hint: [project-name]
---

# Spec-Kit — Specification-Driven Development

You are helping the user work with **spec-kit** (`specify` CLI), GitHub's toolkit for Specification-Driven Development (SDD). In SDD, natural-language specifications are the primary artifact — you write detailed specs describing *what* and *why*, then generate plans, tasks, and implementation from those specs.

**This skill uses lazy-loading.** This file is the dispatcher — it detects the current phase and loads only the relevant phase file plus any needed reference files. Do NOT read all files upfront.

## File layout

```
phases/              # One file per workflow phase — load only what's needed
  install.md         # Phase 0: install specify, init project
  interview.md       # Phase 2: specification interview
  plan.md            # Phase 5: architecture walkthrough and plan generation
  tasks.md           # Phase 6: task list generation
  implement.md       # Phase 7: autonomous runner, fix-validate, auto-unblocking
reference/           # Enterprise knowledge base — loaded on demand by phase files
                     # AND by spawned runner agents (see "Two-tier prompt
                     # loading" in README.md). Stable paths → cache hits.
  index.md           # Decision-tree index: "if you are doing X, read Y" — every runner-spawned agent gets this as a Tier-2 pointer
  testing.md         # Integration testing, structured output, stub processes, fix-validate loop, security scan validation
  logging.md         # Structured logging spec
  errors.md          # Error hierarchy, propagation
  config.md          # Config management
  security.md        # Security baseline, scanning tiers, headers, local scanner commands, SARIF CI integration
  shutdown.md        # Graceful shutdown
  health.md          # Health checks
  rate-limiting.md   # Rate limiting & backpressure
  observability.md   # Metrics, tracing
  migration.md       # Migration & versioning
  cicd.md            # CI/CD pipeline, local security scan validation, agentic CI feedback loop
  nix-ci.md          # Nix-specific CI rules (NIX_REMOTE=daemon, devshell, flake check background, bwrap sandbox)
  dx.md              # Developer experience tooling
  ui-flow.md         # UI_FLOW.md spec
  data-model.md      # Data model depth
  api-contracts.md   # API contract depth (external interfaces)
  interface-contracts.md # Internal interface contracts between tasks (file paths, formats, protocols)
  traceability.md    # FR numbering, SC, learnings format, test plan matrix, done criteria, IC tags
  idempotency.md     # Idempotency & readiness checks
  edge-cases.md      # Edge case enumeration
  complexity.md      # Complexity tracking
  phase-deps.md      # Phase dependencies & parallelization
  readme.md          # Human-facing README.md structure, sections, quality checklist
  pre-pr.md          # Pre-PR gate: single-command validation, multi-build discovery, non-vacuous checks
  e2e-runtime.md     # Real-runtime E2E: emulator, browser, simulator patterns, side-by-side architecture
  mcp-e2e.md         # MCP-driven E2E exploration loop (explore/plan/execute/verify), findings.json shape, per-platform tool semantics
  fix-agent-playbook.md # General debugging heuristics for any spawned fix-agent: falsification rule, anti-patterns, claim format
  e2e-failure-patterns.md # Library of known platform-runtime failure signatures, matched per-attempt by the runner
  agent-file-schemas.md # IC-AGENT-* schemas for every cross-agent file (findings.json, plan.md, handoff.md, etc.) — the runner parses specific anchors
  verification.md    # Deterministic completion-claim verification rules
  stripe.md          # Stripe / payment integration: listener scripts, env pattern, webhook contract, RUNBOOK, live-key guardrails
  cost-reporting.md  # Post-hoc cost & effectiveness analysis via cost_report.py (reads run-log.jsonl, outputs per-model/per-phase dollar breakdown)
presets/             # Quality presets — loaded once per project
  poc.md             # Proof of concept
  local.md           # Single-user local tool
  library.md         # Published package (npm, PyPI, crates.io)
  extension.md       # Browser / IDE extension
  public.md          # Single-user public-facing
  enterprise.md      # Multi-user production
```

## Project preset — PICK FIRST

Before doing anything else, determine the project's quality preset. This controls how many questions you ask, which infrastructure you include, and how heavy the process is. **Ask the user to pick one** (or detect from context if they already stated it):

| Preset | Use when | Infrastructure |
|--------|----------|---------------|
| **poc** | Throwaway prototype, speed over everything | None — console.log, hardcoded config, no auth/tests/CI |
| **local** | Single-user local tool (CLI, desktop, dev tooling) | Enterprise-grade — full test infra, CI/CD, structured logging, comprehensive errors. Scoped: no auth/CORS/rate-limiting/observability. |
| **library** | Published package (npm, PyPI, crates.io) | Enterprise-grade — full test infra across target environments, CI/CD with publish pipeline, strict semver. Scoped: no server, no deployment, no auth. |
| **extension** | Browser extension, VS Code extension, IDE plugin | Enterprise-grade — full test infra with host platform harness, CI/CD with store publish, permission audit. Scoped: platform sandbox constraints. |
| **public** | Single-user but internet-exposed | Enterprise-grade — full security hardening, CI/CD, structured logging. Scoped: no multi-user auth, no observability infra. |
| **enterprise** | Multi-user, production, team-maintained | Full — everything in the reference files |

**How to apply the preset:**

1. Read the preset file from `presets/<preset>.md` (relative to this SKILL.md)
2. The preset lists overrides for each phase: what to skip, what to default, what to still ask about
3. **The preset overrides MANDATORY tags in phase/reference files** — if the preset says "skip", skip it. Preset wins.
4. **Phase and reference files remain your knowledge base** — if the user asks about something the preset skipped, reference the relevant file and advise
5. Record the chosen preset in `interview-notes.md` so downstream phases know which preset is active

**If the user doesn't pick**: After hearing the project description, **suggest the best-fit preset** with a brief pros/cons comparison. Example format:

> This sounds like a local developer tool, so I'd recommend **local**:
>
> | Preset | Pros | Cons |
> |--------|------|------|
> | **poc** | Fastest path to working code, ~3 questions | No tests, no error handling — you'll rewrite most of it |
> | **local** (recommended) | Solid tests, good error messages, still fast | Slight overhead for config module and error hierarchy |
> | **public** | N/A — this tool isn't network-exposed | Would add unnecessary security hardening |

Skip presets that clearly don't apply (don't show enterprise for a throwaway script, don't show poc for a multi-user SaaS). Only show plausible matches.

**Upgrading later**: The user can re-run with a higher preset at any time. The agent reads the existing spec and interview-notes, identifies what the new preset adds, and walks through only the new decisions.

## Nix-first dependency management

**At the start of every project, check if Nix is available** (`which nix`). If it is, Nix flakes are the **default** for all dependency and environment management:
- `flake.nix` with `devShells.default` provides all tools
- `.envrc` with `use flake` auto-activates the dev shell
- Backing services: prefer Nix-native solutions over Docker Compose
- New tools go in `flake.nix`, not global installs

If Nix is NOT available, fall back to Docker/devcontainers. Do not block on Nix.

## Payment integration (Stripe)

Stripe is a **first-class project dependency** in spec-kit — treated with the same weight as choosing a platform target (Android/iOS/web). When the project involves revenue, payments, subscriptions, donations, or any form of commerce, the skill must detect this during the interview, explicitly confirm with the user, and scaffold the full integration pattern.

### Auto-detection during the interview

When the user describes their project, scan the description for commerce/revenue keywords:
`ecommerce`, `marketplace`, `subscription`, `SaaS`, `payments`, `revenue`, `checkout`, `billing`, `storefront`, `shop`, `paid tier`, `pro plan`, `charge customers`, `sell`, `for profit`, `donations`, `tips`, `one-time purchase`.

If any keyword appears, the interview MUST explicitly ask:

> "This project mentions revenue/payments — do you want Stripe integration scaffolded? [y/N]"

Default: **No**. Never scaffold Stripe by inference — always require explicit confirmation. Record the answer in `interview-notes.md` under `Payment integration: stripe | none`.

### When the user opts in

Load `reference/stripe.md` — it is the full knowledge base. The generated bundle includes:

- **Scripts** (`scripts/stripe-listen-start.sh`, `stripe-listen-stop.sh`, `stripe-webhook-secret.sh`, `sync-env.sh`) — stack-agnostic bash, all chmod +x'd.
- **Flake** — `stripe-cli` added to the devShell.
- **Env scaffolding** — `.env.example` with `STRIPE_SECRET_KEY`, `PUBLIC_STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_TAX_ENABLED`, plus a banner warning about test-only keys.
- **Webhook handler contract** — documented in `docs/stripe-integration.md` (stack-agnostic — the agent researches raw-body handling for their specific framework: Fastify, Express, Next.js, FastAPI, etc.).
- **Publishable key delivery contract** — `GET /api/<client>/stripe/config` + `PUBLIC_*` env fallback for web + `--dart-define` / build-config fallback for mobile. Dual-path so mobile keys can rotate without app store releases.
- **CLAUDE.md stanza** — keys, dev workflow, test vs live.
- **test/e2e/README.md stanza** — first-time setup, agent usage pattern, scripts reference table.
- **RUNBOOK.md stanza** — all 8 areas (dev webhook lifecycle, test/live guardrails, prod endpoint setup, delivery failure recovery, secret rotation, fraud/dispute response, monitoring, common errors).
- **`.claude/task-deps.json` entry** — `stripe-listen` with start/stop scripts, JSON output schema, prereq list.
- **Task-list tagging** — Stripe-related E2E tasks get `[needs: stripe-listen]` + `Prereq:` line.
- **Live-key guardrails (all three)** — pre-commit hook blocking `sk_live_` / `pk_live_`, gitleaks rule, `.env.example` warning comment.

### Core design patterns (documented in depth in `reference/stripe.md`)

- **Single-source-of-truth `.env` + `sync-env.sh`** — root `.env` is canonical; `PUBLIC_*`-prefixed variables are copied into the web frontend's `.env` via a predev/prebuild hook. Secrets physically cannot leak to the frontend because the sync script filters them out.
- **Runtime fetch + build-time fallback for publishable keys** — clients hit `/api/<client>/stripe/config` at runtime, with the build-time env as a fallback. Enables key rotation without app store re-releases.
- **Listener lifecycle scripts** — the webhook signing secret rotates every `stripe listen` session as a security feature. Rather than fighting it, the start script is idempotent (detects/reuses a live listener, cleans stale PIDs, writes the session secret to `.env`) and emits JSON (`{pid, secret, forward_to, log, reused}`) for agents to parse. API must restart after start to pick up the new secret.
- **Three-layered live-key guardrails** — pre-commit hook + CI gitleaks + `.env.example` warning. Bypassing one still trips the others.

### Future-proofing

The initial implementation is Stripe-specific. If a future project uses a different payment processor (Braintree, Adyen, Paddle), the **shape** transfers directly — webhook-listener lifecycle scripts, publishable-key dual delivery, env sync, live-key guardrails. Only the SDK names change. `reference/stripe.md` explicitly documents this so a future `reference/braintree.md` (or whatever) can follow the same pattern.

## Agent sandboxing

Implementation agents (Phase 7) run inside a **bubblewrap (bwrap) sandbox**. The sandbox is transparent to agents — they don't need to do anything special. The runner handles all sandbox setup.

### What agents need to know

- **Only the project directory is writable.** Global install paths don't exist. Install tools via `flake.nix`, not globally.
- **Network is restricted.** DNS is neutered; outbound connections only work through an allowlist proxy. Allowed domains: `api.anthropic.com`, `registry.npmjs.org`, `pypi.org`, `files.pythonhosted.org`, `cache.nixos.org`, `github.com`.
- **No credential files exist.** `~/.claude/`, `~/.ssh/`, `~/.aws/` are not mounted. Auth is handled by the runner via a one-shot file descriptor.
- **`--no-sandbox` disables sandboxing** (for debugging). `--unshare-pid` isolates the PID namespace.

### Install rules (defense in depth)

Even without the sandbox, agents MUST use project-scoped installs:
- **NEVER** use `nix profile install`, `npm install -g`, `uv tool install`, `pip install` (global), or `curl | sh`
- **ALWAYS** add tools to the project's `flake.nix` devShell
- **ALWAYS** use `--ignore-scripts` for npm/pnpm/yarn installs (e.g. `npm install --ignore-scripts`). Then run `npm rebuild <pkg>` only for packages that need native compilation (e.g. `esbuild`, `sharp`, `better-sqlite3`). This blocks postinstall-based supply chain attacks.
- **For pip**: prefer installing from wheels (`pip install --only-binary :all:`) when available, which skips `setup.py` execution. Fall back to source builds only when no wheel exists.
- The sandbox enforces this at the OS level — global install paths are not writable

## .gitignore management

**After every phase that produces or defines new artifacts**, ensure the project's `.gitignore` is up to date. This is not a one-time setup — re-evaluate on every phase transition.

### When to run

Check and update `.gitignore` after completing **any** of these phases:
- **Phase 0 (install/init)** — create the initial `.gitignore` with baseline entries
- **Phase 2 (specify)** — if the spec introduces new artifact types (e.g. generated files, dev certs)
- **Phase 5 (plan)** — the plan may define build output dirs, codegen targets, database files, etc.
- **Phase 6 (tasks)** — if tasks reference new directories (e.g. `validate/`, custom output dirs)
- **Phase 7 (implement)** — re-check after implementation adds runtime artifacts

### How to run

1. Read the current `.gitignore` (or note it doesn't exist yet)
2. Compute the required entries based on what's been decided so far (see baseline + conditional below)
3. Merge: add any missing entries, never remove entries the user added manually
4. Write the updated `.gitignore` if it changed
5. If entries were added, briefly tell the user what was added and why

### Baseline entries (always present)

```gitignore
# Spec-kit / agent artifacts
test-logs/
logs/
validate/
attempts/
ci-debug/
BLOCKED.md

# Environment
.env
.env.local
.env.*.local

# Direnv
.direnv/

# Editor / OS
.DS_Store
*.swp
*~

# Python
__pycache__/
*.pyc
.venv/
venv/

# Node
node_modules/
dist/
```

### Conditional entries (add when relevant)

| Condition | Entries to add |
|-----------|---------------|
| Nix/flakes in use | `result` (nix build output symlink) |
| Security baseline (any preset except poc) | `*.pem`, `*.key`, `credentials.json` |
| Build output dir defined in plan | The specific dir (e.g. `build/`, `out/`, `.next/`) |
| Codegen at build time | The generated dir (e.g. `src/generated/`) |
| Database files (SQLite, etc.) | `*.sqlite`, `*.sqlite3`, `*.db` |
| Coverage reports | `coverage/`, `.nyc_output/`, `htmlcov/` |
| Docker | `.docker/` |
| Custom dev certs | `certs/` or wherever they're stored |

### Interaction with presets

- **poc**: Baseline only — skip security and infrastructure entries
- **local/public/enterprise**: Baseline + all conditional entries that apply based on interview decisions

## Quick reference

| Phase | Command | What it does |
|-------|---------|--------------|
| 0 | `specify init <name>` | Scaffold project with slash commands |
| 1 | `/speckit.constitution` | Define governance principles & architectural rules |
| 2 | `/speckit.specify` | Write a structured feature specification |
| 3 | `/speckit.clarify` | Identify and resolve ambiguities in specs |
| 4 | `/speckit.analyze` | Validate spec consistency (loops until clean) |
| 5 | `/speckit.plan` | Generate technical implementation plan |
| 6 | `/speckit.tasks` | Break plan into actionable task list |
| 7 | `/speckit.implement` | Execute tasks with TDD, phased ordering |
| 8 | `/speckit.checklist` | Quality assurance checklists |
| 9 | `/speckit.taskstoissues` | Convert tasks to GitHub Issues |

---

## Workflow: detect phase, load phase file, execute

### Step 1: Ensure spec-kit is installed and project exists

Read and follow `phases/install.md`.

### Step 2: Detect current state and guide the user

**Use glob/ls to check** which artifacts exist in the project. Work backwards from the most advanced phase:

| Check (in this order) | Location | If exists → | If missing → |
|----------------------|----------|-------------|-------------|
| Task list | `specs/*/tasks.md` or `tasks.md` | Ready for Phase 7 (implement) | Check for plan |
| Plan | `specs/*/plan.md` or `plan.md` | Ready for Phase 6 (tasks) | Check for spec |
| Feature spec | `specs/*/spec.md` | Check for `[NEEDS CLARIFICATION]` tags → Phase 3 (clarify), then Phase 4 (analyze loop) → once clean, Phase 5 (plan) | Check for constitution |
| Constitution | `.specify/memory/constitution.md` | Ready for Phase 2 (specify) | Start with Phase 1 (constitution) |
| Interview notes | `specs/*/interview-notes.md` | Resume from where interview left off | Fresh project — start interview |

Also check for `learnings.md` (from prior features) — if it exists, read it for cross-feature context.

Present the user with their current state and next recommended step.

### Step 3: Execute the phase

**Load only the relevant phase file:**

| Phase | File to load |
|-------|-------------|
| Install/init | `phases/install.md` |
| Constitution (Phase 1) | Read `.specify/commands/constitution.md` template directly. Sets architectural rules — 9 "articles" covering library-first design, test-first development, simplicity, etc. Optional but recommended. If the user already has strong opinions about architecture, capture them here. |
| Specify (Phase 2) | `phases/interview.md` |
| Clarify (Phase 3) | Read `.specify/commands/clarify.md` template directly. Scans for ambiguities across 11 categories, generates up to 5 prioritized questions presented one at a time, integrates answers back into the spec. |
| Analyze (Phase 4) | Read `.specify/commands/analyze.md` template directly. **Mandatory and looping** — see below. |
| Plan (Phase 5) | `phases/plan.md` |
| Tasks (Phase 6) | `phases/tasks.md` |
| Implement (Phase 7) | `phases/implement.md`. Note: spec-kit's built-in `/speckit.implement` runs in a single context and will hit limits on larger projects — use the parallel runner instead. |
| Checklist (Phase 8) | Read `.specify/commands/checklist.md` template directly |

For each phase:
1. Tell the user which phase you're running and why it's next
2. Load the phase file (or command template for simple phases)
3. Follow its instructions exactly
4. **Update `.gitignore`** if this phase is listed in the gitignore management section above
5. After completing the phase, summarize what was produced and **automatically proceed to the next phase** (see auto-advance below)

**Reference files are loaded on demand by the phase files** — they tell you which reference to load and when. Never preload all references.

### Auto-advance between phases

After completing any phase, **automatically start the next phase** without waiting for the user to ask. The one exception: **never auto-start Phase 7 (implement)**. Instead, summarize what's ready and ask the user to confirm before launching the implementation runner.

The full auto-advance chain: constitution → specify → clarify → **analyze loop** → plan → tasks → **stop and confirm** → implement.

### Phase 4 (analyze) — mandatory loop until clean

Phase 4 is **not optional**. After clarify (Phase 3) completes — or whenever a spec exists without `[NEEDS CLARIFICATION]` tags — run the analyze phase. This is a loop:

1. Read `.specify/commands/analyze.md` and execute it against the spec
2. If the analysis finds ambiguities, inconsistencies, or gaps:
   - Present the findings to the user
   - Resolve each issue (update the spec, ask the user, or clarify inline)
   - **Run analyze again** on the updated spec
3. Repeat until the analysis comes back clean — no ambiguities, no inconsistencies, no gaps
4. Only then proceed to Phase 5 (plan)

There is no iteration cap. The spec must be unambiguous before planning begins. Each iteration should get shorter as issues are resolved. If the same issue keeps recurring across iterations, flag it to the user as a potential design decision that needs an explicit call.

---

## Learnings management

The `learnings.md` file accumulates discoveries across tasks. The parallel runner manages its size automatically:

- **Phase-based filtering**: Each agent receives only learnings from its phase and upstream dependencies (not the full file).
- **Auto-pruning**: After each main-loop iteration, the runner removes learnings for tasks in phases that are fully validated AND have no pending downstream dependents. This keeps the file focused on active/upcoming work.
- **Concise entries**: Agents are instructed to write max 3 bullet points per task, focusing on non-obvious gotchas only.

No manual intervention is needed — the file shrinks naturally as phases complete.

---

## Interaction style

- **Be a guide, not a lecturer.** Explain just enough for each step, then do it.
- **Propose, don't interrogate.** Make concrete suggestions based on what you know.
- **Show progress.** After each phase, summarize what exists and what's next.
- **Respect the workflow order** but don't be rigid — if the user wants to skip, let them.
- **Read the command templates.** Always read the relevant `.specify/commands/` template before executing a phase.

---

## Rules

- Always check for an existing `.specify/` directory before running `init`.
- Never modify spec-kit's generated command templates in `.specify/commands/`.
- Read the relevant command template before executing each phase.
- If a phase produces output files, verify they were created successfully.
- If `specify init` fails, check Python version (needs 3.11+) and `uv` availability.
- The `--ai claude` flag configures spec-kit for Claude — always use it during init.
