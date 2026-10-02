# Developer Experience (DX) Tooling

Every project MUST ship with first-class developer experience out of the box. A new developer (or agent) should be able to clone the repo, run one command, and have a fully working development environment. Never force them to remember raw commands.

## One-command dev setup

- **If Nix is available**: `nix develop` enters the dev shell with all tools. For projects using `devenv` or `process-compose` via Nix, `nix develop --command process-compose` (or equivalent) can start everything in one step.
- **`npm run dev`** (or equivalent) — starts the dev server, watches for changes, and starts all backing services
- If backing services need setup first, the dev command handles it automatically (idempotent)
- The command MUST print a clear summary on startup: what's running, what ports, and how to access it
- The dev command MUST check for `.env` and, if missing, copy `.env.example` to `.env` and tell the developer to fill in secrets

## Script inventory

At minimum:

| Script | Purpose |
|--------|---------|
| `dev` | Start everything for local development |
| `test` | Run all tests |
| `test:unit` | Run unit tests only |
| `test:integration` | Run integration tests only |
| `lint` | Run linter |
| `lint:fix` | Run linter with auto-fix |
| `typecheck` | Run type checker (if applicable) |
| `build` | Production build |
| `db:migrate` | Run database migrations (if applicable) |
| `db:seed` | Seed the database (if applicable) |
| `db:reset` | Drop + recreate + migrate + seed (if applicable) |
| `codegen` | Run all code generation (if applicable) |
| `clean` | Remove build artifacts, test-logs, temp files |
| `clean:all` | Nuclear option — remove ALL dev state: build artifacts, test-logs, node_modules/venv, database files, generated files, dev certs, .env (back to clone-fresh). After this, `npm run dev` rebuilds everything from scratch. |
| `check` | Run all validation: lint + typecheck + test |

## Dev server requirements

- **Hot reload / HMR** — file changes reflect immediately
- **Proxy configuration** — if separate frontend/backend, proxy API requests so you don't deal with CORS in dev
- **HTTPS in development** (if needed) — generate self-signed dev certificates automatically. Required when OAuth callbacks, secure cookies, or service workers demand HTTPS.
- **Port selection** — consistent, documented port; clear error on conflict with the conflicting process identified (not just `EADDRINUSE`)

## Environment management

- **`.env.example`** — committed to git, contains every env var with placeholder values and comments
- **`.env`** — gitignored, created from `.env.example`
- **Environment isolation** — Nix flakes are the default when `nix` is available:
  - `flake.nix` with `devShells.default` providing all tools (runtimes, CLIs, databases, linters, formatters). The flake should use `nixpkgs` for packages and declare all project inputs.
  - `.envrc` with `use flake` for auto-activation (auto-activates the dev shell on `cd`); `.direnv/` gitignored
  - All dependencies go in `flake.nix`, not global installs or language-specific version managers (`nvm`, `pyenv`, `rbenv`, etc.)
  - Prefer `process-compose` or `devenv` over Docker Compose for backing services. Only use Docker for services with no Nix package.
  - `flake.lock` committed for reproducibility — every developer and CI runner gets identical toolchains
  - Admin process parity: migrations, seeds, and scripts run inside `nix develop` — same tools, same versions as the app
- **If Nix is NOT available**: Fall back to devcontainers or Docker Compose
- **If supporting non-Nix users** (e.g., open-source project): include a `Dockerfile` or `devcontainer.json` as a fallback, but the Nix path is primary

## Code generation

If the project uses codegen (ORM schemas, GraphQL types, protobuf, OpenAPI, etc.):
- `codegen` script runs all generators in correct order
- Generated files placed in a dedicated directory (e.g., `src/generated/`, `__generated__/`) with `.gitignore` if generated at build time, or committed if part of source tree. Alternatively, prefix with a `// @generated` comment and a `DO NOT EDIT` header.
- Dev command runs codegen automatically before starting
- Watch mode for schema-driven codegen (if applicable)

## Debugging setup

- **VS Code `launch.json`** — debug configs for: attaching to dev server, running tests with debugger, running specific test file. Per-language attach methods: Node.js `--inspect`, Python `debugpy`, Go `dlv`, Rust `lldb`.
- **JetBrains** — add run/debug configurations if the user requests it
- **Source maps** enabled in development
- **Debugger-friendly dev command** — starts with debugger port open by default

## CLAUDE.md integration

The project's `CLAUDE.md` MUST include a "Development" section with:

```markdown
## Development

### Quick start
1. `nix develop` (or `npm install --ignore-scripts && npm rebuild` if not using Nix)
2. `npm run dev`

### Available scripts
| Script | Purpose |
|--------|---------|
| `dev` | Start everything for local development |
| `test` | Run all tests |
| ... |

### Environment setup
Copy `.env.example` to `.env` and fill in secrets. See the config documentation for all available keys.
```

## Preset behavior

- **POC**: `dev` script only. `.env.example` if env vars are used. Skip everything else.
- **Local**: Full DX minus HTTPS dev certs, proxy config (unless needed), JetBrains configs.
- **Public**: Full DX including HTTPS dev certs if OAuth/service workers require it, proxy if separate frontend/backend.
- **Enterprise**: Full DX — everything including HTTPS dev certs, proxy, JetBrains configs, custom developer workflow scripts.

## What the spec and plan MUST include

- **Spec (Phase 2)**: Include functional requirements for DX tooling — one-command setup, script inventory, dev server config, debugging configs
- **Plan (Phase 5)**: DX tooling tasks in the Foundational Infrastructure phase (Phase 2), before feature work. Include: task runner setup, script inventory, dev server configuration, environment management, debugging configs, CLAUDE.md generation
