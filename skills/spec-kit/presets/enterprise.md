# Preset: Enterprise

**Goal**: Production-grade, multi-user, fully hardened. This is the default SKILL.md behavior — no overrides.

## Interview phase overrides

**None** — ask about everything on the topic checklist. All enterprise infrastructure decisions are mandatory. Secure by default — warn on every skip. This includes:
- Branching strategy (default: feature branches with PRs, ask about naming convention and merge strategy)
- DX tooling (full scope: one-command dev, complete script inventory, dev server with HMR/proxy/HTTPS certs, environment isolation, codegen pipeline, debugging configs for VS Code + JetBrains, `clean:all`, CLAUDE.md development section)

## Spec phase overrides

**None** — all SKILL.md requirements apply:
- FR/SC numbering required
- Full Enterprise Infrastructure section
- Full Edge Cases & Failure Modes section
- Full Testing section (unit, integration, contract, e2e, security)
- Security warnings on every skip

## Plan phase overrides

**None** — all SKILL.md requirements apply:
- Phase 1 Test Infrastructure (custom reporter, structured output, test-logs/)
- Phase 2 Foundational Infrastructure (logging, error hierarchy, config, graceful shutdown, health checks, CI/CD, security scanning, observability)
- Full research.md with rationale and rejected alternatives
- Full data-model.md with ERDs, field tables, state transitions, cross-entity constraints
- Full API contract depth
- Complexity Tracking table
- Phase Dependencies with dependency graph and parallelization strategy

## Task phase overrides

**None** — all SKILL.md requirements apply:
- Fix-validate loop per phase
- `[P]` parallel markers
- FR/Story traceability on every task
- learnings.md
- Full approach note with fix-validate loop description

## New sections (apply in full)

All new spec-kit sections apply at full depth for enterprise:
- **Non-Goals section**: required in spec — exhaustive intentional omissions with rationale
- **Examples on FRs**: mandatory on any FR flagged during analyze; encouraged on all FRs for clarity
- **Operational workflows**: required in interview — day-1 setup, day-2 ops, failure recovery, admin processes
- **Test plan matrix**: required in plan — every SC-xxx mapped to test tier, fixture, assertion, infrastructure
- **Runtime state machines**: required if project has daemons, protocols, or connection management
- **Interface contracts**: required — `reference/interface-contracts.md` defines format, `[produces/consumes: IC-xxx]` tags on all tasks that share state
- **Critical path (user perspective)**: required — day-1 flow, phase mapping, incremental checkpoints
- **Done criteria on tasks**: required — verifiable, additive, 1-3 bullets per task
- **Spec amendment process**: full — AMENDMENT files, ADR-style spec updates, rework evaluation

## Summary

This preset exists for completeness. When a user picks "enterprise", just follow SKILL.md as written — every section, every MANDATORY tag, every requirement. No shortcuts.
