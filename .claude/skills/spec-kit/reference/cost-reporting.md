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

Prices in the script are public Anthropic rates as of 2026-04-19 for the Claude 4.x family at standard ≤200K context. The harness spawns agents via `--model opus|sonnet|haiku` with no 1M-context flag, so these are the rates that apply to every run. They live at the top of `cost_report.py` in the `PRICING` dict. If Anthropic rates change, edit that dict — everything downstream recomputes.

Per-family rates (USD per 1M tokens):

| Family | Input | Cache read | Cache create | Output |
|---|---:|---:|---:|---:|
| Opus | $5.00 | $0.50 | $6.25 | $25.00 |
| Sonnet | $3.00 | $0.30 | $3.75 | $15.00 |
| Haiku | $1.00 | $0.10 | $1.25 | $5.00 |

Historical note: Opus rates were corrected on 2026-04-20 from the original entries ($15 / $1.50 / $18.75 / $75 per M). Cost reports generated before that date overestimate Opus spend by 3× at standard context; re-run the reporter on existing `run-log.jsonl` files to get corrected totals.

## Prompt-caching strategy

The runner spawns each agent as a fresh `claude` CLI process. The agent's instructions are written to a per-agent prompt file (`logs/agent-N-<task>.log.prompt.md`) that the agent Reads as its first tool call. **The path of that prompt file is unique per spawn**, so any content inlined into the prompt body lives at a per-spawn path and gets no cache benefit across spawns.

The cache mechanism that actually works for cross-spawn agents is **Claude Code's Read tool result cache**: when two agents Read the same absolute file path with identical content within the 5-minute cache TTL window, the second Read is a cache hit (priced at ~10% of fresh input). The runner is structured around this:

1. **Reference content is NEVER inlined into prompt bodies.** Instead, each prompt builder emits a "Required reading" (Tier 1) block listing absolute paths to reference files, and a "Reference index" (Tier 2) pointer to `reference/index.md` for on-demand lookups. The agent Reads each file by path. See `_required_reads_block` and `_reference_index_pointer` in `parallel_runner.py`, plus the "Two-tier prompt loading" section of the README.
2. **Reference file paths are stable across spawns.** They're computed once at module scope from `__file__` (`_REF_DIR = Path(__file__).parent / "reference"`). The same role spawned twice produces a Tier-1 block with byte-identical paths, so spawn 2's Read of `reference/testing.md` hits cache_read on spawn 1's Read.
3. **Per-attempt diagnostics go in the variable tail.** Logs, attempt numbers, claim file lists, process tree snapshots — these all live in the role-specific tail of the prompt body. They don't matter for cross-spawn caching (the prompt-file Read is uncached anyway), but they shouldn't be in the stable Tier-1/Tier-2 blocks either, for clarity.
4. **Tier-1 path lists are literal per role.** The list is hardcoded in each prompt builder (e.g., e2e-fix's Tier-1 is always `[fix-agent-playbook.md, e2e-failure-patterns.md]`). Don't generate the list from runtime state unless the result is byte-stable across all spawns of that role.

Cache hit rates observed: fix-agents in a multi-attempt platform-init loop routinely hit 95–98% cache_read on the reference content (playbook ~11KB, patterns library ~13KB, index ~5KB). The first agent in a fresh 5-min cache window pays cache_create on each file's Read; subsequent agents pay cache_read on the same paths. A 10-attempt platform-fix loop therefore costs ~$0.10–$0.30 in cached reference-content reads, not ~$5–$10 of inlined cache_create on every spawn.

What this costs you if you're not careful:

- **Inlining reference file content into a prompt builder f-string.** This was the previous strategy and was wrong: the bytes live in a per-spawn prompt file path, so they're never cache-shared. Always pass paths.
- **Per-spawn variability in Tier-1 paths.** If you build the path list from `task.capabilities` or any per-spawn state, two spawns may get different paths and lose the cross-spawn cache. Keep the list literal per call site.
- **Editing a referenced file mid-run.** If a fix-agent edits `reference/testing.md` (it shouldn't), the next agent's Read sees different content and pays cache_create instead of cache_read. The reference dir should be treated as immutable during a feature run.
- **Per-attempt content in the Tier-1/Tier-2 blocks.** Putting `attempt: 3` in the Tier-1 header doesn't break cross-spawn cache (the prompt body itself isn't cached), but it confuses the role/cache mental model. Keep variable content in the role-specific tail.

When adding new reference content: put it in a new file under `reference/`, add a row to `reference/index.md`, and add the path to the relevant role's `_required_reads_block` call (if mandatory) or rely on the index for opt-in reads. **Do not inline.**

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
