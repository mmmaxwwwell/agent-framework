# Agent Framework

A collection of reusable Claude Code skills — self-contained prompts that teach an agent how to perform specific workflows.

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

## Skills

| Skill | Description |
|-------|-------------|
| [`fix-build`](.claude/skills/fix-build/SKILL.md) | Iteratively fix a failing build/test command with sub-agents |
| [`generate-project`](.claude/skills/generate-project/SKILL.md) | Scaffold a new agent-framework project via interview |
| [`generate-feature`](.claude/skills/generate-feature/SKILL.md) | Plan and add a feature to an existing project |
| [`run-tasks`](.claude/skills/run-tasks/SKILL.md) | Automate task execution with Opus sub-agents |

## License

MIT
