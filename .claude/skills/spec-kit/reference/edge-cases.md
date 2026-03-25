# Edge Case Enumeration

Every spec MUST include an **Edge Cases & Failure Modes** section after the user stories. Without this, implementing agents encounter ambiguous situations and either guess wrong, write BLOCKED.md (wasting a run), or implement inconsistently across related features. When edge cases are enumerated upfront, agents have a lookup table for "what should happen when X goes wrong."

After defining user stories (Phase 2), enumerate edge cases for every major flow. For each edge case, specify the **trigger** and the **expected behavior** — not implementation details, just what the system should do.

## Categories to probe

| Category | Example edge cases |
|----------|-------------------|
| **Timeout** | What happens when an API call, external service, or user action takes too long? |
| **Crash/restart** | What happens when the server, agent, or client process crashes mid-operation? |
| **Concurrent access** | What happens when two users/agents/processes touch the same resource simultaneously? |
| **Invalid input** | What happens with malformed data, wrong types, missing fields, or values outside valid ranges? |
| **Partial completion** | What happens when a multi-step flow fails halfway through? Is state rolled back or left partial? |
| **Network failure** | What happens when a connection drops, a WebSocket disconnects, or DNS fails? |
| **Resource exhaustion** | What happens when disk is full, memory is exhausted, or rate limits are hit? |
| **Missing dependencies** | What happens when an external service is unavailable, a file doesn't exist, or a tool isn't installed? |
| **Duplicate operations** | What happens when the same request is sent twice (retries, double-clicks, replayed messages)? |
| **Permission/auth failure** | What happens when credentials expire, tokens are invalid, or permissions are insufficient? |
| **Data migration/upgrade** | What happens when the system encounters data from a previous version? |

## How to integrate into the workflow

- **Specify phase**: Probe for edge cases explicitly — don't wait for the user to volunteer them
- **Clarify phase**: Any edge case marked `[NEEDS CLARIFICATION]` must be resolved before planning
- **Plan phase**: Edge cases inform test scenarios. Each enumerated edge case maps to at least one test
- **Tasks phase**: Edge case tests appear alongside their feature's test tasks, not in a separate phase
