# Resumption prompt — spec-kit wrapper audit

Paste the section between the `---BEGIN---` and `---END---` markers into a new Claude Code conversation to resume.

---BEGIN---

I'm resuming a conversation about auditing my spec-kit wrapper + parallel runner system. Here's the full context.

## What the system is

- **spec-kit wrapper** at `/home/max/git/agent-framework/skills/spec-kit/` — drives agents through Specification-Driven Development (constitution → specify → clarify → analyze → plan → workflows → tasks → implement). Has 6 presets (poc / local / library / extension / public / enterprise) that override interview/plan/task depth.
- **parallel runner** at `parallel_runner.py` (19,737 LOC, monolithic) — spawns Claude CLI subprocesses to execute `tasks.md` with phase dependencies, parallel `[P]` tasks, fix-validate loops at phase boundaries, separate validate (Sonnet) and review (Opus) agents, runner-side independent test re-execution (`runner-verified.json`), proof-discipline gates (`verification.json`), CI/E2E loops with their own sub-agent flows.
- **cost_report.py** — post-hoc cost analyzer reading `run-log.jsonl`.
- **41 reference docs** in `reference/*.md` that phase docs and runner prompts load on demand.

## What we did this session

1. **Two parallel audits**:
   - `/tmp/spec-kit-audit-runner.md` (986 lines) — `parallel_runner.py` + `cost_report.py`. Architecture, every embedded agent prompt, code-enforced guardrails, failure handling, cost controls, observability, anti-fake-work mechanisms, smells.
   - `/tmp/spec-kit-audit-reference.md` (1,089 lines) — every rule in `reference/*.md` with location, enforcement tag, overlaps, contradictions, gaps relative to my goals.

2. **Built the rule matrix** at `/tmp/spec-kit-rule-matrix.md` (~250 rules across 27 sections). Every rule tagged with:
   - **Enforcement strength**: CODE / TEMPLATE / CI / VALIDATOR / PROMPT / CONVENTION
   - **Rationalization payoff**: HIGH / MED / LOW / NEG (how much work skipping saves the agent)
   - **Preset applicability**: ALL / NON-POC / PROD / ENT / PLATFORM / CONDITIONAL

   Plus sections on contradictions, gaps, structural observations, and a preset-behavior cross-reference table.

## What I told Claude my goals are

- Ship production-quality code unattended
- Reduce time per feature
- Enforce a quality bar agents wouldn't self-impose
- Cost-controlled scaling

## What I told Claude my pain points are

- Agents claim done when they aren't
- Rules ignored or contradictory
- Cost / token waste
- Specifically: agents rationalizing the least amount of work possible

## What we figured out together

The conversation went through several drafts before landing on the right framing:

- **Round 1** — Claude tried to propose a "principle layer" on top of everything. I pushed back: too many rules to limit, can't be principle-only.
- **Round 2** — Claude tried to add scope (core / planning / execution) to each principle. I pushed back: not all rules are principles; many are preferences or tactics.
- **Round 3** — Claude tried a three-layer principle/preference/tactic taxonomy. I told it to stop blowing smoke and pushed back: docs reorganization without fixing the actual broken stuff is decorating a half-finished house. Claude agreed.
- **Round 4** — Claude proposed three artifacts (audit findings + enforced-rules doc + improvement backlog). I said the system *feels* like it's lacking rigor — meh instead of good. Claude responded with three concrete moves: (1) fix the runner bugs the audit found, (2) make boundaries explicit so it's clear what enforces what, (3) build the missing primitives (aggregate budget cap, wrapper-script linter, schema-vs-parser drift detector, etc.).
- **Round 5** — I said presets are good but the runner is preset-blind; the runner treats every preset like enterprise. Claude agreed and proposed making presets a project-lifetime contract that both the wrapper AND the runner respect.
- **Round 6** — I said the lying problem is specifically agents rationalizing minimum work. Claude reframed: this isn't "more E2E," it's that "what counts as done" is too loose — the agent reads task descriptions, finds the smallest defensible interpretation, stops there.
- **Round 7** — I said I want the inventory so we can think about things in a new way. Claude built the matrix.

## Key structural findings (from the matrix)

1. **Bimodality**: ~80 CODE-enforced rules vs. ~110 PROMPT-enforced rules. The CODE side works; the PROMPT side gets rationalized.
2. **The HIGH-payoff × PROMPT cells are where the system loses** — rules that save agents hours of work AND have no machinery behind them. These cluster in: testing tier discipline, real-runtime E2E, no-bypass-in-release, behavioral regression tests, user-flow integration tests, adversarial flow tests, no-mocks-inside-tier, "done when" must pin exact names.
3. **The runner has the data to catch most rationalization but doesn't use it**: stream-json log has every tool call (could verify `mcp_interactions`), git diff is available (could verify `files_modified`), proof artifacts exist (but project-side wrappers can fake them).
4. **Presets affect authoring (wrapper) but not runtime (runner)** — a poc runs through the same fix-validate/review/verify machinery as enterprise.
5. **Concrete bugs the runner audit found** (line numbers in `/tmp/spec-kit-audit-runner.md`):
   - Pricing tables disagree 3× between `parallel_runner.py:3741-3745` and `cost_report.py:38-57`
   - No aggregate budget kill-switch
   - Connection-error retry has no upper bound
   - Implementer prompt contradicts itself: line 1834-1835 allows marking complete after connection error, line 1897 forbids it without exit-0
   - `[SECURITY] Stripping capabilities` only logs to stderr; agent doesn't see it; loops forever
   - IC-AGENT-016 numbered twice in `agent-file-schemas.md:460` and `:640`
   - `MAX_VR_FIX_ATTEMPTS=5` declared twice (lines 11139 and 11265)
   - `subprocess.run(..., timeout=600)` for runner-verify blocks the main thread
   - `_run_feature` is ~1,800 LOC inside a ~9,800 LOC class

## Where we landed

The matrix is the foundation. The next conversation should pick up at "what do we do with the matrix?" Options we discussed but didn't decide between:

- **Option A — Fix the runner bugs first**. Bounded, concrete, gives the system a clean foundation before any restructuring.
- **Option B — Build mechanical enforcement for the top HIGH×PROMPT rules**. Higher leverage but each one is real engineering work (diff-vs-claim verifier, stream-log-vs-claim verifier, wrapper-script linter, UI_FLOW-vs-code drift detector).
- **Option C — Make presets affect runtime behavior**. Structural change to the runner; requires a config layer (`cost-config.json` exists but only covers executor caps + role models). Would mean defining each preset's authoring contract + execution contract + verification contract.
- **Option D — Demote MANDATORY voice in prose-only rules**. Smallest move; just an editing pass across `reference/*.md` to align voice with what's actually enforced. Wouldn't change behavior but would make the system more honest.

I haven't picked. Read the matrix first (`/tmp/spec-kit-rule-matrix.md`), then help me decide between (or sequence) these.

## Important context Claude should know

- **The audits are exhaustive but not the rule matrix's reads section** — section 27 has 30 structural observations, but we agreed I'd want as many as the data justifies, not capped.
- **I dislike Claude agreeing too readily.** Earlier in the session I told Claude to stop blowing smoke. If you're agreeing with me, justify it from the data.
- **Don't propose a "principle layer"** — we already worked through why that's not the right move. The matrix IS the layer.
- **The presets stay**. Don't propose removing or replacing them. Preset-aware runner is a goal; preset elimination is not.
- **My system grew organically from nothing** — I built it solo. Some of the smells are growth artifacts, not architectural mistakes. Be specific about which is which.
- **The auto-memory system is disabled for the kanix repo** (per `/home/max/git/kanix/CLAUDE.md`) — don't write to `~/.claude/projects/-home-max-git-kanix/memory/`.

## Files to read at the start of the resumed conversation

1. `/home/max/git/agent-framework/revision/spec-kit-rule-matrix.md` — the matrix (primary)
2. `/home/max/git/agent-framework/revision/spec-kit-audit-runner.md` — runner audit (for line-number citations)
3. `/home/max/git/agent-framework/revision/spec-kit-audit-reference.md` — reference audit (for cross-file citations)
4. `/home/max/git/agent-framework/skills/spec-kit/README.md` — for the canonical system overview
5. `/home/max/git/agent-framework/skills/spec-kit/parallel_runner.py` — only as needed for specific line numbers

Don't re-read everything; the matrix and the two audit docs have the citations.

## Starting question for the resumed conversation

After reading the matrix, propose a sequenced plan that decides between options A/B/C/D above (or combines them). Justify the sequence from the matrix data — specifically, point to which rows or sections support each step's leverage. Don't propose new abstractions; build on what we already have.

---END---
