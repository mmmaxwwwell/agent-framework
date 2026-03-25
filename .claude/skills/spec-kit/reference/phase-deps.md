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
