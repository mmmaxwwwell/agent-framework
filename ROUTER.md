# Skill Router

Use this file to select the right skill(s) for a task. Read the table, match against the descriptions, then follow each matching skill's `SKILL.md`.

## Available Skills

| Skill | Path | Use when |
|-------|------|----------|
| fix-build | `.claude/skills/fix-build/SKILL.md` | Repeatedly run a build/test command in a sub-agent loop, fixing errors each iteration until the command passes. Use when the user wants to fix a failing build, test suite, linter, or any command that should exit 0. |
| generate-feature | `.claude/skills/generate-feature/SKILL.md` | Plan and generate a new feature for an existing agent-framework project. Interviews the user, researches the codebase, then generates a feature prompt, task list, and notes file. Use when adding a feature to a project that already has a project prompt and task list. |
| generate-project | `.claude/skills/generate-project/SKILL.md` | Scaffold a new AI-agent-driven project. Interviews the user about their project, researches the codebase and libraries, then generates a prompt file, task list, and notes file. Use when starting a new project with the agent framework. |
| run-tasks | `.claude/skills/run-tasks/SKILL.md` | Process agent-framework task lists by spawning Opus sub-agents to execute each incomplete task autonomously. Use when the user wants to run tasks from a project or feature prompt. |
| ux-review | `.claude/skills/ux-review/SKILL.md` | Review React app screenshots and code for accessibility, layout, and UX issues using structured heuristic evaluation. Makes bold design decisions — rearranges screens, fixes accessibility, restyles with shadcn/ui + Tailwind CSS v4. Handles migration from other frameworks. When invoked by a user, presents findings for review before applying. When invoked by a sub-agent, implements fixes automatically. |

## Selection

Match the user's request against the **Use when** column. Apply every skill that matches — multiple skills can be used in the same task. If no skill matches, proceed without the router.

## How to Use a Skill

1. **Announce**: Tell the user which skill(s) you are loading. ALWAYS say it out loud — e.g. "Loading skill: **generate-feature**". Never silently load a skill.
2. Read the skill's `SKILL.md` at the path above
3. Follow its instructions exactly
4. The `SKILL.md` contains the full prompt — frontmatter is metadata, the body is your instructions
