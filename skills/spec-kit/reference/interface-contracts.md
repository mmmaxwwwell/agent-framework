# Interface Contracts (Internal)

When a project is decomposed into tasks that run in parallel or in sequence across phases, the data that flows between tasks must be explicit. Without formal interface contracts, producer tasks pick file paths, formats, and protocols that consumer tasks don't expect — causing integration failures that waste fix-validate cycles.

This reference defines the contract format and when to create contracts.

## When to create an interface contract

Create an IC entry for any shared artifact between tasks:
- **File paths** — config files, cert stores, socket paths, PID files, database files
- **Data formats** — JSON schemas, PEM encoding, protobuf wire format, structured log format
- **Environment variables** — variables one task sets that another reads
- **Socket/IPC protocols** — Unix socket paths, named pipes, message formats
- **CLI interfaces** — flags, stdin/stdout format, exit codes between spawned processes

If two tasks touch the same file, socket, env var, or data format, there MUST be an IC entry.

## Contract table format

In `plan.md`, add an `## Interface Contracts (Internal)` section:

| IC | Name | Producer | Consumer(s) | Specification |
|----|------|----------|-------------|---------------|
| IC-001 | Cert store layout | T005 | T008, T033 | Dir: `~/.config/app/certs/`, CA: `ca.pem`, device: `<fingerprint>.pem`, format: PEM X.509, permissions: 0600 |
| IC-002 | Device registry | T008 | T033, T041 | File: `~/.config/app/devices.json`, schema: see data-model.md §Devices, permissions: 0600 |
| IC-003 | Agent socket | T006 | T033, tests | Path: `$XDG_RUNTIME_DIR/app/agent.sock`, protocol: SSH agent (RFC 4252) |

Each contract specifies:
1. **Location** — exact path or path pattern (use env var references for dynamic paths)
2. **Format** — encoding, schema reference, or wire protocol
3. **Permissions** — file mode, ownership (for security-sensitive artifacts)
4. **Lifecycle** — who creates it, who deletes it, what happens on crash

## Task-level cross-references

In `tasks.md`, each task that produces or consumes a shared artifact references the contract:

```markdown
- [ ] T005 Implement cert store [FR-003] [produces: IC-001]
  Done when: certs written to IC-001 path in PEM format with 0600 permissions; unit test verifies write and read-back

- [ ] T008 Implement device registry [FR-005] [consumes: IC-001] [produces: IC-002]
  Done when: registry loads certs from IC-001 path; devices.json matches IC-002 schema; integration test covers add/remove device
```

The `[produces: IC-xxx]` and `[consumes: IC-xxx]` tags make data flow visible in the task list. The runner does not parse these tags — they are for implementing agents and human reviewers.

## Relationship to other spec-kit artifacts

- **`reference/api-contracts.md`** — covers *external* interfaces (REST, gRPC, WebSocket, IPC protocols between processes). Interface contracts cover *internal* shared state between tasks within the same codebase.
- **`data-model.md`** — covers *persistent data schemas* (entity fields, relationships, state transitions). Interface contracts cover the *file-system-level interface* (paths, permissions, encoding) and ephemeral shared state.
- **`learnings.md`** — captures discoveries *after* implementation starts (reactive). Interface contracts define expectations *before* implementation (proactive). Learnings may refine contracts when agents discover the planned interface doesn't work.

## Preset behavior

- **POC**: skip — tasks run serially and can read each other's code
- **Local, library, extension, public, enterprise**: include for any project with 2+ tasks that share state
