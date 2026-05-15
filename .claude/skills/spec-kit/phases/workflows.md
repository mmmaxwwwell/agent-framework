# Spec-Kit Workflows Phase (Phase 5.5)

You are generating `specs/<feature>/workflows.md` — the **test contract** for the feature. Workflows are the source of truth for what an end-to-end test exercises. The implementation tasks (Phase 6) and the gate's E2E suite (Phase 7) both read from this file.

This phase runs between **Plan (5)** and **Tasks (6)**. By this point, `spec.md` describes user-visible behavior and `plan.md` describes the architecture. `workflows.md` translates both into concrete, scripted, exhaustively-asserted runtime paths.

## Why this phase exists

User stories in `spec.md` describe *what* a user achieves. Acceptance scenarios describe *when* the feature is "working." Neither tells an E2E author *exactly what to script and what to assert*. Without that translation layer, agents write thin tests against happy paths and miss the boring-but-critical assertions — CSS resolved, network calls fired, modals dismissed, focus restored — that determine whether the shipped artifact actually works for a human.

Workflows are the bridge. One workflow → one E2E test, exhaustively scripted at selector + network granularity.

## Read these first

- `spec.md` — user stories + functional requirements + success criteria
- `plan.md` — architecture, tech stack, deployment shape (matters for *how* tests target the artifact)
- `interview-notes.md` — preset, any custom workflow rules the user gave
- `reference/testing.md` § "Tier authoring order" and § "Verify gate enforces all three tiers"
- `reference/ui-flow.md` if the project has a UI

## What `workflows.md` contains

### Persona sections (minimum three, more if the app needs them)

**Three personas are the floor: developer, sysadmin, and at least one end-user persona.** Most apps have more. The agent generating workflows.md must think dynamically about who actually interacts with the system and produce a persona for every distinct role.

The mandatory floor — present in every spec, no exceptions:

| Persona | Scope |
|---|---|
| **Developer** | A human running the code locally. `npm run dev` / `cargo run` / `go run ./...` / equivalent. Hot-reload, fast feedback, dev-mode quirks, debugging, profiling. |
| **Sysadmin** | A human deploying or operating the built artifact. `npm run build && node dist/server.js` / installed binary / systemd unit / docker container — whatever the production launch shape is. Configuration, secrets, restart recovery, log inspection, upgrade, backup/restore. |
| **End user (one or more)** | At least one persona representing the people the app is *for*. If the app has only one type of user, there's one end-user persona. If it has multiple types, split them — see below. |

**Split end users when their actions, permissions, or mental models differ.** The default question for the agent is: *"would these two people see different UI, take different actions, or assert different things?"* If yes, they are different personas. Common splits:

- **Admin vs. regular user** (admin manages other users, billing, system config; regular user consumes the product). Two personas.
- **Content author vs. content consumer** (authors upload/edit/publish; consumers browse/read/buy). Two personas.
- **Reviewer vs. submitter vs. observer** (review-workflow apps). Three personas.
- **Operator vs. supervisor vs. auditor** (industrial/regulated apps — operators run the line, supervisors approve exceptions, auditors read history). Three personas.
- **Tenant-org admin vs. tenant-org member vs. platform admin** (multi-tenant SaaS — three personas at minimum).
- **Free-tier user vs. paid-tier user** ONLY if they see substantively different UI/features; if the only difference is a quota, one persona with a quota-edge workflow.
- **API consumer / integrator** as its own persona when the app exposes a public API in addition to a UI. They never see the UI; their workflows are HTTP calls + response assertions + webhook receipt.

**Don't over-split.** A "logged-in user" and "logged-out user" are usually two facets of the same persona, expressed by preconditions on individual workflows, not by separate persona sections. Similarly, "mobile user" vs. "desktop user" are usually the same persona with viewport-conditional workflows, unless the mobile UI is genuinely a different surface.

**Anti-pattern: missing personas.** If the spec mentions "admins can…", "moderators can…", "the customer-success team can…", "the on-call engineer pages on…", and none of those show up as personas, the workflows file is incomplete. Walk every role spec.md names and confirm it's represented.

### Process for deciding the persona list

Before writing any workflows, the agent must produce a **persona inventory** and walk the user through it:

1. Re-read spec.md looking for every noun that names someone who interacts with the system (`operator`, `developer`, `admin`, `customer`, `auditor`, `the on-call engineer`, `API client`, `webhook sender`). List them.
2. Group synonyms. ("user", "operator", and "kiosk user" might be one persona; "admin" and "site owner" might be one persona; or they might not — check the spec.)
3. Add the mandatory floor: developer, sysadmin. (End-user persona[s] came from step 1.)
4. Present the inventory to the user as a numbered list with one-line scope for each. The user confirms, splits, or merges. This is the same model as the plan-phase decision walkthrough — engage deeply, or "yolo" to your best judgment.
5. Only after the persona list is locked does workflow enumeration begin.

Each persona section enumerates N workflows. Aim for **complete coverage** — every action a persona could reasonably take in the system gets at least one workflow. The user said "EVERYTHING must be tested exhaustively." Honor that. A small project might have 5 workflows per persona; a complex one 20+. Don't artificially compress. If a persona ends up with < 3 workflows, double-check whether it should exist as its own persona at all (might be a facet of another persona, expressed via preconditions).

### Workflow schema (every workflow must contain all fields)

```markdown
### W-N — Title

**Persona**: user | developer | sysadmin
**Touches**: US1, US2, FR-101, SC-101 (cross-reference to spec.md)
**Trigger**: what kicks off the workflow (operator taps button / dev runs command / cron fires)
**Preconditions**: exact state required before the workflow runs (printers idle, config file present, port free, DB seeded with N rows)
**Bypass paths**: explicit list of "things that might happen but don't, in this workflow" — keeps assertions focused

**Steps**:

1. **Action**: exact thing the persona does (selector + input value, or shell command + args)
   **Expected DOM**: every region that should exist after this step, with role/text/size assertions where they matter
   **Expected network**: every XHR/WS/fetch that should fire (method + URL + status + payload shape)
   **Negative assertions**: regions/calls that must NOT appear (no error toast, no `/api/error` request, no console error)

2. **Action**: ...
   **Expected DOM**: ...
   **Expected network**: ...
   **Negative assertions**: ...

(continue for every step)

**Edge cases** (each is a sub-workflow with its own step list, or a single "what changes" diff against the main flow):
- E1: network blip mid-step — what behavior is expected
- E2: state changed under the user — what behavior is expected
- E3: double-tap / double-submit — what behavior is expected
(enumerate every edge from spec.md's Edge Cases section that this workflow can trigger)

**Performance budget**: end-to-end wall clock, or per-step budget. Source from spec.md SCs where they exist.

**Test command**: exact command that runs this workflow's E2E (`pnpm --dir apps/x run test:e2e -- --grep W-N` or equivalent)
```

### Assertion depth: DOM + network (mandatory)

For every step, the workflow must specify:

1. **DOM state**: what *should* be on the page, by role or accessible name. Bad: "home page loads." Good: "page contains 3 elements with `role="article"` and `data-printer-name="x1c|ad5m-a|q2"`; each contains a `role="status"` showing one of `idle|printing|paused|error`; a floating button with `aria-label="Stop all printers"` of computed size ≥ 60×60 px is in the lower-right quadrant; no element with `role="alert"` is visible."
2. **CSS resolution**: at least once per workflow (in the first step), assert that **utility classes actually applied** — pick one tailwind class the page uses and assert its computed style matches the expected value (e.g. an element with class `bg-background` has a non-`rgba(0,0,0,0)` background-color). This is the single most valuable assertion: it catches every "Tailwind plugin missing", "PostCSS broke", "build script dropped the CSS file" regression in one line.
3. **Network state**: every request the step should fire, with method + URL + status code (and payload shape if it's a write). Network assertions catch the "page renders but `/api` is unreachable" bug class.
4. **Negative assertions**: list what must NOT happen. No console errors. No `role="alert"`. No requests to `/api/error`. No 5xx. No 404. Negative assertions catch silent regressions that positive assertions miss.

DOM + network is the floor. **Don't assert against the DB or console** in workflows — those are integration-tier coverage. If a workflow needs DB state, it asserts it via the UI (the history page shows the row) or via the API (`GET /api/history` returns the row), not via direct DB read. This keeps workflows runnable against the deployed artifact, not just the test harness.

### Selectors: use roles and accessible names, not CSS classes

Workflows must reference DOM elements by **stable identifiers**:

1. ARIA role + accessible name (`role="button"` `name="Confirm"`)
2. `data-testid` if the framework supports it
3. Visible text content
4. *Never* by tag + nth-child, never by CSS class name, never by generated id

If a workflow can't reference an element by stable identifier, the implementation lacks an accessibility affordance and the workflow's first step is "add the affordance" — surface that as an FR amendment.

### Performance budgets

Every workflow has a budget. Source from spec.md SCs where the SC is testable end-to-end. If spec.md doesn't pin one, the workflow must propose one — and the proposal goes back to spec.md as a new SC during this phase (not in plan/tasks). Common budgets:

- Cold-start FCP: typically 2 s prod, 10 s dev (Vite cold-bundles)
- Action → observable result: depends on the action; spec.md usually has these for safety-critical paths
- Page-to-page navigation: 200 ms

### Edge case enumeration is exhaustive, not selective

For each workflow, walk through `spec.md`'s Edge Cases section and enumerate every edge that the workflow's persona can trigger. If an edge case applies to multiple workflows, list it in every applicable workflow (workflows are the test units; duplication here is correct because each workflow becomes a separate E2E).

If an edge case has no workflow it can be triggered from, flag it back to spec.md as either a missing workflow or a missing trigger condition.

## What `workflows.md` replaces

This phase **replaces the Acceptance Scenarios bullets** under each `### User Story N` in spec.md. The user stories keep:

- Title + priority
- Prose ("an operator at the touchscreen sees three printer cards...")
- "Why this priority" line
- "Independent Test" line (now reframed as "Primary workflow: W-N")

The Given/When/Then bullets are deleted from spec.md and re-expressed (with vastly more detail) as one or more workflows in `workflows.md`. Acceptance scenarios were necessary-but-not-sufficient; workflows are necessary-AND-sufficient.

Update the user story to point at the workflows that cover it:

```markdown
### User Story 1 — Operator starts a print on a free printer (Priority: P1)

An operator at the touchscreen ...

**Why this priority**: ...

**Workflows**: W-U1 (happy path), W-U2 (no idle printers), W-U3 (filament-incompatible 3MF rejected)
```

## What `workflows.md` does NOT contain

- **Internal test cases (unit, integration)**: those are in the implementation tasks. Workflows are exclusively E2E-tier — what a real human running the artifact would do.
- **Implementation details**: don't say "use Playwright's `getByRole`" — say "the test must reference the Confirm button by ARIA role + accessible name." The *how* is the task agent's job.
- **Tech-stack choices**: those are plan.md.

## Process

1. **Read inputs** — spec.md, plan.md, interview-notes.md, reference/testing.md.
2. **Build the persona list** — run the persona inventory process above. Three is the floor (developer, sysadmin, ≥1 end-user). Add more whenever the spec names a distinct role with different actions/permissions/mental model. The user confirms or amends the list.
3. **For each persona, enumerate workflows**:
   - **End-user persona(s)**: walk every user story in spec.md that names this persona. Each story becomes one happy-path workflow + one or more variant workflows for the story's edge cases. Cross-story workflows (W-U2 from spec 002: "operator starts prints on two printers concurrently") are first-class — don't constrain to one-story-per-workflow. If a story is shared across multiple end-user personas (e.g. "view dashboard" applies to both admin and regular user), generate the workflow under whichever persona experiences it most fully, then add a one-line variant under the other persona pointing at the primary and listing only the diffs.
   - **Developer**: enumerate every dev-time action. Minimum set: cold `npm run dev` produces working page, code edit triggers HMR, error in a source file shows readable overlay, lint runs, types check, tests run, every npm script that exists in package.json. Add project-specific items: "switch git branch and reload, no state leaks", "stop dev server with Ctrl-C, no orphan child processes", "open a second browser tab, both stay in sync".
   - **Sysadmin**: enumerate every prod-time action. Minimum set: `npm run build` succeeds with no warnings, built artifact starts under the prod launch command, artifact serves the same UI as dev with identical functionality, artifact survives restart with state intact, artifact logs to where logs are expected, every config knob the spec mentions has a workflow that exercises it (default value works, non-default value works, invalid value rejects with readable error). Add project-specific items: "rotate a secret on disk, service picks it up without restart" (if spec says so), "kill the service mid-write, restart, no corruption", "view logs via journalctl/equivalent", "upgrade from v(n-1) to v(n)".
4. **Walk the user through the workflow list** — present the persona × workflow matrix to the user. Confirm coverage. Add anything missed. Same model as the plan-phase decision walkthrough.
5. **For each workflow, fill in the full schema** — steps, DOM, network, negative assertions, edges, budget, test command. Group writes; don't ask between workflows once the list is confirmed.
6. **Propagate budget proposals back to spec.md** — if a workflow had to invent a performance budget because spec.md was silent, add an SC for it. Update spec.md atomically.
7. **Update spec.md user stories** — remove Acceptance Scenarios bullets, add `**Workflows**: W-N, W-M` line.
8. **Write `workflows.md`** to the spec dir.
9. **Re-run analyze (Phase 4)** — workflows.md is a new artifact; the analyzer checks cross-consistency between spec.md, plan.md, and workflows.md. Fix any findings before advancing to Phase 6.

## Output structure

`specs/<feature>/workflows.md`:

```markdown
# Workflows — <feature name>

## Personas

(One subsection per persona. Three is the floor — developer, sysadmin, ≥1 end-user — but list every distinct role the spec names. Each entry: one-sentence scope and a stable workflow-id prefix.)

- **Developer** (`W-DEV-*`): <one sentence>
- **Sysadmin** (`W-SYS-*`): <one sentence>
- **Operator** (`W-OP-*`): <one sentence>           # end-user persona for this spec
- **Admin** (`W-ADM-*`): <one sentence>             # additional end-user persona, if applicable
- **API client** (`W-API-*`): <one sentence>        # additional persona, if applicable
- ...

Workflow ids use the persona's prefix so a grep for `W-ADM-` returns all admin workflows. Numbering is per-persona (`W-OP-1`, `W-OP-2`, ...).

## Coverage matrix

| Persona | Workflow count | Touches |
|---|---|---|
| Developer | M | (no user stories — workflows derive from plan.md + DX requirements) |
| Sysadmin | L | FR-XXX (deployment-related), SC-YYY |
| Operator | N | US1..USK |
| Admin | K | US-A1..US-AJ |
| ...     | ... | ... |

## Developer workflows

### W-DEV-1 — Cold `<dev command>` produces working page
(full schema)

## Sysadmin workflows

### W-SYS-1 — `<build command>` succeeds and built artifact starts
...

## Operator workflows
(or whatever the primary end-user persona is for this spec)

### W-OP-1 — Title
...

## <Other end-user persona> workflows

### W-<PREFIX>-1 — Title
...

## Cross-cutting assertions

Things every workflow asserts, listed once here and referenced by `[CC-N]` from steps:

- **CC-1**: No console errors or warnings throughout the workflow.
- **CC-2**: At least one Tailwind/CSS utility class on the first rendered page has resolved computed style.
- **CC-3**: No request to `/api/error` or `/api/internal-error` fires.
- ...
```

## Constraints on the agent generating workflows.md

- **No fictional features.** Every step must correspond to UI/CLI/API surface that exists in the spec or the plan. If a workflow needs an affordance that isn't yet specified (e.g. "tap the Refresh Library button"), flag it as a missing spec item and either amend the spec or drop the workflow — don't write a workflow against vapor.
- **No hand-waving.** "The page should look right" is never a valid assertion. Pick concrete observables: role, name, visible text, computed style, network method/URL/status, payload shape.
- **No skipped edges.** Every edge case in spec.md must appear in at least one workflow's `Edge cases` block, or be deleted from spec.md as not-actually-an-edge-case.
- **No premature "skip on CI / skip on Nix sandbox" carveouts.** Workflows describe the truth; the implementation phase solves the environment. If a workflow can't run somewhere, that's an environment bug to be fixed in `flake.nix` or equivalent — never a workflow that's silently skipped. See `reference/testing.md` § "Obstacles are solved, not skipped".

## After this phase

- `tasks.md` (Phase 6) generates one task per workflow under a late `E2E` phase, plus tasks for the affordances workflows surfaced as missing.
- The implement runner's verify gate (Phase 7) executes every `test:e2e` script declared in every workspace `package.json`. That command must invoke the workflow suite. If the project doesn't yet declare `test:e2e`, Phase 6 generates a task to declare it; Phase 7's gate enforces it from that point on.
- Future spec changes (new FR, new user story) trigger a workflows.md update before the change can advance to tasks/implement. workflows.md is durable; it grows with the spec, and old workflows stay (they document already-shipped behavior and prevent regression).
