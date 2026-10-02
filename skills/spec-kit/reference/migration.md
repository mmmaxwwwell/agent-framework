# Migration & Versioning Strategy

Every project MUST have an explicit strategy for handling change over time — data schema changes, API version bumps, and configuration format changes.

## Data schema migrations

**Strongly recommended**: Implement idempotent up/down structured migrations using a migration library appropriate for the stack (e.g., Knex/Prisma for Node.js, Alembic for Python, golang-migrate for Go, Diesel for Rust).

Migration requirements:
- **Up migration**: Apply the change (add column, create table, transform data)
- **Down migration**: Reverse the change (drop column, drop table, reverse transform)
- **Idempotent**: Safe to run multiple times — check if already applied before executing
- **Versioned**: Each migration has a sequential version number and timestamp
- **Tested**: Migration up/down is covered by integration tests

If the user defers migrations, document the decision with a warning: "No migration strategy — schema changes will require manual data transformation."

## Database seeding

If the project uses a database, provide a **seed script** that:
1. Creates the schema (runs all migrations)
2. Populates required reference data (roles, categories, default config)
3. Optionally populates sample data for development with known state

The seed script serves double duty:
- **Development bootstrapping**: New developer runs seed, has a working database
- **Integration test setup**: Tests use the seed pattern to create isolated test scenarios with known state

## API versioning

Every project with an API MUST implement versioning from day one:
- **URL path versioning** is the default: `/v1/projects`, `/v2/projects`
- **Latest version alias**: Unversioned path (e.g., `/api/projects`) routes to the latest version. This lets clients that want "always latest" skip versioning, while clients that want stability pin to a version.
- **Semantic versioning**: The project follows semver. The implementing agent MUST have enough context to determine whether a change is a patch (bugfix), minor (new feature, backward compatible), or major (breaking change).

### Backward compatibility policy
The compatibility promise is defined during the interview. If deferred, document: "No backward compatibility policy — all clients assumed internal and updated simultaneously."

When a new API version is introduced:
- Update all documentation (API contracts, CLAUDE.md, README)
- Update the "latest" alias routing
- Document which version is current and which are deprecated

## Admin process parity

Migrations, seeds, maintenance scripts, and any one-off admin tasks MUST run in the same environment as the application — same runtime, same dependencies, same config, same release. Never run a migration from a developer laptop against a production database using different dependency versions. Admin processes MUST:
- Be shipped with the application code (not maintained in separate repos or ad-hoc scripts)
- Use the same dependency isolation as the app (same Nix flake, same virtualenv, same container)
- Run against the same config sources
- Be invocable via named scripts in the project's task runner

## Configuration versioning

When config file formats change between versions:
- Auto-migration: detect old format and upgrade automatically, logging what changed at INFO level
- Clear error message if auto-migration isn't possible, telling the user exactly what to change
- Document config format changes in release notes, README, and agentic documentation
