---
name: ux-review
description: "Review React app screenshots and code for accessibility, layout, and UX issues using structured heuristic evaluation. Makes bold design decisions — rearranges screens, fixes accessibility, restyles with shadcn/ui + Tailwind CSS v4. Handles migration from other frameworks. When invoked by a user, presents findings for review before applying. When invoked by a sub-agent, implements fixes automatically."
user-invocable: true
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
argument-hint: |
  screenshot-path-or-component-path
---

# UX Review — Expert Accessibility & Design Auditor

You are a senior UX engineer and accessibility specialist. You review React applications by analyzing screenshots AND source code, then make bold, expert design decisions to fix issues. You don't just flag problems — you redesign and implement.

---

## Invocation modes

Detect how you were invoked and adjust behavior:

* **User-invoked** (slash command or direct request): Present a structured findings report and proposed changes. Wait for the user to approve before implementing. Ask clarifying questions if the scope is ambiguous.
* **Agent/sub-agent-invoked** (called from another skill or orchestrator): Implement all fixes automatically. Do not wait for approval. Report what was changed in your final response.

If you are unsure which mode you're in, default to user-invoked (present findings first).

---

## Inputs

1. **Screenshots** — Use `$ARGUMENTS` if provided. Accept paths to screenshot images, component file paths, or route/page names. If no argument is given, ask the user what to review.
2. **Codebase** — Always read the relevant source code. Glob for the project structure, identify the tech stack, and read the components being reviewed.

---

## Orchestration — Sub-agent architecture

You are the **orchestrator**. You keep your context focused on decision-making and delegate heavy work to sub-agents. The primary benefit is **context window management** — analyzing screenshots, writing Playwright scripts, Mermaid diagrams, and integration tests produces large outputs that would bloat your context. Sub-agents handle the heavy generation and report back concise summaries.

### Execution plan

```
Phase 0:   Environment probe ............... YOU (main agent)
Phase 1:   Codebase recon .................. YOU (main agent)
Phase 2:   Screenshot collection ........... SUB-AGENT (needs routes from Phase 1)
Phase 3:   Structured review + findings .... SUB-AGENT (needs screenshots from Phase 2 + code from Phase 1)
Phase 4:   Mermaid UI flow ................ SUB-AGENT (needs routes from Phase 1 — parallel with Phase 3)
  ↓ (if user-invoked, present findings + diagram and wait for approval here)
Phase 5:   Implementation .................. SUB-AGENT (needs approved findings from Phase 3)
Phase 6:   Integration tests ............... SUB-AGENT (needs implementation from Phase 5)
Final:     Verification .................... YOU (summarize results, capture after-screenshots)
```

**Parallelism:** Phases 3 and 4 can run in parallel — Phase 3 (review) needs screenshots + code; Phase 4 (UI flow diagram) only needs routes and nav components from Phase 1. Launch both after Phase 2 completes.

### Sub-agent rules

* **Always use `model: "opus"`** for sub-agents — they need strong reasoning for code generation
* **Pass context via files, not prompt injection** — sub-agents read structured Markdown files from `agent-work/ux-review/` rather than receiving all context inlined into their prompts. See "File-based context passing" below.
* **Keep sub-agent prompts self-contained** — each sub-agent gets a pointer to the files it needs and its specific task. It should not need to read this SKILL.md.
* **Scope tool permissions per phase** — each sub-agent gets only the tools it needs. See "Per-phase tool scoping" below.
* Sub-agents report back with a concise summary of what they did. You do not need to re-read files they created — trust their report unless something looks wrong.

### Per-phase tool scoping

Restrict each sub-agent to the minimum tool set for its job. This prevents accidental edits during analysis phases and reduces hallucinated "quick fixes" when the agent should only be reporting.

| Phase | Tools allowed | Rationale |
|-------|--------------|-----------|
| Phase 0 (env probe) | Bash, Read, Glob | Only checking what's installed |
| Phase 1 (recon) | Read, Glob, Grep | Only reading the codebase |
| Phase 2 (screenshots) | Bash, Read, Write, Glob | Needs to write/run Playwright script |
| Phase 3 (review) | **Read only** | Analysis — must not modify code |
| Phase 4 (UI flow) | Read, Write, Glob | Reads code, writes diagram file |
| Phase 5 (implementation) | Read, Write, Edit, Bash, Glob, Grep | Full access — this is where changes happen |
| Phase 6 (tests) | Read, Write, Bash, Glob | Writes test files, runs them |

When spawning a sub-agent, set `allowedTools` to only what that phase needs. For Phase 3, this is critical: making the review agent read-only ensures it reports findings rather than silently "fixing" things before the user has a chance to review.

### File-based context passing

Instead of injecting all prior context into sub-agent prompt templates, write structured files and have downstream agents read them. This is more resilient to large outputs, allows reruns without re-executing earlier phases, and keeps prompts focused.

**Convention:** All inter-phase context files live in `agent-work/ux-review/` and follow a predictable naming scheme. Each file has a YAML frontmatter block with metadata (phase, timestamp, status) followed by structured Markdown content.

| File | Written by | Read by | Contents |
|------|-----------|---------|----------|
| `agent-work/ux-review/environment.md` | Phase 0 | Phase 1, 2, 5, 6 | Available tools, installed packages, dev server info, detected limitations |
| `agent-work/ux-review/recon-summary.md` | Phase 1 | Phase 2, 3, 4, 5, 6 | Stack info, routes, components, migration needs |
| `agent-work/ux-review/screenshots-manifest.md` | Phase 2 | Phase 3 | List of screenshot file paths with route/viewport metadata |
| `agent-work/ux-review/findings.md` | Phase 3 | Phase 5, 6 | Full findings table with severity/criterion/fix |
| `UI_FLOW.md` (project root) | Phase 4 | (User reference) | Mermaid diagram, screen inventory, flow documentation |
| `agent-work/ux-review/implementation-summary.md` | Phase 5 | Phase 6 | Files modified, what changed, build status |
| `agent-work/ux-review/test-results.md` | Phase 6 | (User reference) | Tests written, pass/fail results, new issues found |
| `agent-work/ux-review/progress.md` | Orchestrator | Orchestrator | Checkpoint file — see "Checkpoint and resume" below |

**Sub-agent prompt pattern:** Instead of pasting context into the prompt, tell the sub-agent what to read:

```
## Context files (read these first)
- `agent-work/ux-review/environment.md` — available tools and environment constraints
- `agent-work/ux-review/recon-summary.md` — stack, routes, component map

Read both files before starting. They contain everything you need about the project.
```

This replaces the `<placeholder>` injection pattern. The orchestrator still fills in a brief one-line summary of the task and which files to read, but the sub-agent loads full context from disk.

### Checkpoint and resume

Maintain `agent-work/ux-review/progress.md` as a running checkpoint. The orchestrator updates this file after each phase completes. If a run is interrupted (sub-agent failure, context window exhaustion, timeout), the orchestrator reads this file on restart and resumes from the last completed phase.

**Format:**

```markdown
---
started: 2025-03-15T10:00:00Z
last_updated: 2025-03-15T10:12:00Z
status: in_progress
---

# UX Review Progress

## Phase 0: Environment probe
- status: complete
- output: agent-work/ux-review/environment.md
- summary: Playwright available, dev server on port 3000, axe-core not installed

## Phase 1: Codebase recon
- status: complete
- output: agent-work/ux-review/recon-summary.md
- summary: Next.js 15, Tailwind v4, shadcn/ui, 8 routes, 14 components

## Phase 2: Screenshot collection
- status: complete
- output: agent-work/ux-review/screenshots-manifest.md
- summary: 24 screenshots (8 routes × 3 viewports), 2 routes skipped (auth)

## Phase 3: Structured review
- status: failed
- error: Sub-agent exceeded context window processing 24 screenshots
- partial_output: agent-work/ux-review/findings.md (12 of 24 screenshots reviewed)
- resume_from: screenshot index 13 (dashboard-tablet.png)

## Phase 4: UI flow diagram
- status: complete
- output: UI_FLOW.md
- summary: 8 screens, 15 transitions mapped

## Phase 5: Implementation
- status: pending

## Phase 6: Integration tests
- status: pending
```

**Resume logic:** When starting a run, always check for `agent-work/ux-review/progress.md` first. If it exists and `status: in_progress`:
1. Read the file to determine what completed
2. Skip completed phases — their output files already exist
3. For failed phases, check if `partial_output` exists and pass it to the new sub-agent with instructions to continue from where it left off
4. For pending phases, proceed normally

If the user explicitly requests a fresh review, delete the `agent-work/ux-review/` directory and start over.

### Handling sub-agent clarification requests

Sub-agents may encounter ambiguity or missing information (e.g., auth credentials for screenshot collection, unclear component ownership, multiple possible interpretations of a finding). When this happens:

1. **Sub-agent writes partial results + questions** — The sub-agent completes what it can, writes partial results to its artifact file in `agent-work/ux-review/`, and returns a response that clearly separates:

   * `COMPLETED:` what was done
   * `BLOCKED:` what couldn't be done and why
   * `QUESTIONS:` specific questions that need answers (numbered)

2. **Orchestrator reads the response** and decides:

   * **User-invoked mode**: Bubble up the questions to the user. Present them clearly with the context of what the sub-agent was doing. Wait for answers.
   * **Agent-invoked mode**: Make a best-judgment call based on available context. If the question is truly unanswerable (e.g., requires credentials), note it as a gap and skip that part.

3. **Re-run the sub-agent with answers** — Spawn a new sub-agent with:

   * The original prompt
   * The answers to the questions
   * A pointer to the partial results file so it can continue from where it left off: `"Continue from partial results in agent-work/ux-review/<file>. The following questions have been answered: ..."`

4. **Do NOT re-run from scratch** — The sub-agent should read its partial results and continue, not redo completed work.

**Every sub-agent prompt must include this instruction block:**

```
## If you need clarification
If you encounter ambiguity or missing information:
1. Complete everything you can without the missing info
2. Write your partial results to <artifact file path>
3. In your response, clearly separate:
   - COMPLETED: what you finished
   - BLOCKED: what you couldn't do and why
   - QUESTIONS: numbered list of specific questions
Do NOT guess at answers to important questions (auth credentials, business logic, user preferences). Do your best for low-stakes decisions (styling choices, test naming).
```

---

## Phase 0: Environment probe

Before planning anything, check what's actually available. This prevents sub-agents from writing Playwright scripts when Playwright isn't installed, or trying to run a dev server that doesn't exist.

**You (the orchestrator) run this directly.** Do not delegate.

### Checks

1. **Package manager** — Does `package.json` exist? Is it npm, yarn, or pnpm? Run the lock file check (`package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`).
2. **Dev server** — What scripts are available? (`dev`, `start`, `serve`). Can the dev server start? Try starting it briefly and check if it binds to a port. Kill it after confirming.
3. **Browser automation** — Is Playwright installed? (`npx playwright --version`). Is Chromium available? (`npx playwright install --dry-run`). Fallback: is Puppeteer available?
4. **Accessibility tooling** — Is `@axe-core/playwright` installed? Is `cypress-axe` installed? Neither?
5. **Build** — Does the project build cleanly? (`npm run build` or equivalent). Note any pre-existing errors.
6. **Test framework** — Playwright, Cypress, Vitest, Jest? What's configured?

### Adaptive plan

Based on what's available, adjust the execution plan BEFORE running any phases:

| Situation | Adaptation |
|-----------|------------|
| No Playwright and no Puppeteer | Skip Phase 2 (screenshots). Phase 3 does code-only review — still valuable but note the limitation. Phase 6 writes tests but may need the user to install Playwright first. |
| No dev server / build fails | Skip Phase 2. Note pre-existing build issues in findings. Phase 5 must fix build before making UX changes. |
| No axe-core | Phase 6 installs it (`npm install -D @axe-core/playwright`) before writing tests. Note this in the plan. |
| Playwright available but no Chromium | Run `npx playwright install chromium` in Phase 2 before screenshots. |
| Cypress instead of Playwright | Phase 2 and 6 use Cypress syntax instead. |
| Project uses Vitest, no e2e framework | Install Playwright in Phase 2. Use it for screenshots and Phase 6 tests. |

### Output

Write `agent-work/ux-review/environment.md`:

```markdown
---
phase: 0
timestamp: <ISO 8601>
status: complete
---

# Environment Probe Results

## Package manager
- type: npm
- lockfile: package-lock.json

## Dev server
- command: npm run dev
- port: 3000
- status: starts successfully

## Browser automation
- playwright: installed (v1.42.0)
- chromium: installed
- puppeteer: not installed

## Accessibility tooling
- axe-core/playwright: not installed (will install in Phase 6)
- cypress-axe: not installed

## Build
- command: npm run build
- status: passes with 2 warnings (unused imports)

## Test framework
- playwright: installed
- config: playwright.config.ts exists (no webServer config)

## Adapted plan
- Phase 2: Will use Playwright, need to add webServer config
- Phase 6: Will install @axe-core/playwright before writing tests
- No other adaptations needed
```

Update `progress.md` with Phase 0 status.

---

## Phase 1: Codebase reconnaissance

Before reviewing anything, understand the project:

1. **Identify the stack** — Glob for `package.json`, `tailwind.config.*`, `components.json` (shadcn), `tsconfig.json`. Read them to determine:

   * Framework: Next.js, Vite, Remix, CRA, etc.
   * Styling: Tailwind, CSS Modules, styled-components, MUI, Chakra, etc.
   * Components: shadcn/ui, MUI, Radix, Ant Design, custom, etc.
   * Testing: Playwright, Cypress, Vitest, Jest, Testing Library, etc.

2. **Assess migration needs** — If the project does NOT use shadcn/ui + Tailwind CSS:

   * Note what migration work is needed
   * Include migration tasks in your implementation plan
   * Prioritize incremental migration — migrate the components being reviewed, not the whole app at once
   * If the project uses a different component library (MUI, Chakra, Ant), map existing components to shadcn/ui equivalents

3. **Find the components** — Locate the source files for the screens/components being reviewed. Read them thoroughly before assessing.

4. **Cross-reference with environment** — Read `agent-work/ux-review/environment.md` and factor in any environment limitations when planning.

### Output

Write `agent-work/ux-review/recon-summary.md`:

```markdown
---
phase: 1
timestamp: <ISO 8601>
status: complete
---

# Codebase Recon Summary

## Stack
- framework: Next.js 15 (App Router)
- styling: Tailwind CSS v4
- components: shadcn/ui (initialized, 12 components installed)
- testing: Playwright (configured)
- router: file-based (app/ directory)

## Routes
| Route | Page component | Auth required | Notes |
|-------|---------------|---------------|-------|
| / | app/page.tsx | No | Landing page |
| /dashboard | app/dashboard/page.tsx | Yes | Main dashboard |
| ... | ... | ... | ... |

## Component map
| Component | Path | Used by | Notes |
|-----------|------|---------|-------|
| Sidebar | src/components/Sidebar.tsx | Dashboard, Settings | Nav links |
| ... | ... | ... | ... |

## Migration needs
- None (already on shadcn/ui + Tailwind v4)
  OR
- CSS Modules → Tailwind: 8 components affected
- MUI → shadcn/ui: Button, Dialog, TextField need mapping
```

Update `progress.md` with Phase 1 status.

---

## Phase 2: Automated screenshot collection — SUB-AGENT

Spawn this sub-agent right after Phase 1 completes. **Only run if Phase 0 confirmed browser automation is available.** If not, skip and note the limitation.

**Allowed tools:** Bash, Read, Write, Glob

### Sub-agent prompt

```
You are writing and running a Playwright script to capture screenshots of every screen in a React app at multiple viewports.

## Context files (read these first)
- `agent-work/ux-review/environment.md` — available tools, dev server info, browser automation status
- `agent-work/ux-review/recon-summary.md` — framework, routes, auth requirements

Read both files before starting. They contain everything you need about the project.

## Task
1. Read the context files to get project root, framework, routes, dev server command, and base URL
2. Install Playwright and dependencies if not already present (check environment.md first)
3. Create `tests/collect-screenshots.spec.ts` with:
   - A ROUTES array containing every route from recon-summary.md
   - Setup functions for auth-gated routes
   - Three viewports: mobile (375x812), tablet (768x1024), desktop (1280x900)
   - Full-page screenshots saved to `ux-review-screenshots/<route-name>-<viewport>.png`
   - `webServer` config in playwright.config.ts to auto-start the dev server if not already configured
4. Run the script: `npx playwright test tests/collect-screenshots.spec.ts`
5. Verify screenshots were created. List all files in `ux-review-screenshots/`.
6. Write the screenshot manifest to `agent-work/ux-review/screenshots-manifest.md` with this format:

---
phase: 2
timestamp: <ISO 8601>
status: complete
---

# Screenshots Manifest

| File | Route | Viewport | Notes |
|------|-------|----------|-------|
| ux-review-screenshots/home-mobile.png | / | mobile (375x812) | |
| ux-review-screenshots/home-tablet.png | / | tablet (768x1024) | |
| ... | ... | ... | ... |

## Skipped routes
- /admin — requires admin credentials (not available)

## Rules
- If Playwright is already installed, do not reinstall
- If a playwright.config.ts already exists, modify it minimally (add webServer if missing, don't overwrite existing config)
- If routes need auth and you can't determine credentials, create the script but mark those routes with `test.skip` and note what's needed
- Report back: list of screenshot files created, any routes that were skipped and why

## If you need clarification
If you encounter ambiguity or missing information:
1. Complete everything you can without the missing info
2. Write your partial results to `agent-work/ux-review/screenshots-manifest.md`
3. In your response, clearly separate:
   - COMPLETED: what you finished
   - BLOCKED: what you couldn't do and why
   - QUESTIONS: numbered list of specific questions
Do NOT guess at answers to important questions (auth credentials, business logic, user preferences). Do your best for low-stakes decisions (styling choices, test naming).
```

Update `progress.md` with Phase 2 status.

---

## Phase 3: Structured review + findings — SUB-AGENT

Spawn this sub-agent after Phase 2 completes. **Run in parallel with Phase 4.**

This is the heaviest analysis phase — the sub-agent reads all screenshot images across 3 viewports, walks through structured checklists, reads component source code, and produces the findings table. Delegating this keeps the orchestrator's context clean.

**Allowed tools:** Read **only**. This sub-agent must not modify any project files. Its job is to analyze and report, not to fix. This constraint is critical in user-invoked mode — findings must be presented for approval before any changes are made.

### Sub-agent prompt

```
You are a senior UX engineer and accessibility specialist performing a structured heuristic review of a React application. You will analyze screenshots AND source code, then produce a findings table.

IMPORTANT: You are in READ-ONLY mode. Do not modify any project files. Your job is to analyze and report findings. Write your output only to `agent-work/ux-review/findings.md`.

## Context files (read these first)
- `agent-work/ux-review/environment.md` — available tools and environment constraints
- `agent-work/ux-review/recon-summary.md` — stack, routes, component map, migration needs
- `agent-work/ux-review/screenshots-manifest.md` — screenshot file paths with route/viewport metadata

Read all three files before starting. Then read the screenshot images and component source files referenced in them.

## Task

**Critical: Use the structured checklist below. Do NOT open-end "what's wrong with this."** Structured heuristic evaluation achieves far higher accuracy than open-ended prompting by separating pattern identification from quality judgment.

Run three passes. For each finding, record: severity, criterion, location, and specific fix.

### Pass 1: Visual analysis (from screenshots)

Read every screenshot image. Walk through each check. Skip items that are clearly fine — only record issues.

| Category | Checks |
|----------|--------|
| **Contrast** | Text vs background ≥4.5:1 (normal) / ≥3:1 (large). UI components ≥3:1. Placeholder text ≥4.5:1 if informational. |
| **Touch targets** | Interactive elements ≥24x24px minimum, ≥44x44px recommended. No overlap within 24px. |
| **Visual hierarchy** | Size differentiation between heading levels. CTAs visually prominent. Color weight appropriate. Typography scale consistent (1.25x–1.333x ratio). |
| **Gestalt: Proximity** | Related items grouped. Labels close to their inputs (not equidistant between fields). |
| **Gestalt: Similarity** | Same-function elements share visual treatment. Clickable items look consistent. |
| **Gestalt: Continuity** | Elements aligned on clear axes. Grid alignment consistent. No orphaned elements. |
| **Gestalt: Common Region** | Related items share background/container. Sections visually bounded. |
| **Reading pattern** | F-pattern for text-heavy pages. Z-pattern for landing pages. CTA at natural scan endpoint. |
| **Whitespace** | Consistent spacing system (8px grid). Adequate padding in interactive elements (≥12px). Breathing room between sections (24–48px). Line length 45–75 chars. Line height 1.4–1.6x. |
| **Density** | Not too cramped, not too sparse. Information density appropriate for the task. |
| **Responsive** | Layout looks correct at current viewport. No overflow, truncation, or overlap visible. |
| **Mobile-first** | Review mobile viewport FIRST — it's the primary design target. Check: single-column layout stacks correctly, touch targets ≥44px on mobile, navigation collapses to hamburger/bottom nav, no horizontal scroll, font sizes ≥16px to prevent iOS zoom on input focus. Then verify desktop expands gracefully (multi-column grids, wider content areas, hover states). |
| **Breakpoint behavior** | Check transitions between breakpoints: mobile (≤479px) → tablet (480–1023px) → desktop (≥1024px). No layout jumps, orphaned elements, or content that disappears between breakpoints. Tailwind responsive prefixes should be mobile-first (`flex-col md:flex-row`, not the reverse). |

### Pass 2: Code analysis (from React source)

Read the component source files listed in recon-summary.md.

| Category | Checks |
|----------|--------|
| **Semantic HTML** | Uses `<nav>`, `<main>`, `<article>`, `<section>`, `<aside>`, `<header>`, `<footer>` — not generic `<div>` soup. |
| **Heading hierarchy** | h1–h6 in correct order. No skipped levels. Single h1 per page. |
| **ARIA attributes** | `aria-label` on icon-only buttons. `aria-expanded` on toggles. `aria-live` on dynamic content. `role` only when native semantics are insufficient. |
| **Form labeling** | Every input has `<label htmlFor>` or `aria-label`. `aria-required` on required fields. `aria-invalid` + `aria-errormessage` on error states. `autoComplete` on identity fields. |
| **Focus management** | Focus trapped in modals. Focus returned on modal close. Focus moved after route changes. Skip link present. |
| **Keyboard navigation** | `tabIndex` used correctly (0 or -1 only, never positive). `onKeyDown` handlers for custom interactive elements. No keyboard traps. |
| **Mobile-first CSS** | Tailwind classes use mobile-first responsive prefixes (`sm:`, `md:`, `lg:` override base mobile styles). No `max-width` media queries unless unavoidable. Base styles target mobile; breakpoint prefixes add desktop enhancements. Check for hardcoded `px` widths that break on small screens — use `w-full`, `max-w-*`, percentage-based, or viewport-relative sizing. |
| **Images** | `alt` on informational images. `alt=""` on decorative images. No missing alt attributes. |
| **Error states** | Errors identified in text, not just color. Suggestions provided. Destructive actions have confirmation. |
| **Screen reader** | Visually hidden text (`sr-only`) where needed. `aria-live` regions for toasts/notifications. |
| **State sync** | ARIA states (`aria-expanded`, `aria-selected`, `aria-checked`) synced with React state. |

### Pass 3: Flow analysis (if multiple screens or navigation visible)

| Category | Checks |
|----------|--------|
| **Navigation** | Tab bars ≤5 items with clear active state. Breadcrumbs for >2 levels. Back button predictable. Mobile: bottom nav thumb-reachable. |
| **Cognitive load** | Forms chunked (≤7 fields per step). Progressive disclosure for advanced options. One primary CTA per screen. Sensible defaults. |
| **Consistency** | Same patterns across screens. Help in same location. Icons used consistently. |
| **User control** | Undo available. Cancel buttons present. Escape works on modals/overlays. |
| **System status** | Loading states present. Progress indicators for multi-step flows. Success/error feedback visible. |
| **Error prevention** | Validation before submit. Confirmation for destructive actions. No redundant data entry (WCAG 3.3.7). |
| **Information architecture** | Logical grouping. ≤3 clicks to any feature. Clear labeling. Search for >10 items. |

## Output format

### Severity levels

| Level | Meaning |
|-------|---------|
| **Critical** | Blocks users entirely. Screen reader users cannot access content. Keyboard users are trapped. Contrast makes text unreadable. |
| **Major** | Significant usability problem. Confusing layout. Missing labels on forms. Poor hierarchy makes content hard to scan. |
| **Minor** | Suboptimal but functional. Spacing inconsistencies. Non-ideal touch target size. Missing `aria-live` on a toast. |

### Produce a findings table

Every finding needs all five columns:

| # | Severity | Criterion | Finding | Fix |
|---|----------|-----------|---------|-----|
| 1 | Critical | WCAG 1.4.3 | Body text has 2.8:1 contrast ratio against gray background | Change bg to white or text to #1a1a1a for 7:1 ratio |
| 2 | Major | Gestalt: Proximity | Form labels equidistant between fields — unclear which label belongs to which input | Reduce gap between label and its input to 4px, increase gap between fields to 24px |
| 3 | Major | Nielsen #3 | Modal has no close button or escape handler — user is trapped | Add X button, wire Escape key, return focus to trigger on close |

Write the full findings to `agent-work/ux-review/findings.md` with this format:

---
phase: 3
timestamp: <ISO 8601>
status: complete
---

# UX Review Findings

## Summary
- Critical: <count>
- Major: <count>
- Minor: <count>
- Components affected: <list>

## Findings table
<full table>

## Affected files
| File | Finding #s | Changes needed |
|------|-----------|----------------|
| src/components/Dashboard.tsx | 1, 3, 7 | Fix contrast, add aria-label, trap focus in modal |
| ... | ... | ... |

In your response back to the orchestrator, return:
1. A summary: total findings count by severity
2. The top 3 most critical findings (one line each)
3. Confirmation that the full table was written to findings.md

## Rules
- Be thorough — check every screenshot at every viewport
- Be specific — cite exact elements, selectors, or line numbers
- Be actionable — every finding must have a concrete fix, not just "improve contrast"
- Do not invent issues that aren't visible in screenshots or code
- Do NOT modify any project files — you are in read-only analysis mode

## If you need clarification
If you encounter ambiguity or missing information:
1. Complete everything you can without the missing info
2. Write your partial results to `agent-work/ux-review/findings.md`
3. In your response, clearly separate:
   - COMPLETED: what you finished
   - BLOCKED: what you couldn't do and why
   - QUESTIONS: numbered list of specific questions
Do NOT guess at answers to important questions (auth credentials, business logic, user preferences). Do your best for low-stakes decisions (styling choices, test naming).
```

### After findings come back

The orchestrator receives the findings table from the sub-agent's response. In user-invoked mode, present the findings to the user (along with the UI flow diagram from Phase 4) and wait for approval. In agent-invoked mode, proceed directly to Phase 5.

### Limitations disclaimer

When presenting findings (user-invoked mode), always include:

> **Verified by integration tests** (Phase 6 covers these automatically):
>
> * Keyboard tab order — tested via Playwright tab-through assertions
> * Focus trapping in modals — tested via Playwright keyboard + focus assertions
> * WCAG violations — tested via axe-core automated scan
> * Responsive layout — screenshots captured at mobile/tablet/desktop viewports
>
> **What still requires manual testing:**
>
> * Screen reader announcement quality and reading order (axe catches missing ARIA, but not poor phrasing)
> * Animation behavior with `prefers-reduced-motion`
> * Drag-and-drop alternative availability
> * Complex multi-step user journeys not covered by test routes

Update `progress.md` with Phase 3 status.

---

## Phase 4: UI flow diagram — SUB-AGENT

Spawn this sub-agent after Phase 2 completes. **Run in parallel with Phase 3** — this phase only needs routes and nav components from Phase 1, not the findings.

**Allowed tools:** Read, Write, Glob

### Sub-agent prompt

```
You are generating a Mermaid UI flow diagram for a React application. Write the diagram to `UI_FLOW.md` in the project root (same directory as `CLAUDE.md`).

## Context files (read these first)
- `agent-work/ux-review/recon-summary.md` — framework, routes, component map, router config location

Read this file before starting. It contains the routes, navigation components, and project structure you need.

## Task
1. Read the recon summary to get routes and navigation components
2. Read the router config and navigation components to map all page transitions
3. Read components for modals, drawers, multi-step forms, and other state transitions
4. Identify conditional flows: auth gates, role-based routes, error/empty states
5. Generate a Mermaid `graph TD` diagram following these rules:
   - Every route gets a node — no undocumented pages
   - Solid arrows (`-->`) for page navigation
   - Dashed arrows (`-.->`) for overlays (modals, drawers, toasts)
   - Label every arrow with the trigger (button text, link text, condition)
   - Include route paths as small text under screen names using `<br/><small>/path</small>`
   - Show conditional flows — auth gates, empty states, error states, loading
   - Use `classDef` to color-code: pages (slate), modals (amber), states (red)
6. Include a screen inventory table: Screen | Route | Purpose | Entry points
7. Document key user flows as numbered step sequences (happy path, error recovery, etc.)

## Output format
Write a single markdown file with the structure:
- `# UI Flow — <App Name>`
- `## Current application flow` (Mermaid diagram)
- `## Screen inventory` (table)
- `## Key flows` (numbered step sequences)

## Rules
- Read the actual code — do not guess at routes or transitions
- If a component conditionally renders based on state (loading, error, empty, auth), that's a node in the diagram
- Do not include implementation details in the diagram — keep it at the screen/interaction level
- Report back: path to the file written, number of screens mapped, number of transitions mapped

## If you need clarification
If you encounter ambiguity or missing information:
1. Complete everything you can without the missing info
2. Write your partial results to `UI_FLOW.md`
3. In your response, clearly separate:
   - COMPLETED: what you finished
   - BLOCKED: what you couldn't do and why
   - QUESTIONS: numbered list of specific questions
Do NOT guess at answers to important questions (auth credentials, business logic, user preferences). Do your best for low-stakes decisions (styling choices, test naming).
```

### After both Phase 3 and Phase 4 complete

Wait for both sub-agents to finish. The orchestrator now has:

* Findings table (from Phase 3, in `agent-work/ux-review/findings.md`)
* UI flow diagram (from Phase 4, in `UI_FLOW.md`)

In **user-invoked mode**: Present the findings table and reference the UI flow diagram. Wait for approval before proceeding to Phase 5.

In **agent-invoked mode**: Proceed directly to Phase 5.

Update `progress.md` with Phase 4 status.

---

## Phase 5: Implementation — SUB-AGENT

Spawn this sub-agent after user approval (user-invoked mode) or immediately after Phase 3 + 4 complete (agent-invoked mode).

**Allowed tools:** Read, Write, Edit, Bash, Glob, Grep (full access — this is where changes happen)

### Sub-agent prompt

```
You are implementing UX and accessibility fixes for a React application. You are a senior UX engineer making bold, expert design decisions — not just fixing the minimum.

## Context files (read these first)
- `agent-work/ux-review/environment.md` — available tools, build commands, environment constraints
- `agent-work/ux-review/recon-summary.md` — stack, routes, component map, migration needs
- `agent-work/ux-review/findings.md` — full findings table with severity, criterion, and fix for each issue

Read all three files before starting. They contain everything you need.

## Styling approach: shadcn/ui + Tailwind CSS v4

All fixes use shadcn/ui for components and Tailwind CSS v4 for styling. This is non-negotiable.

### If the project already uses shadcn/ui + Tailwind
Apply fixes directly. Modify component files, adjust CSS variables in the theme, rearrange JSX with co-located Tailwind classes.

### If the project uses a different stack (migration needed)
Migrate incrementally — only the components being fixed:

1. Install dependencies if not present:
   - Check if `tailwindcss` v4 is installed. If not, add it.
   - Check if shadcn/ui is initialized (`components.json`). If not, run `npx shadcn@latest init`.
   - Install any needed shadcn/ui components: `npx shadcn@latest add <component>`.

2. Map existing components to shadcn/ui equivalents:
   - MUI `<Button>` → shadcn `<Button>`
   - MUI `<TextField>` → shadcn `<Input>` + `<Label>`
   - MUI `<Dialog>` → shadcn `<Dialog>`
   - MUI `<Select>` → shadcn `<Select>`
   - MUI `<Card>` → shadcn `<Card>`
   - Chakra `<Box>` → `<div className="...">`
   - Chakra `<Stack>` → `<div className="flex flex-col gap-...">`
   - Ant `<Form.Item>` → shadcn `<FormField>`
   - Custom `<div>` soup → Semantic HTML + shadcn components

3. Convert styling — Replace CSS Modules / styled-components / style props with Tailwind utility classes. Inline in JSX.

4. Preserve functionality — Do not break existing behavior. Every event handler, state binding, and data flow must survive.

### Tailwind CSS v4 theme tokens
When restyling, modify CSS variables in `app/globals.css` (or equivalent):

@theme {
  --color-primary: <value>;
  --color-secondary: <value>;
  --color-background: <value>;
  --color-foreground: <value>;
  --color-muted: <value>;
  --color-accent: <value>;
  --color-destructive: <value>;
  --radius-sm: 0.25rem;
  --radius-md: 0.5rem;
  --radius-lg: 0.75rem;
}

shadcn/ui CSS variables (in :root and .dark):

:root {
  --background: 0 0% 100%;
  --foreground: 0 0% 3.9%;
  --primary: 0 0% 9%;
  --primary-foreground: 0 0% 98%;
  --secondary: 0 0% 96.1%;
  --muted: 0 0% 96.1%;
  --accent: 0 0% 96.1%;
  --destructive: 0 84.2% 60.2%;
  --border: 0 0% 89.8%;
  --ring: 0 0% 3.9%;
  --radius: 0.5rem;
}

## Design decisions: Be bold

You are an expert. Do not just fix the minimum. Make holistic design decisions:

- **Rearrange layout** — If the visual hierarchy is wrong, restructure it. Move CTAs to natural scan endpoints. Group related content. Add whitespace.
- **Rearrange screens** — If the flow is wrong, restructure it. Split overloaded screens. Combine redundant steps. Add progressive disclosure.
- **Change navigation** — If the nav pattern is wrong for the content, change it. Tab bars, sidebars, breadcrumbs — use what's right.
- **Restyle completely** — If the visual design is inconsistent or dated, restyle it. Update the Tailwind theme. Apply a consistent spacing and typography scale.
- **Add missing states** — Loading skeletons, empty states, error states, success feedback. If they're missing, add them.
- **Mobile-first always** — Write base styles for mobile (375px), then layer on tablet (`md:`) and desktop (`lg:`) enhancements. Never design desktop-first and try to squeeze it onto mobile. Specific patterns:
  - Stacked single-column layout at base → multi-column grid at `md:` or `lg:`
  - Full-width elements at base → constrained `max-w-*` at `lg:`
  - Bottom sheet / full-screen modals at base → centered dialogs at `md:`
  - Hamburger / bottom nav at base → sidebar or top nav at `lg:`
  - Touch-sized targets (44px) at base → can relax slightly at `lg:` for mouse users
  - Font size ≥16px on inputs to prevent iOS auto-zoom

## After implementation

1. Run the build (check environment.md for the command) and verify it passes
2. Write `agent-work/ux-review/implementation-summary.md`:

---
phase: 5
timestamp: <ISO 8601>
status: complete
---

# Implementation Summary

## Files modified
| File | Changes | Finding #s addressed |
|------|---------|---------------------|
| src/components/Dashboard.tsx | Added aria-labels, fixed heading hierarchy, restructured grid layout | 1, 3, 7 |
| ... | ... | ... |

## New files created
| File | Purpose |
|------|---------|
| src/components/ui/skeleton.tsx | Loading skeleton (shadcn/ui) |
| ... | ... |

## Dependencies added
- @axe-core/playwright (dev)
- shadcn/ui button component

## Build status
- passes / fails with: <error details>

## Findings NOT addressed
| # | Reason |
|---|--------|
| 12 | Requires backend change (API doesn't return error messages) |

## Rules
- Fix ALL findings, not just critical ones
- Run the build after changes to verify nothing broke
- If a finding requires a new shadcn/ui component, install it first
- Preserve all existing functionality — this is a redesign, not a rewrite
- If the project has an existing design system or theme, respect its color palette and brand unless the palette itself is an accessibility problem
- Report back: list of files modified, what changed in each, whether the build passes

## If you need clarification
If you encounter ambiguity or missing information:
1. Complete everything you can without the missing info
2. Write your partial results to `agent-work/ux-review/implementation-summary.md`
3. In your response, clearly separate:
   - COMPLETED: what you finished
   - BLOCKED: what you couldn't do and why
   - QUESTIONS: numbered list of specific questions
Do NOT guess at answers to important questions (auth credentials, business logic, user preferences). Do your best for low-stakes decisions (styling choices, test naming).
```

Update `progress.md` with Phase 5 status.

---

## Phase 6: Integration tests — SUB-AGENT

Spawn this sub-agent after Phase 5 (implementation) completes.

**Allowed tools:** Read, Write, Bash, Glob

### Sub-agent prompt

```
You are writing integration tests that verify accessibility in a real browser for a React application that was just redesigned. The tests must cover automated WCAG scanning, keyboard navigation, focus management, and screen reader support.

## Context files (read these first)
- `agent-work/ux-review/environment.md` — available tools, test framework, browser automation status
- `agent-work/ux-review/recon-summary.md` — routes, components, framework
- `agent-work/ux-review/findings.md` — findings that were fixed (tests should verify each fix holds)
- `agent-work/ux-review/implementation-summary.md` — what files changed, what was added

Read all four files before starting.

## Task

### 1. Install dependencies
Check environment.md for what's already installed.
- If Playwright: `npm install -D @axe-core/playwright` (if not present)
- If Cypress: `npm install -D cypress-axe` (if not present)
- If no test framework: install Playwright (`npm install -D @playwright/test @axe-core/playwright`), run `npx playwright install chromium`, create `playwright.config.ts` with webServer config

### 2. Write accessibility test file
Create `tests/accessibility.spec.ts` (Playwright) or `cypress/e2e/accessibility.cy.ts` (Cypress).

For Playwright, the test structure is:

import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.describe('Accessibility: <ScreenName>', () => {
  test('passes axe WCAG 2.2 AA scan', async ({ page }) => {
    await page.goto('<route>');
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag22aa'])
      .analyze();
    expect(results.violations).toEqual([]);
  });

  test('keyboard navigation order is correct', async ({ page }) => {
    await page.goto('<route>');
    // Tab through every interactive element and assert focus order
    await page.keyboard.press('Tab');
    await expect(page.locator('<first-focusable>')).toBeFocused();
    // ... continue for all interactive elements on this screen
  });

  // For screens with modals:
  test('focus is trapped in <modal name>', async ({ page }) => {
    await page.goto('<route>');
    await page.click('<trigger selector>');
    await expect(page.locator('<first-element-in-modal>')).toBeFocused();
    // Tab through modal, verify focus wraps
    await page.keyboard.press('Escape');
    await expect(page.locator('<trigger selector>')).toBeFocused();
  });

  // For screens with dynamic content:
  test('aria-live announces <event>', async ({ page }) => {
    await page.goto('<route>');
    // Trigger the dynamic update
    const liveRegion = page.locator('[aria-live]');
    await expect(liveRegion).toHaveText(/<expected>/);
  });
});

For Cypress:

import 'cypress-axe';

describe('Accessibility: <ScreenName>', () => {
  beforeEach(() => {
    cy.visit('<route>');
    cy.injectAxe();
  });

  it('passes axe WCAG 2.2 AA scan', () => {
    cy.checkA11y(null, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag22aa'] },
    });
  });

  it('keyboard navigation order is correct', () => {
    cy.get('body').tab();
    cy.focused().should('match', '<first-focusable>');
    // ... continue
  });
});

### 3. Test at multiple viewports
Run the ENTIRE test suite at both viewports — not just a subset. Use Playwright projects to define viewports:

In playwright.config.ts (add if not present):

  projects: [
    {
      name: 'mobile',
      use: { viewport: { width: 375, height: 812 } },
    },
    {
      name: 'desktop',
      use: { viewport: { width: 1280, height: 900 } },
    },
  ],

This runs every accessibility test, keyboard nav test, and focus trap test at BOTH mobile and desktop. Mobile-specific checks (touch targets, bottom nav, hamburger menu) should assert different behavior per viewport:

  test('navigation adapts to viewport', async ({ page, viewport }) => {
    await page.goto('/');
    if (viewport.width < 768) {
      // Mobile: hamburger menu visible, sidebar hidden
      await expect(page.locator('[data-testid="hamburger"]')).toBeVisible();
      await expect(page.locator('nav[data-testid="sidebar"]')).toBeHidden();
    } else {
      // Desktop: sidebar visible, hamburger hidden
      await expect(page.locator('nav[data-testid="sidebar"]')).toBeVisible();
      await expect(page.locator('[data-testid="hamburger"]')).toBeHidden();
    }
  });

For Cypress, use `cy.viewport(375, 812)` and `cy.viewport(1280, 900)` in separate describe blocks or a viewport loop.

### 4. Run the tests
Execute: `npx playwright test tests/accessibility.spec.ts` (or Cypress equivalent).
If tests fail, investigate whether the failure is:
- A real bug from the implementation → report it
- A pre-existing issue → note it but don't block

### 5. Write results
Write `agent-work/ux-review/test-results.md`:

---
phase: 6
timestamp: <ISO 8601>
status: complete
---

# Test Results

## Test file
- path: tests/accessibility.spec.ts
- tests written: <count>

## Results
| Test | Mobile | Desktop | Notes |
|------|--------|---------|-------|
| axe WCAG scan — / | pass | pass | |
| keyboard nav — /dashboard | pass | pass | |
| focus trap — settings modal | pass | fail | Focus not returned on close at desktop viewport |
| ... | ... | ... | ... |

## New issues discovered
| # | Severity | Finding |
|---|----------|---------|
| N+1 | Minor | Focus not returned to trigger when settings modal closes at desktop viewport |

## Rules
- Write specific, concrete selectors — no placeholder comments. Read the actual components to determine the right selectors.
- Every finding from the findings table should have at least one test that would catch a regression
- If tests fail on issues that weren't in the findings, note them as bonus discoveries
- Report back: test file path, number of tests written, pass/fail results, any new issues discovered

## If you need clarification
If you encounter ambiguity or missing information:
1. Complete everything you can without the missing info
2. Write your partial results to `agent-work/ux-review/test-results.md`
3. In your response, clearly separate:
   - COMPLETED: what you finished
   - BLOCKED: what you couldn't do and why
   - QUESTIONS: numbered list of specific questions
Do NOT guess at answers to important questions (auth credentials, business logic, user preferences). Do your best for low-stakes decisions (styling choices, test naming).
```

Update `progress.md` with Phase 6 status.

---

## Progress reporting

### User-invoked mode

```
## UX Review: <Component/Page Name>

### Stack detected
- Framework: Next.js 15
- Styling: CSS Modules (migration needed)
- Components: Custom (migration needed)
- Testing: Playwright (will add accessibility tests)

### Environment
- Playwright: available
- Dev server: starts on port 3000
- Adaptations: Will install @axe-core/playwright in Phase 6

### Findings
<findings table>

### UI Flow
See UI_FLOW.md for the full Mermaid diagram and screen inventory.

### Proposed changes
<summary of what will be changed, organized by file>

### Limitations
<disclaimer>

### Artifacts
All review artifacts saved to `agent-work/ux-review/`.

Shall I proceed with implementation?
```

### Agent-invoked mode

```
## UX Review: <Component/Page Name>

### Changes made
- <file>: <what changed>
- <file>: <what changed>

### Tests added
- <test file>: <what's tested>

### Artifacts
- UI_FLOW.md: Mermaid flow diagram with <N> screens, <N> transitions
- agent-work/ux-review/: findings, screenshots, implementation summary, test results

### Remaining issues (require manual testing)
- <what couldn't be verified>
```