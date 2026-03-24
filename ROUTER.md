# Skill Router

Use this file to select the right skill(s) for a task. Read the table, match against the descriptions, then follow each matching skill's `SKILL.md`.

## Available Skills

| Skill | Path | Use when |
|-------|------|----------|
| code-review | `.claude/skills/code-review/SKILL.md` | Review code changes for bugs, security issues, performance problems, and quality concerns. Language-agnostic base layer — only use this if no language-specific code-review skill matches (e.g. code-review-react, code-review-node), since those already include all base checks. |
| code-review-node | `.claude/skills/code-review-node/SKILL.md` | Node.js-specific code review. Extends the base code-review skill with checks for async/await pitfalls, event loop blocking, prototype pollution, dependency security, and Node runtime patterns. Use when reviewing Node.js or backend JavaScript/TypeScript code. |
| code-review-react | `.claude/skills/code-review-react/SKILL.md` | React-specific code review. Extends the base code-review skill with checks for hooks correctness, component design, render performance, state management, and React security patterns. Use when reviewing React, Next.js, or React-based frontend code. |
| fix-build | `.claude/skills/fix-build/SKILL.md` | Repeatedly run a build/test command in a sub-agent loop, fixing errors each iteration until the command passes. Use when the user wants to fix a failing build, test suite, linter, or any command that should exit 0. |
| generate-feature | `.claude/skills/generate-feature/SKILL.md` | Plan and generate a new feature for an existing agent-framework project. Interviews the user, researches the codebase, then generates a feature prompt, task list, and notes file. Use when adding a feature to a project that already has a project prompt and task list. |
| generate-project | `.claude/skills/generate-project/SKILL.md` | Scaffold a new AI-agent-driven project. Interviews the user about their project, researches the codebase and libraries, then generates a prompt file, task list, and notes file. Use when starting a new project with the agent framework. |
| run-tasks | `.claude/skills/run-tasks/SKILL.md` | Process agent-framework task lists by spawning Opus sub-agents to execute each incomplete task autonomously. Use when the user wants to run tasks from a project or feature prompt. |
| spec-kit | `.claude/skills/spec-kit/SKILL.md` | Initialize and drive a spec-kit (Specification-Driven Development) project using the `specify` CLI. Handles install, init, and walks the user through the full SDD workflow — constitution, specify, clarify, plan, tasks, implement. Enforces end-to-end integration testing with real server implementations, structured agent-readable test output, and a fix-validate loop after every feature. Use when the user wants to start or continue a spec-kit project. |
| ux-review | `.claude/skills/ux-review/SKILL.md` | Review React app screenshots and code for accessibility, layout, and UX issues using structured heuristic evaluation. Makes bold design decisions — rearranges screens, fixes accessibility, restyles with shadcn/ui + Tailwind CSS v4. Handles migration from other frameworks. When invoked by a user, presents findings for review before applying. When invoked by a sub-agent, implements fixes automatically. |

## Selection

Match the user's request against the **Use when** column. Apply every skill that matches — multiple skills can be used in the same task. If no skill matches, proceed without the router.

### Code review precedence

The code-review skills form a hierarchy. Language-specific skills include all base checks, so **never load code-review alongside a language-specific variant** — that would duplicate the base checks. Selection rules:

1. If the project is React / Next.js → use **code-review-react** (skip code-review)
2. If the project is Node.js / backend JS/TS → use **code-review-node** (skip code-review)
3. If the project is both (e.g. Next.js full-stack) → use **code-review-react** (it covers the most relevant frontend + general checks; Node-specific backend patterns are also covered by the general categories)
4. If the project uses neither React nor Node.js, or you can't determine the stack → use **code-review**

When uncertain, check `package.json` or file extensions in the diff to determine which skill to load.

## How to Use a Skill

1. **Announce**: Tell the user which skill(s) you are loading. ALWAYS say it out loud — e.g. "Loading skill: **generate-feature**". Never silently load a skill.
2. Read the skill's `SKILL.md` at the path above
3. Follow its instructions exactly
4. The `SKILL.md` contains the full prompt — frontmatter is metadata, the body is your instructions
