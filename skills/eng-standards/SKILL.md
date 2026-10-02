---
name: eng-standards
description: A standards library — engineering rigor baselines (presets) plus a tag-indexed set of reference standards for testing, security, CI/CD, config, errors, logging, data models, APIs, and more. Use when implementing, fixing, planning, or reviewing code and you want to apply a consistent, opinionated engineering baseline. Pick a preset to set the rigor level for a project, then read the specific reference standards that match the task at hand. This is the standards content only — no workflow, no CLI, no runner.
---

# Engineering Standards

This skill is a **standards library**, not a workflow. It gives you two things:

1. **Presets** (`presets/`) — six rigor baselines. A preset answers "how much engineering rigor does *this project* warrant?" once, so you don't re-litigate logging/CI/security/testing scope on every task.
2. **Reference standards** (`reference/`) — ~26 topic files (testing, security, CI/CD, config, errors, logging, data-model, API contracts, etc.), each a concrete opinionated standard. A tag index (`reference/index.md`) maps a task to exactly the files worth reading.

The content was distilled from a spec-driven-development workflow. A few files still mention that workflow's roles or artifacts — **ignore that framing**; read each file for its engineering rules, which stand on their own.

## How to use it

### Step 1 — Establish the rigor baseline (once per project)

If the project's rigor level isn't already settled, pick a preset. Read `presets/<name>.md` and adopt its defaults. If it's ambiguous which fits, ask the user rather than guessing — the preset changes how much you build.

| Preset | When it fits |
|--------|--------------|
| `poc.md` | Prototype, speed over rigor. Skips infra/process overhead but keeps FR numbering + learnings so agents don't guess wrong. The *only* preset that trades rigor for speed. |
| `local.md` | Enterprise-grade rigor for single-user, non-networked local software. No auth/CORS/security-headers/rate-limiting. |
| `public.md` | Enterprise-grade rigor for single-user software exposed to the internet. Full security hardening (headers, input validation, rate limiting, sanitized errors), no multi-user auth. |
| `enterprise.md` | Production-grade, multi-user, fully hardened. The maximal baseline — no overrides. |
| `library.md` | A package published to a registry (npm/PyPI/crates). API surface, semver, backwards-compat, docs generation, multi-consumer. |
| `extension.md` | An extension inside a host platform (browser / VS Code / JetBrains). Sandbox, permissions, host-API churn, store review. |

Each preset spells out what to **skip**, what to **default without asking**, and what to **still ask about** — organized by phase (interview / spec / plan / task). Even outside a formal spec workflow, treat those as: what to leave out, what to include silently, and what to confirm with the user.

### Step 2 — Apply the right standards per task

For each task, open `reference/index.md`:

1. **Classify** the task — one task-kind tag (`task:implement`, `task:fix-bug`, `task:plan`, `task:review`, …) plus all applicable domain tags (`domain:api`, `domain:security`, `domain:test`, …).
2. **Look up** every index row whose tags intersect yours.
3. **Read** those reference files (cited section if named) and apply their rules.

`coding-behavior.md` is the universal floor — apply it to any implementation or fix work regardless of tags.

Don't read all of `reference/` up front. The index exists so you read 3–6 relevant files, not 26.

## What this skill is NOT

- **Not a workflow.** No `specify` CLI, no phases, no runner, no orchestration loop. If you want the full spec-driven-development machinery, use the `spec-kit` skill instead — this is its standards content, extracted to stand alone.
- **Not a code reviewer.** For reviewing a diff, use a `code-review*` skill. You *can* pull `security.md`, `testing.md`, etc. here to inform a review, but this skill doesn't drive one.

## Files

```
presets/     poc, local, public, enterprise, library, extension
reference/   index.md + 26 topic standards (testing, security, cicd, config,
             errors, logging, observability, data-model, api-contracts,
             migration, health, shutdown, idempotency, rate-limiting,
             interface-contracts, dx, nix-ci, pre-pr, readme, ui-flow,
             traceability, complexity, phase-deps, edge-cases, stripe,
             coding-behavior)
```
