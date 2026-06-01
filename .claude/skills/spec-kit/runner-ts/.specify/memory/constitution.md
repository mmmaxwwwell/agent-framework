<!--
Sync Impact Report
==================
Version change: (initial) → 1.0.0
Modified principles: (none — initial ratification)
Added sections: All — Core Principles (I–VII), Security Perimeter, Development Workflow, Governance
Removed sections: None
Templates requiring updates:
  - .specify/templates/plan-template.md (✅ no changes needed — constitution principles align with default Constitution Check shape)
  - .specify/templates/spec-template.md (✅ no changes needed)
  - .specify/templates/tasks-template.md (✅ no changes needed)
  - .claude/commands/speckit.*.md (✅ no changes needed)
Follow-up TODOs: None
-->

# tabrunner Constitution

The non-negotiable rules that govern how tabrunner is designed, built, and changed. Every spec, plan, task, review, and PR must verify compliance against these principles.

## Core Principles

### I. Single-User, Tailnet-Scoped (NON-NEGOTIABLE)

tabrunner is a single-user tool. The only network it accepts connections from is the user's own Tailnet. The server MUST bind exclusively to a Tailscale interface (Tailscale IP discovered at startup, never `0.0.0.0`). It MUST refuse to start if no Tailscale interface is available. There is no multi-user model, no team features, no public-internet exposure.

**Rationale**: The whole shape of the system — auth, history schema, sandbox model, meta agent — is built around one operator with multiple devices on a private network. Adding "users" later is a v2 redesign, not a knob.

### II. mTLS-TOFU with QR Pairing (NON-NEGOTIABLE)

All HTTP and WebSocket traffic MUST be protected by mutual TLS. The server presents a self-signed certificate (pinned in the PWA at first pairing — Trust On First Use). New client devices pair via a QR code that encodes a one-shot, short-TTL pairing token. During pairing, the client generates its own keypair in-browser (WebCrypto), submits a CSR, and the server signs and persists the resulting client certificate. Every subsequent request MUST present a valid client certificate; unauthenticated requests get TCP-level rejection.

**Rationale**: Tailscale is the perimeter; mTLS is defense in depth. TOFU + QR keeps the UX a single scan per device, and in-browser key generation means the private key never transits the wire — even the pairing channel.

### III. One Tab = One Sandboxed Claude Session (NON-NEGOTIABLE)

Each PWA tab corresponds to exactly one running `claude` CLI session. Sessions MUST be spawned inside a bubblewrap (bwrap) sandbox: only the active project directory and a per-session scratch directory are writable; the network is restricted to the same allowlist as the spec-kit parallel runner (`api.anthropic.com`, `registry.npmjs.org`, `pypi.org`, `files.pythonhosted.org`, `cache.nixos.org`, `github.com`). Closing the tab MUST terminate the session gracefully (SIGTERM, then SIGKILL after a grace period).

**Rationale**: Mirrors the existing parallel_runner.py contract so the security posture is the same across both runners. The 1:1 tab-to-session mapping keeps the mental model simple — what you see in a tab is exactly one process, nothing hidden.

### IV. Single Source-of-Truth History DB

All sessions, messages, tool calls, and meta-agent queries persist to one SQLite database via `better-sqlite3`. The meta agent reads across all sessions; per-tab agents read only their own `session_id`. Schema migrations MUST be versioned and apply forward-only on startup with a fail-fast version check. The DB file is the canonical record — log files are derived artifacts only.

**Rationale**: One DB makes cross-session queries trivial for the meta agent and gives the user one file to back up. SQLite is durable enough for a single-user tool and avoids the operational burden of a server-class database.

### V. TypeScript Strict, Tests Hit Reality

All code is TypeScript with `"strict": true`. Integration tests MUST spawn real `claude` (or a real stub binary that exhibits the same I/O contract), write to a real SQLite file, and connect via a real WebSocket client. Mocks at the integration boundary are forbidden because the prior pattern is: mocks pass, real subprocesses break. Unit tests may mock pure-function inputs only.

**Rationale**: tabrunner's correctness lives in its boundary behavior (subprocess lifecycle, WebSocket framing, mTLS handshake, SQLite concurrency). Mocking those boundaries means testing your mock, not your code.

### VI. Meta Agent is Read-Only in v1

The meta agent MUST be read-only by default. Its MCP tool surface is limited to: query the history DB, tail live stdout/stderr from running sessions, list running PIDs, read files inside the watched project directory. It MUST NOT spawn sessions, send signals, edit files, or run shell commands. Promotion to operator mode is an explicit future feature with its own spec — not a configuration flag in v1.

**Rationale**: A read-only meta agent can be wired up safely and its behavior bounded. An operator-mode agent needs a separate confirmation UI, audit logging, and a kill switch — all out of scope for v1.

### VII. Nix-First, No Global Installs (NON-NEGOTIABLE)

All tools, runtimes, and binaries that tabrunner depends on MUST come from `flake.nix` via `nix develop`. No `npm install -g`, no `uv tool install`, no `nix profile install`, no `curl | sh`. The `specify` CLI runs via `uvx --from "git+https://github.com/github/spec-kit.git@v0.4.1" specify`. NPM/PNPM installs MUST use `--ignore-scripts` and then `npm rebuild <pkg>` only for packages that genuinely need native compilation.

**Rationale**: Reproducible environments, no hidden state in the host, no supply-chain attacks via postinstall scripts. Matches agent-framework's house style.

## Security Perimeter

tabrunner has two layers of defense:

1. **Network**: Tailscale-only binding. No `0.0.0.0`, no localhost-on-public-interface accidents.
2. **Crypto**: mTLS-TOFU with QR pairing (Principle II). Both layers MUST pass before any request reaches application logic.

The "local" preset's "no auth" default is **explicitly overridden** by this constitution. tabrunner is single-user but not local-only — its operator drives it from multiple devices over a private network, so endpoint authentication is required. This is an intentional, documented deviation captured in `interview-notes.md` and `research.md`.

Secrets handling:
- The signing CA private key lives in `data/ca-key.pem` (chmod 600, gitignored).
- Client certificates persist as `data/clients/<fingerprint>.pem`.
- No environment variable carries any private key. Keys are loaded from disk at startup.
- A pre-commit hook MUST reject any file matching `*.pem` or `*.key` outside `*.example`.

## Development Workflow

- **Branching**: direct-to-main, solo developer. No PR ceremony.
- **Commits**: conventional commits (`feat:`, `fix:`, `chore:`, `refactor:`, `docs:`, `test:`). Co-Author trailer for Claude commits per repo policy.
- **CI/CD**: GitHub Actions — lint, typecheck, unit, integration, Tier 1 security scan (Trivy, Semgrep, Gitleaks, npm audit). No deploy stage.
- **Pre-commit hooks**: lint, typecheck on staged files, secret scan, live-key rejection.
- **Tests** (Principle V): `tsx --test` with the spec-kit structured reporter. Three tiers — unit, integration, contract (WebSocket frames + MCP tool schemas).
- **Reviews**: per-phase review/validate cycling per the spec-kit `phases/implement.md` contract. Use `code-review-graph` MCP tools as the first step of every review (Principle from CLAUDE.md stanza).
- **Spec amendments**: agents MAY write `AMENDMENT-*.md` files when a spec premise is wrong; runner forwards to the user for adjudication.

## Governance

This constitution supersedes all other practices. Every PR, plan, and review MUST verify compliance with the seven core principles. Violations require explicit justification recorded in the relevant spec or plan's "Complexity Tracking" section — unjustified violations block merge.

**Amendments**:
- MAJOR: removing or fundamentally redefining a NON-NEGOTIABLE principle.
- MINOR: adding a new principle, materially expanding an existing one, or adding a new section.
- PATCH: clarifications, wording, typo fixes.

All amendments require: (1) a new version number, (2) an updated `Last Amended` date, (3) a Sync Impact Report at the top of this file, (4) propagation review across `.specify/templates/`.

Runtime guidance for agents working inside the project lives in `CLAUDE.md` (project root). When a runtime concern arises that this constitution does not address, it goes in `CLAUDE.md` first; if it becomes a non-negotiable rule, it gets promoted here in the next amendment.

**Version**: 1.0.0 | **Ratified**: 2026-05-23 | **Last Amended**: 2026-05-23
