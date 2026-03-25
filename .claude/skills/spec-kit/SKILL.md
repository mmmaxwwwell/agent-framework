---
name: spec-kit
description: Initialize and drive a spec-kit (Specification-Driven Development) project using the `specify` CLI. Handles install, init, and walks the user through the full SDD workflow — constitution, specify, clarify, plan, tasks, implement. Enforces end-to-end integration testing with real server implementations, structured agent-readable test output, and a fix-validate loop after every feature. Use when the user wants to start or continue a spec-kit project.
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
  testing.md         # Integration testing, structured output, stub processes, fix-validate loop
  logging.md         # Structured logging spec
  errors.md          # Error hierarchy, propagation
  config.md          # Config management
  security.md        # Security baseline, scanning tiers, headers
  shutdown.md        # Graceful shutdown
  health.md          # Health checks
  rate-limiting.md   # Rate limiting & backpressure
  observability.md   # Metrics, tracing
  migration.md       # Migration & versioning
  cicd.md            # CI/CD pipeline
  dx.md              # Developer experience tooling
  ui-flow.md         # UI_FLOW.md spec
  data-model.md      # Data model depth
  api-contracts.md   # API contract depth
  traceability.md    # FR numbering, SC, learnings format
  idempotency.md     # Idempotency & readiness checks
  edge-cases.md      # Edge case enumeration
  complexity.md      # Complexity tracking
  phase-deps.md      # Phase dependencies & parallelization
presets/             # Quality presets — loaded once per project
  poc.md             # Proof of concept
  local.md           # Single-user local tool
  public.md          # Single-user public-facing
  enterprise.md      # Multi-user production
```

## Project preset — PICK FIRST

Before doing anything else, determine the project's quality preset. This controls how many questions you ask, which infrastructure you include, and how heavy the process is. **Ask the user to pick one** (or detect from context if they already stated it):

| Preset | Use when | Questions | Infrastructure |
|--------|----------|-----------|---------------|
| **poc** | Throwaway prototype, speed over everything | 3-5 | None — console.log, hardcoded config, no auth/tests/CI |
| **local** | Single-user local tool (CLI, desktop, dev tooling) | 5-10 | Light — error handling, config, basic tests |
| **public** | Single-user but internet-exposed | 8-12 | Medium — security headers, input validation, rate limiting, CI |
| **enterprise** | Multi-user, production, team-maintained | Exhaustive | Full — everything in the reference files |

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
4. After completing the phase, summarize what was produced and **automatically proceed to the next phase** (see auto-advance below)

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
