---
name: spec-kit
description: Initialize and drive a spec-kit (Specification-Driven Development) project using the `specify` CLI. Handles install, init, and walks the user through the full SDD workflow — constitution, specify, clarify, plan, tasks, implement. Use when the user wants to start or continue a spec-kit project.
user-invocable: true
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, WebFetch
argument-hint: [project-name]
---

# Spec-Kit — Specification-Driven Development

You are helping the user work with **spec-kit** (`specify` CLI), GitHub's toolkit for Specification-Driven Development (SDD). In SDD, natural-language specifications are the primary artifact — you write detailed specs describing *what* and *why*, then generate plans, tasks, and implementation from those specs.

## Quick reference

| Phase | Command | What it does |
|-------|---------|--------------|
| 0 | `specify init <name>` | Scaffold project with slash commands |
| 1 | `/speckit.constitution` | Define governance principles & architectural rules |
| 2 | `/speckit.specify` | Write a structured feature specification |
| 3 | `/speckit.clarify` | Identify and resolve ambiguities in specs |
| 4 | `/speckit.analyze` | Validate spec consistency (optional) |
| 5 | `/speckit.plan` | Generate technical implementation plan |
| 6 | `/speckit.tasks` | Break plan into actionable task list |
| 7 | `/speckit.implement` | Execute tasks with TDD, phased ordering |
| 8 | `/speckit.checklist` | Quality assurance checklists |
| 9 | `/speckit.taskstoissues` | Convert tasks to GitHub Issues |

---

## Step 0: Ensure spec-kit is installed

1. Check if `specify` is available: run `which specify || specify --version 2>/dev/null`.
2. **If not installed**, install it:
   ```bash
   uv tool install specify-cli --from git+https://github.com/github/spec-kit.git
   ```
   If `uv` is not available, tell the user they need to install `uv` first (`pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`).
3. Verify: `specify --version`

---

## Step 1: Initialize or locate the project

**If `$ARGUMENTS` contains a project name** (or the user provides one):
- Check if a `.specify/` directory already exists in the current working directory.
  - **If it exists** → skip init, this project is already set up. Tell the user and proceed to Step 2.
  - **If it doesn't exist** → run: `specify init <project-name> --ai claude --script bash`
  - After init, briefly tell the user what was created.

**If no project name provided**:
- Check if `.specify/` exists in the current directory.
  - **If it exists** → this is an existing spec-kit project. Tell the user and proceed to Step 2.
  - **If not** → ask the user for a project name, then init.

---

## Step 2: Guide the user through the SDD workflow

Present the user with their current state and next recommended step. The workflow phases are ordered — each phase builds on the previous one's output.

### Detecting current state

Check which artifacts exist to determine where the user is:

| Artifact | Location | Means |
|----------|----------|-------|
| Constitution | `.specify/memory/constitution.md` | Phase 1 done |
| Feature spec | `specs/<branch-name>/spec.md` | Phase 2 done |
| Clarifications | Updated spec with no `[NEEDS CLARIFICATION]` tags | Phase 3 done |
| Plan | `plan.md`, `research.md`, `data-model.md` | Phase 5 done |
| Tasks | `tasks.md` | Phase 6 done |

### Running each phase

For each phase, the user has two options:
1. **Run the spec-kit slash command** — The slash commands are defined in `.specify/commands/` as markdown prompt files. Read the relevant command file and follow its instructions.
2. **Skip** — If the user wants to skip a phase (e.g., skip clarify for a simple spec), move to the next one.

**How to execute a phase:**

1. Tell the user which phase you're running and why it's next.
2. Read the command template from `.specify/commands/<command-name>.md` (e.g., `.specify/commands/specify.md` for the specify phase).
3. Follow the instructions in that template file. The template contains the full prompt for that phase — it tells you exactly what to do, what inputs to gather, and what outputs to produce.
4. After completing the phase, summarize what was produced and recommend the next step.

### Phase-specific notes

**Constitution (Phase 1):**
- This sets the architectural rules for the project. It's optional but recommended.
- If the user already has strong opinions about architecture, capture them here.
- The constitution template has 9 "articles" covering things like library-first design, test-first development, simplicity, etc.

**Specify (Phase 2):**
- This is the core of SDD — writing the feature spec.
- Focus the user on *what* and *why*, not *how*.
- The spec creates a branch and directory structure under `specs/`.
- Specs get automatic numbering.

**Clarify (Phase 3):**
- Scans for ambiguities across 11 categories.
- Generates up to 5 prioritized questions, presented one at a time.
- Integrates answers back into the spec.

**Plan (Phase 5):**
- Generates `plan.md` plus supporting docs (data models, API contracts, test scenarios).
- Runs a research phase first, then a design phase.
- Checks constitutional compliance.

**Tasks (Phase 6):**
- Generates `tasks.md` with dependency-ordered, phased tasks.
- Tasks marked `[P]` can be parallelized.
- Phases: Setup → Foundational → User Stories (P1-P3) → Polish.

**Implement (Phase 7):**
- Executes tasks with TDD approach — tests before implementation.
- Runs phase by phase, marking tasks complete as it goes.
- Checks extension hooks pre/post execution.

---

## Interaction style

- **Be a guide, not a lecturer.** The user may not know SDD — explain just enough for each step, then do it.
- **Propose, don't interrogate.** When gathering spec information, make concrete suggestions based on what you know about the project.
- **Show progress.** After each phase, summarize what exists and what's next.
- **Respect the workflow order** but don't be rigid — if the user wants to jump ahead or skip a phase, let them.
- **Read the command templates.** The `.specify/commands/` directory contains the actual prompts for each phase. Always read the relevant template before executing a phase — don't wing it from memory.

---

## Rules

- Always check for an existing `.specify/` directory before running `init`.
- Never modify spec-kit's generated command templates in `.specify/commands/`.
- Read the relevant command template before executing each phase.
- If a phase produces output files, verify they were created successfully.
- If `specify init` fails, check Python version (needs 3.11+) and `uv` availability.
- The `--ai claude` flag configures spec-kit for Claude — always use it during init.
