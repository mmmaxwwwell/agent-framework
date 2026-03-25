# Specification Structure & Traceability

These patterns ensure that specs are machine-readable, individually testable, and traceable from requirement through implementation to test.

## Functional requirement numbering

Every functional requirement in the spec MUST have a unique identifier:
- Format: `FR-001`, `FR-002`, etc. (sequential within the spec)
- Each requirement is a single, testable statement
- Requirements are grouped by feature area or user story

## Success criteria

Every spec MUST include a **Success Criteria** section with measurable criteria:
- Format: `SC-001`, `SC-002`, etc.
- Each criterion maps to one or more functional requirements
- Criteria are verifiable by tests or inspection

## Story-to-task traceability

Every task in `tasks.md` MUST reference the user story or functional requirement it implements:
- Format: `[Story 3]` or `[FR-015]` suffix on the task description
- Enables bidirectional traceability: from requirement → task → test

## Structured learnings format

`learnings.md` MUST be structured by task ID. Each entry captures: what was discovered, which task revealed it, and actionable implications for later tasks. This creates a pre-validation oracle — agents implementing T015 can read T001-T014's learnings first.

```markdown
### T001 — Custom test reporter
- Gotcha: Node.js test runner custom reporters must export a default function, not a class
- Decision: Using `spec` reporter as base, extending with JSON output

### T008 — WebSocket session streaming
- Gotcha: Must buffer all WebSocket messages from connection time, not from subscription time
- Pattern: Created `BufferedWebSocket` helper that queues messages until consumer is ready
```

## Auto-generated CLAUDE.md

When a project has multiple features, the project's `CLAUDE.md` MUST be kept in sync:
- **Auto-generated sections**: Active technologies, project structure, commands, code style
- **Manual additions section**: Between `<!-- MANUAL ADDITIONS START -->` and `<!-- MANUAL ADDITIONS END -->` markers
- Include a header: `Auto-generated from all feature plans. Last updated: <date>`
- Each new feature spec updates the auto-generated sections without overwriting manual additions

## Interview handoff documents

When the interview completes, produce:
- **`interview-notes.md`**: Key decisions, gaps, open questions — lightweight summary for planning agents
- **`transcript.md`**: Full conversation history for crash recovery
- **`spec.md`**: The structured specification output
