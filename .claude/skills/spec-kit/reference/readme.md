# README.md — Human-Facing Project Documentation

Every project MUST ship a comprehensive `README.md` at the repository root. This is the first thing a human sees — it must answer "what is this, why should I care, and how do I use it" within 30 seconds. The README targets **humans**, not agents (CLAUDE.md handles agentic documentation).

## Cognitive funneling principle

Order sections from broadest to most specific. Let readers bail out early if the project isn't for them. Lead with *why*, not *how*.

## Required sections

### 1. Title + tagline

The H1 heading. If the name isn't self-explanatory, add a one-sentence tagline below it.

```markdown
# project-name

One-sentence description of what it does and why it exists.
```

### 2. Badges

3–6 shields conveying at-a-glance metadata. Place directly below the title. Common badges:

| Badge | When to include |
|-------|----------------|
| CI status | Always (if CI exists) |
| Test coverage | Always (if coverage is tracked) |
| Latest version/release | Libraries, CLIs, published packages |
| License | Always |
| Security scan status | If SARIF uploads are configured |

Use [Shields.io](https://shields.io) or GitHub's built-in badge URLs. More than 6 badges becomes noise — pick the most useful ones.

### 3. Description / About

1–3 paragraphs answering:
- What does this project do?
- What problem does it solve?
- Why does it exist? (motivation, not implementation details)
- What differentiates it from alternatives? (if applicable)

Lead with why a user should care. Save tech stack details for later.

### 4. Visuals / Demo

At least one of:
- Screenshot (UI projects)
- Terminal recording or output sample (CLI tools)
- Architecture diagram (infrastructure/library projects)
- Link to live demo (web apps)

This lets people evaluate the project without installing it. Use `<details>` for long recordings.

### 5. Features

Bulleted list of key capabilities. One line per feature. Only include if the description alone doesn't convey scope.

### 6. Table of Contents

Only if the README exceeds ~4 screenfuls. Use a collapsible `<details>`/`<summary>` block or rely on GitHub's auto-generated TOC.

### 7. Getting Started / Quick Start

The fastest path from zero to working. Three sub-sections:

**Prerequisites** — OS, runtime versions, system dependencies, required accounts/keys. Be specific about versions.

**Installation** — Step-by-step commands. Copy-paste friendly. Include all common install methods (Nix, package manager, binary download, from source).

**First run / Hello World** — The minimal command or code snippet to verify it works. Show expected output.

```markdown
## Getting Started

### Prerequisites
- Go 1.22+
- Nix (recommended) or manual dependency installation

### Installation

#### With Nix (recommended)
\`\`\`bash
nix develop
make build
\`\`\`

#### Without Nix
\`\`\`bash
go install github.com/example/project@latest
\`\`\`

### Quick start
\`\`\`bash
project init
project run --example
# Expected output: "Hello from project v0.1.0"
\`\`\`
```

### 8. Usage

Detailed usage beyond the quick start:
- Common workflows with examples
- CLI flags / subcommands (with a summary table for CLIs)
- Code examples with expected output (for libraries)
- Configuration patterns

Use code blocks liberally. Link to extended examples if too long to inline.

### 9. Configuration

Document all configuration options. A table works well:

| Variable / Flag | Type | Default | Description |
|----------------|------|---------|-------------|
| `PORT` | int | `8080` | Server listen port |

For projects with many options, link to a dedicated config reference and only show the essential ones here.

### 10. Architecture / Project Structure

Brief overview of codebase organization. A directory tree with one-line descriptions is the minimum:

```
src/
  agent/     # SSH agent protocol handler
  daemon/    # Device registry and lifecycle
  pairing/   # QR code pairing server
```

For complex projects, include a high-level architecture diagram or link to a dedicated `ARCHITECTURE.md`.

### 11. Development

How to set up a development environment and contribute code:
- Dev environment setup (should mirror `reference/dx.md` quick start)
- How to run tests
- How to lint / format
- Link to `CONTRIBUTING.md` for full contributor guidelines

### 12. Security

For projects with a security surface:
- How to report vulnerabilities (link to `SECURITY.md` or security policy)
- Key security design decisions (brief — link to docs for details)
- If applicable: threat model summary

### 13. License

One line stating the license name, linking to the `LICENSE` file:

```markdown
This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
```

### 14. Acknowledgments (optional)

Credit notable contributors, libraries, inspirations, or funding. Keep it short.

## Conditional sections — include when applicable

| Condition | Section | Content |
|-----------|---------|---------|
| Project is a library/SDK | **API Reference** | Document public API surface with examples. Link to generated docs (GoDoc, TypeDoc, etc.) |
| Project has a roadmap | **Roadmap** | High-level planned features. Link to GitHub project board or milestones |
| Project is open source | **Contributing** | Full section or link to `CONTRIBUTING.md`. Cover: bug reports, feature proposals, PR process, code style |
| Project has CI with secrets | **CI Setup** | Document every secret/token the pipeline requires (per `reference/cicd.md`) |
| Project uses backing services | **Infrastructure** | How to run backing services locally (databases, queues, emulators) |
| Project status is non-obvious | **Status** | Prominent notice if archived, experimental, alpha, or seeking maintainers. Put at the TOP. |
| Project has a support channel | **Support / Getting Help** | Where to ask questions (discussions, Discord, issue tracker). Reduces support noise in issues. |

## Quality checklist

Before finalizing the README, verify:

- [ ] Installation commands work when pasted into a terminal on a clean machine
- [ ] Every code example shows expected output
- [ ] No stale version numbers, dead links, or references to removed features
- [ ] Badges point to live endpoints (CI, coverage, release)
- [ ] The README answers "what, why, how" within the first screenful
- [ ] Configuration docs match the actual config schema
- [ ] License section exists and matches the `LICENSE` file

## Principles

- **Respect the reader's time** — be concise. Long is better than incomplete, but don't pad.
- **Copy-paste friendly** — installation and usage commands must work verbatim.
- **Keep it current** — a stale README is worse than a short one. If you can't maintain a section, cut it.
- **Separate concerns** — for lengthy content (full API docs, contributing guides, changelogs), use dedicated files and link from the README.
- **Test your instructions** — follow your own Getting Started steps on a fresh environment.
- **README ≠ CLAUDE.md** — the README is for humans browsing GitHub. CLAUDE.md is for agents working in the codebase. Don't duplicate content between them; link instead.

## Preset behavior

- **POC**: Title, one-paragraph description, quick start (install + run). Nothing else. Speed over polish.
- **Local**: Full README minus badges, CI setup, contributing, and security sections.
- **Library**: Full README including API reference, badges, contributing guide, and semantic versioning notes.
- **Extension**: Full README including platform-specific install instructions, marketplace badges, and permission explanations.
- **Public**: Full README including security section and infrastructure setup.
- **Enterprise**: Full README — every section, no exceptions.

## What the spec and plan MUST include

- **Spec (Phase 2)**: No specific README requirements — the spec drives content, the README documents it.
- **Plan (Phase 5)**: Include a README generation task in the Polish phase, after all features are implemented. The README must reflect what was actually built, not what was planned.
- **Tasks (Phase 6)**: A late-phase task to generate `README.md` from the implemented project state. See below.

## Task generation guidance

Include a README task in the **Polish phase** (after all feature phases, before CI/CD validation):

```
- [ ] T0XX Generate README.md: write comprehensive human-facing README following reference/readme.md structure. Include: title, badges, description, demo/visuals, features, getting started (prerequisites, install, first run), usage with examples, configuration table, architecture overview, development setup, security notes, license. Verify all commands work and all links resolve. [Story: developer onboarding]
```

The task goes late because the README should document what exists, not what's planned. Writing it before implementation means rewriting it after every change.
