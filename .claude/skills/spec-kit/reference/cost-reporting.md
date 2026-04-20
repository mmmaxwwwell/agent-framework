# Cost & Effectiveness Reporting

The parallel runner logs every agent completion to `{spec_dir}/run-log.jsonl` with enough detail to compute actual dollar cost after the fact. The `cost_report.py` script aggregates those logs into a human-readable markdown report plus a machine-readable JSON summary.

## What gets logged per agent

Every `task_complete` and `vr_complete` event in `run-log.jsonl` includes:

| Field | Meaning |
|---|---|
| `task_id` | The task or sub-agent identifier (e.g. `T042`, `E2E-executor-3-2`, `VR-phase-3-1`) |
| `agent_id` | Monotonic counter across the run |
| `status` | `done` / `failed` / `rate_limited` / etc. |
| `exit_code` | Process exit code |
| `duration_s` | Wall-clock seconds |
| `model` | The model observed serving the agent (`claude-opus-4-7`, `claude-sonnet-4-6`, etc.). Missing → assumed Opus (legacy default before 2026-04-19). |
| `input_tokens` | Flat total (legacy, kept for backwards compatibility) |
| `output_tokens` | Output tokens |
| `input_tokens_fresh` | Non-cached input tokens |
| `input_tokens_cache_read` | Cache hits — cheapest bucket (~10% of input rate) |
| `input_tokens_cache_create` | Cache writes — 1.25× input rate |

The breakdown fields are added as of 2026-04-19. Events before that only have the flat `input_tokens` field; the reporter treats those as "legacy" and prices them at the fresh-input rate (conservative — no cache discount applied retroactively).

## Running the reporter

`cost_report.py` lives alongside `parallel_runner.py` in the skill directory. It's stdlib-only; no pip install needed.

```bash
# Report on a single feature
python3 /path/to/.claude/skills/spec-kit/cost_report.py /path/to/project/specs/admin/run-log.jsonl

# Report on every feature in a project
python3 /path/to/.claude/skills/spec-kit/cost_report.py --all /path/to/project/specs

# Combine runs from multiple projects (lifetime cost of the framework)
python3 /path/to/.claude/skills/spec-kit/cost_report.py \
  --all /path/to/project-a/specs \
  --all /path/to/project-b/specs

# Write to custom paths; skip stdout
python3 cost_report.py --output cost.md --json-output cost.json --no-display <log>
```

Default outputs: `cost-report.md` (display) and `cost-report.json` (machine-readable). Both go to the current working directory.

## What the report contains

The markdown report has five sections:

1. **Grand total** — events processed, agent completions, total tokens (split in/out), estimated dollar cost, total agent wall-clock time.
2. **Cost & tokens by model** — one row per model family (opus/sonnet/haiku) with event count, input buckets (fresh / cache_read / cache_create), output, total tokens, cost, and % of spend.
3. **Cost & tokens by phase** — task-id prefix buckets (`task`, `validate-review`, `e2e-planner`, `e2e-executor`, `e2e-fix`, etc.) ranked by cost. Useful for spotting the expensive phases.
4. **Phase × model matrix** — shows where each model is actually being used. Validates that model-choice changes landed (e.g., that `e2e-verify` is on Sonnet after the switch).
5. **Effectiveness signals** — computed heuristics specific to the E2E loop:
   - Planner+executor cost vs. legacy explore baseline (for comparing the split refactor against prior runs)
   - Fix vs. verify spend split
   - **Executor Opus%** — target 0% (executor should run on Sonnet)
   - **Verify Opus%** — target 0% after 2026-04-19

Plus footnotes calling out how much of the data is legacy (missing model / missing cache breakdown), so you know how trustworthy the numbers are.

The JSON output (`cost-report.json`) is the same data in structured form for scripting.

## When to run it

- **After a feature finishes implementing** — measures what the feature actually cost to build
- **Periodically across all features** — tracks lifetime spend on the framework
- **After changing model selection** (e.g., moving verify from Opus to Sonnet) — validates the change reduced cost without a regression in task completion rate
- **Before a cost discussion** with users / stakeholders — gives them real numbers, not estimates

## Pricing

Prices in the script are public Anthropic rates as of April 2026 and live at the top of `cost_report.py` in the `PRICING` dict. If Anthropic rates change, edit that dict — everything downstream recomputes.

Per-family rates (USD per 1M tokens):

| Family | Input | Cache read | Cache create | Output |
|---|---:|---:|---:|---:|
| Opus | $15.00 | $1.50 | $18.75 | $75.00 |
| Sonnet | $3.00 | $0.30 | $3.75 | $15.00 |
| Haiku | $0.80 | $0.08 | $1.00 | $4.00 |

## Legacy-data policy

Two rules keep the reporter honest on old logs:

1. **Missing `model` field → assumed Opus.** This matches the default before the `model` field was added. Every pre-2026-04-19 event is treated as Opus and counted at Opus rates.
2. **Flat `input_tokens` only → priced as fresh input.** Without the cache breakdown there's no way to tell retroactively how many input tokens were cache hits. Pricing everything as fresh is conservative (upper bound on cost).

Both cases trigger a warning footnote in the report so the ambiguity is visible.

## How to interpret the numbers

- **If verify shows > 0% Opus after the 2026-04-19 change**: run was done against an older `parallel_runner.py` that hadn't been updated, OR the runner was launched before the model change landed. Check the `run-log.jsonl` timestamps.
- **If planner+executor combined ≥ legacy explore**: the E2E split isn't saving money yet — likely because executor is re-running the plan on every spawn (check handoff protocol) or planner is producing bloated plans.
- **If `task` (regular implementation) dominates total cost**: the E2E-focused optimizations don't help much. The next leverage point is moving ordinary task execution to a cheaper model for appropriate tasks.
- **If a phase's "avg $/event" is > 10× the others**: something in that phase is running away. Look at the raw `run-log.jsonl` entries for that phase and check `duration_s` and token counts per event.

## Integration with the workflow

Running `cost_report.py` is not part of the autonomous runner loop — it's an explicit post-hoc analysis step. The intended flow:

1. Runner finishes a feature (or you pause it).
2. You (or a supervisor agent) run the reporter: `python3 cost_report.py --all specs/`.
3. Read the effectiveness signals section. Are the expected Sonnet phases actually on Sonnet? Is any phase consuming more than its share?
4. If something looks wrong, fix it in `parallel_runner.py` (wrong model string, prompt bloat, missing cache-control) and re-run the reporter on subsequent runs to confirm the fix landed.

The reporter is read-only — it never modifies logs or the runner. It's safe to run mid-feature if you want a snapshot of spend so far.
