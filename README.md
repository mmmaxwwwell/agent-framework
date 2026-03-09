# Agent Framework

A structured framework for running AI coding agents across multiple sessions on a single project.

## The problem

AI coding agents lose context between sessions. You end up re-explaining the project, the agent redoes work or goes in the wrong direction, and there's no persistent record of what's been done or decided.

## How it works

Every project gets three files:

1. **Prompt file** (`<project>-prompt.md`) — The project spec: what you're building, tech stack, user flows, key files, and the workflow the agent follows. Paste this into the agent at the start of each session.
2. **Task list** (`memory/<project>-tasks.md`) — An ordered checklist of every task. The agent picks up the first unchecked task, does it, marks it done, and stops.
3. **Notes file** (`memory/<project>-notes.md`) — A living document of architecture decisions, technical reference, and open questions. The agent reads this for context and updates it with new findings.

The agent reads all three files at the start of each session, executes one task, updates the task list and notes, and reports what it did.

## Getting started

### 1. Scaffold a new project

Paste the contents of `generator-prompt.md` into an AI chat (Claude, ChatGPT, etc.). It will interview you about your project and generate all three files.

The generator will:
- Ask about your project, tech stack, and goals
- Research libraries and APIs you mention
- Draft a task breakdown and iterate with you
- Generate the prompt, task list, and notes files

### 2. Add features

Once your project is scaffolded, use `feature-prompt.md` to plan and add new features. Paste it into an AI chat and it will interview you about the feature, read your codebase, and generate:

1. **Feature prompt** (`<feature>-prompt.md`) — A self-contained prompt for the feature with overview, architecture decisions, key files, and patterns to follow.
2. **Feature tasks** (`memory/<feature>-tasks.md`) — Task checklist scoped to the feature.
3. **Feature notes** (`memory/<feature>-notes.md`) — Feature-specific context, decisions, and technical reference.

Run the feature prompt the same way you run the project prompt — paste it in, the agent picks up the next task, does it, and stops.

### Or write them manually

Use the template structures in `generator-prompt.md` and `feature-prompt.md` as a reference and create the files yourself.

## Usage

Each agent session:

1. Paste the prompt file into a new agent session
2. The agent reads the task list and notes
3. It executes the first unchecked task
4. It updates both files with progress and findings
5. It stops and reports what it did

Repeat until done.

## Files

- `generator-prompt.md` — The meta-prompt. Give this to your AI to scaffold a new project.
- `feature-prompt.md` — The feature meta-prompt. Give this to your AI to plan and add a feature to an existing project.

