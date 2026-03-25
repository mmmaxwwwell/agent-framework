# Agent Framework

A collection of reusable Claude Code skills — self-contained prompts that teach an agent how to perform specific workflows.

## Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI installed
- [Nix](https://nixos.org/download/) (recommended) — skills default to Nix flakes for dependency and environment management. Without Nix, skills fall back to Docker/devcontainers, but the experience is best with Nix.

## Install

Add this to your `~/CLAUDE.md` so the agent can discover skills automatically:

```markdown
Before starting any task, read the skill router at /path/to/agent-framework/ROUTER.md.
Follow the instructions of every skill that matches the task. If no skill matches, proceed normally.
```

Replace `/path/to/agent-framework` with the actual path (e.g. `~/git/agent-framework`).

## How it works

Each skill is a `SKILL.md` file containing a complete prompt. Skills can be invoked as Claude Code slash commands or pasted into any AI chat. The [`ROUTER.md`](ROUTER.md) file lets agents discover and select skills automatically without slash commands.

## Getting started

### With Claude Code

Install the skills by copying `.claude/skills/` into your project (or `~/.claude/skills/` for global access). Then invoke them as slash commands (e.g. `/generate-project`, `/run-tasks`).

### Autonomous skill discovery

Point any agent at [`ROUTER.md`](ROUTER.md) and it will match the task to the right skill automatically.

### Without Claude Code

The skill files at `.claude/skills/*/SKILL.md` contain the full prompts. Paste the contents of any `SKILL.md` into any AI chat and it will work — the frontmatter is ignored by non-Claude-Code tools.

## Which skill should I use?

```
Building something new from scratch?
├── Want full spec-driven development (specs → plans → tasks → autonomous implementation)?
│   └── /spec-kit
└── Want a quick project scaffold (prompt file + task list, no formal specs)?
    └── /generate-project

Adding to an existing project?
├── New feature → /generate-feature
├── Run an existing task list → /run-tasks
└── Fix a failing build or test suite → /fix-build

Reviewing code?
├── React / Next.js → /code-review-react
├── Node.js / backend JS/TS → /code-review-node
└── Anything else → /code-review

Reviewing UI?
└── /ux-review
```

### spec-kit vs generate-project

Both create new projects, but they work very differently:

- **`/spec-kit`** is the full Specification-Driven Development workflow. It interviews you, writes a formal spec, runs an analyze loop to find gaps, generates an architecture plan with data models and API contracts, then produces a task list. Implementation agents run in a sandboxed parallel runner with fix-validate loops. Best for: real projects you intend to ship.

- **`/generate-project`** is a lightweight scaffolder. It interviews you briefly, then generates a prompt file and task list. No formal specs, no architecture docs, no sandbox. Best for: quick prototypes, experiments, or when you already know what you want and just need a task list to hand to `/run-tasks`.

## Example: starting a project with spec-kit

```
you:   /spec-kit my-api
claude: Loading skill: spec-kit. Installing specify CLI into flake.nix...
        Project initialized. Starting Phase 2: Specification Interview.
        What are you building? Tell me about the core problem this solves.
you:   A REST API for managing book reviews. Users can post reviews, rate books,
       and see aggregated ratings.
claude: [asks ~10 follow-up questions about auth, data model, deployment, etc.]
        ...
        Interview complete. Generating specification with specify...
        Running analyze loop — checking for ambiguities...
        [2 issues found, auto-fixing...]
        Specification clean. Moving to Phase 5: Plan.
        [generates architecture plan, data model, API contracts]
        Plan complete. Moving to Phase 6: Tasks.
        [generates task list with 14 tasks across 4 phases]
        Ready for implementation. Run the parallel runner? (y/n)
you:   y
claude: [launches sandboxed agents to implement tasks in parallel]
```

Each phase auto-advances to the next. The agent asks for confirmation before launching implementation.

## Skills

| Skill | Description |
|-------|-------------|
| [`code-review`](.claude/skills/code-review/SKILL.md) | Review code for bugs, security, performance — language-agnostic base layer |
| [`code-review-node`](.claude/skills/code-review-node/SKILL.md) | Node.js-specific review (extends code-review with async, event loop, dependency checks) |
| [`code-review-react`](.claude/skills/code-review-react/SKILL.md) | React-specific review (extends code-review with hooks, render perf, state management checks) |
| [`fix-build`](.claude/skills/fix-build/SKILL.md) | Iteratively fix a failing build/test command with sub-agents |
| [`generate-project`](.claude/skills/generate-project/SKILL.md) | Scaffold a new agent-framework project via interview |
| [`generate-feature`](.claude/skills/generate-feature/SKILL.md) | Plan and add a feature to an existing project |
| [`run-tasks`](.claude/skills/run-tasks/SKILL.md) | Automate task execution with Opus sub-agents |
| [`spec-kit`](.claude/skills/spec-kit/SKILL.md) | Initialize and drive spec-kit (SDD) projects — specs, plans, tasks, implementation |
| [`ux-review`](.claude/skills/ux-review/SKILL.md) | Review and fix accessibility, layout, and UX in React apps |

## License

MIT
