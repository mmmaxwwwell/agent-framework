# Phase Dependencies & Parallelization

Every plan MUST include a **Phase Dependencies** section that makes parallelization opportunities explicit. Without this, the task runner and human operators run everything serially by default, even when independent workstreams exist.

## What the plan MUST include

1. **Dependency graph** (ASCII or Mermaid) showing which phases block which:
   ```
   Phase 1 (Test Infra) ──▶ Phase 2 (Smoke Test)
   Phase 2 ──▶ Phase 3 (Core Services) ──▶ Phase 4 (API Layer) ──▶ Phase 5 (UI)
   Phase 1 ──▶ Phase 6 (Mobile Build)  [parallel with Phases 3-5]
   Phase 5 + Phase 6 ──▶ Phase 7 (Integration)
   ```

2. **Parallel workstreams** — identify phases that can run concurrently because they touch independent code paths. Common patterns:
   - Frontend and backend (until integration phase)
   - Different platform clients (Android, iOS, web)
   - Independent feature modules with no shared state
   - Test infrastructure and initial project scaffolding

3. **Optimal multi-agent strategy** — when the project has naturally independent workstreams, describe how agents could split the work:
   ```
   Agent A: Phase 1 → 2 → 3 → 4 → 5
   Agent B: Phase 1 (wait) → 6 → (wait for Phase 5) → 7
   ```
   For single-stream projects, state "all phases are sequential."

4. **Sync points** — phases where parallel workstreams must converge (e.g., integration testing, e2e validation). These are where agents must wait for all prerequisite streams to complete.

## Avoiding circular phase dependencies

The dependency graph MUST be acyclic (a DAG). The runner considers a phase "complete" only when ALL tasks in that phase are done. This means:

**Never put a task that depends on a later phase into the same phase as tasks that the later phase depends on.** This creates a deadlock: the later phase can't start because the earlier phase isn't complete, but the earlier phase can't complete because its task is waiting on the later phase.

Example of the bug:
```
Phase 19: T109a [x], T109b [x], T109c [x], T099 [ ]
Phase 20: T110 [ ], T111 [ ], T112 [ ], T113 [ ]

DAG: Phase 19 → Phase 20 (because T109a/b/c → T110)
     T113 → T099 (task-level dep crossing back into Phase 19)
```
Phase 20 waits for Phase 19 to complete, but T099 (in Phase 19) waits for T113 (in Phase 20). Deadlock — the runner sits idle with "No agents running."

**Fix:** split the phase. Move T099 into a new Phase 21 that depends on Phase 20. Phase 19 contains only T109a/b/c (already complete), Phase 20 is unblocked, and Phase 21 runs after Phase 20 finishes.

**Rule:** if a task has a dependency on a task in a later phase, that task MUST be moved to a phase that comes after the later phase, not placed alongside the tasks the later phase depends on.
