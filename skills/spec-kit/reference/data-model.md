# Data Model Depth

Spec-kit's plan phase produces `data-model.md`. The skill mandates a minimum level of detail — a shallow field list is not sufficient.

## What `data-model.md` MUST contain

1. **Entity relationship diagram** (ASCII or Mermaid) showing all entities with cardinality (1:1, 1:many, many:many). Every relationship must show both directions and labels.

2. **Per-entity field tables**:

   | Field | Type | Required | Default | Constraints |
   |-------|------|----------|---------|-------------|
   | id | string (UUID) | yes | auto-generated | unique |
   | status | enum | yes | "pending" | one of: pending, active, archived |

3. **State transition rules** for any entity with lifecycle states. Use Mermaid state diagrams or explicit transition tables:

   | From | To | Trigger | Constraints |
   |------|----|---------|-------------|
   | pending | active | user confirms | all required fields populated |
   | active | archived | user deletes | no active child entities |

   Include: all valid transitions, triggers, guard conditions, and terminal states.

   **Note:** These state transitions cover *persistent entity* lifecycles (database records, stored objects). For *runtime/process* state machines (daemon lifecycles, protocol handshakes, connection management), see the `## Runtime State Machines` section in `plan.md`. The two are complementary — data-model covers state at rest; runtime state machines cover state in flight.

4. **Cross-entity constraints**:
   - Uniqueness (e.g., "only one active session per project")
   - Mutual exclusion (e.g., "a user can be either admin or member, not both")
   - Cascading behavior (e.g., "deleting a project archives all its sessions")
   - Referential integrity (e.g., "session.projectId must reference an existing project")

This applies regardless of storage backend — SQL database, document store, filesystem-as-database, or in-memory state. The data model describes the logical schema, not the physical storage.
