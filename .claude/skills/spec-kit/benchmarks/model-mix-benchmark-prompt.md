# Benchmark: Model Mix Cost vs Quality

## Goal

Compare three configurations of the spec-kit parallel runner across the same task set, measuring code quality and token cost:

| # | Architecture | Planner | Executor | Projected Cost | Savings | Label |
|---|---|---|---|---|---|---|
| 1 | Single agent | Opus | — | $195.50 | — | baseline |
| 2 | Single agent + filtered context | Opus | — | $173.00 | 12% | filtered |
| 3 | Planner + sub-agents | Opus | Opus | $109.00 | 44% | opus-split |
| 4 | Planner + sub-agents | Opus | Sonnet | $56.12 | 71% | hybrid |
| 5 | Planner + sub-agents | Sonnet | Sonnet | $21.82 | 89% | full-sonnet-split |
| 6 | Single agent (no split) | Sonnet | — | $39.10 | 80% | sonnet-only |

Projected costs are based on analysis of 29 completed tasks (870 API messages, 86.6M tokens) from the nix-key project at API rates. The original projections used Opus rates of $15/$75/$18.75/$1.875 per M for input/output/cache-create/cache-read; Sonnet at $3/$15/$3.75/$0.375.

**Note (2026-04-20):** Opus rates at standard ≤200K context have been corrected to $5/$25/$6.25/$0.50 per M. The Opus-heavy configs (1, 2, 3) in the table above are overstated by ~3×; actual cost is roughly one-third of the listed dollar amount. The hybrid and full-sonnet configs (4, 5, 6) are largely unaffected (Sonnet rates unchanged). See `reference/cost-reporting.md` § Pricing for current rates; re-run `cost_report.py` on any existing `run-log.jsonl` to get corrected totals.

**Minimum benchmark set**: Configs 1 (baseline), 4 (hybrid), and 5 (full-sonnet-split). Config 2 is already implemented. Configs 3 and 6 are optional if time permits.

## What I need you to do

Design a benchmark plan that will let me run all three configurations against the same tasks and compare the results. Here are the constraints and context:

### Context

- The runner is at `~/.claude/skills/spec-kit/parallel_runner.py`
- It spawns `claude` CLI processes with `--model opus` (hardcoded in `spawn_agent()`)
- The planner/sub-agent split doesn't exist yet — it needs to be implemented first
- The filtering optimization (inline tasks.md + learnings.md) is already merged
- The project being tested is `nix-key` — a Go project with ~45 tasks across 10 phases
- Phases 1-4 are already complete. Remaining tasks: T021-T027 (phases 5-6) plus later phases
- Current cost for 29 completed tasks (all Opus): ~$195 equivalent in tokens
- I'm on the $200/mo Claude Max plan so cost is measured in token-equivalents, not actual dollars

### What the plan needs to cover

1. **Implementation work required** — what changes to `parallel_runner.py` to support:
   - Planner/sub-agent task decomposition (Opus plans, sub-agents execute)
   - Configurable model per role (planner vs executor)
   - Per-run token tracking built into the runner (not post-hoc log parsing)

2. **Benchmark task selection** — pick a set of tasks that:
   - Are representative (mix of implementation, testing, wiring)
   - Can be run 3 times independently (once per config)
   - Are not yet complete (or can be reset via git)
   - Are complex enough to show quality differences

3. **Quality metrics** — how to objectively compare output across configs:
   - Compilation success (does it build?)
   - Test pass rate (do tests pass on first run?)
   - Code review findings (lint warnings, security issues, style violations)
   - Completeness (did it implement everything the task asked for?)
   - Learnings quality (did the agent record useful discoveries?)
   - Number of fix-validate cycles needed per phase

4. **Cost metrics** — per config:
   - Total tokens by category (input, output, cache create, cache read)
   - Cost at API rates (for apples-to-apples comparison even on subscription)
   - Wall-clock time
   - Number of agent spawns
   - Average conversation length (turns per agent)

5. **Execution plan** — step by step:
   - How to isolate each run (git worktrees? branches?)
   - How to ensure identical starting state
   - How to collect and compare results
   - What to do if a config fails mid-benchmark

6. **Risk mitigation**
   - What if Sonnet can't complete certain tasks that Opus can?
   - What if the planner produces bad plans that waste sub-agent runs?
   - How to handle non-determinism (different tasks may be easier/harder by chance)

### Output format

Give me a concrete, numbered implementation plan I can hand to Claude Code to execute. Each step should be specific enough to act on. Include the specific files to modify, functions to add, and CLI commands to run.
