You are designing an autonomous multi-agent execution system. Given a high-level task, produce three coordinated artifacts that together let an orchestrator agent execute the task with waves of parallel worker agents.

# Task to plan for

$ARGUMENTS

(If the above is empty or too vague to produce concrete subtasks, ask the user clarifying questions FIRST — do not generate speculative files.)

# Your output

Create these three files in the current working directory, in this order:

1. `tasks.md` — Task DAG with metadata for every subtask
2. `prompt.md` — The megaprompt itself: orchestrator instructions + one prompt template per worker role
3. `memory.md` — Empty seed for accumulated learnings (headers only; workers fill in as they go)

Then print a one-screen summary: total tasks, wave count, max parallelism per wave, and external prerequisites the user must satisfy before running the orchestrator (auth tokens, hardware access, credentials).

# Rules for tasks.md

Format every task as:

```
## T{id}: {imperative title}
- Status: pending
- Depends on: [T{id}, T{id}] or "none"
- Wave: {integer, assigned by grouping}
- Role: {worker role name from prompt.md}
- Deliverable: {exact file path or observable outcome}
- Verify: {command / file existence / property check the orchestrator can run to confirm}

### Brief
{1-3 paragraphs the worker will receive verbatim. Include exact file paths, line numbers, function names — no vague "the relevant module".}

### Success criteria
- {bulleted, independently testable}
- {every criterion mechanically checkable}
```

Rules:
- Each task self-contained enough to complete in one agent turn.
- Every dependency explicit; never rely on implicit ordering.
- Wave assignment: no-dep tasks → Wave 1; tasks depending only on Wave 1 → Wave 2; etc.
- Prefer many small tasks in early waves over a few large ones (higher parallelism).
- Two tasks in the same wave must NOT write to the same file.
- If a task can't be verified mechanically, redesign it until it can.

# Rules for prompt.md

Structure:

```
# Megaprompt: {task title}

## Orchestrator instructions

Loop until every task in tasks.md is Status=completed or blocked with no path forward.

### Per-iteration
1. Read tasks.md; find tasks with Status=pending AND all dependencies satisfied.
2. Group by Wave number — all tasks in the current wave dispatch concurrently.
3. For each task in the wave, spawn a worker via the Agent tool in parallel, using the role template below. Fill in {{task_id}}, {{brief}}, {{deliverable}}, {{success_criteria}}, {{verify}} from tasks.md.
4. When the wave returns, for each task:
   - Run the Verify check.
   - Pass → mark completed in tasks.md; append learnings to memory.md.
   - Fail → capture failure reason in tasks.md; retry once with a fresh agent; if it fails again, mark blocked.
5. Read memory.md before dispatching the next wave — it may contain corrections that change downstream tasks.
6. Print one-line status: "Wave N: X/Y ok, Z failed, K blocked".
7. Repeat.

### Quality gates
- Never mark completed without running the Verify check.
- If a wave has >50% failure rate, stop and surface to the user with the failure summaries.
- If a task is blocked and it blocks >30% of remaining tasks, stop and surface.

### Failure recovery
- Deliverable missing → retry once, then block.
- Deliverable exists but Verify fails → append correction to memory.md, retry.
- Same task fails twice → block all downstream tasks, notify user with the two failure traces.

## Worker templates

### Template: {role-name-1}
You are a {role-name-1} worker for task {{task_id}}.

FIRST: read memory.md (constraints, gotchas, corrections may apply to your task). Read the sections of tasks.md relevant to your dependencies.

Brief:
{{brief}}

Deliverable:
{{deliverable}}

Success criteria:
{{success_criteria}}

Verify (the orchestrator will run this after you return):
{{verify}}

When done, append a bullet to memory.md under the appropriate section IF you learned anything a future worker on a related task would need. Do NOT dump raw findings — only cross-cutting facts, constraints, or bugs.

Return a one-line summary: what you produced, and any concerns.

### Template: {role-name-2}
(one template per distinct role — reuse across many tasks)
```

Rules:
- Every worker template starts with "read memory.md first".
- Every worker template ends with "append cross-cutting learnings to memory.md, return one-line summary".
- Templates use {{placeholders}} the orchestrator fills at dispatch time.
- Keep the number of roles small (3-6). More roles = more coordination overhead.

# Rules for memory.md

Seed with headers only:

```
# Learnings

Accumulated by workers, curated by the orchestrator. Read before starting any task.

## Constraints discovered
## Bugs / gotchas
## Corrections to tasks
## Verified facts
```

Workers append; the orchestrator dedupes when writing back.

# Constraints on your planning

- Every task has a real, mechanically-verifiable deliverable (a file exists, a build passes, a test asserts). No "investigate X" tasks without concrete outputs.
- The system must run to completion without further user input except when quality gates trip.
- Prefer decomposing along file/module boundaries (each worker owns non-overlapping files) so parallelism doesn't cause merge conflicts.
- Independent parallel research (e.g. "look up X" for 5 different X) is a perfect early wave.
- Ask clarifying questions BEFORE generating the files if you don't have enough to produce concrete tasks.

Begin.
