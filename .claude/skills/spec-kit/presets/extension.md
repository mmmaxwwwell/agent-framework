# Preset: Browser / IDE Extension

**Goal**: Enterprise-grade engineering for extensions that run inside a host platform (browser extensions, VS Code extensions, JetBrains plugins, etc.). Same rigor as production systems — comprehensive tests, full CI/CD with store publish pipeline, thorough documentation — but scoped to the sandboxed, event-driven, permission-gated world of extensions. Extensions face unique constraints: host platform APIs change between versions, store review can reject submissions, users grant sensitive permissions, and the runtime sandbox limits what's possible.

## Interview phase overrides

**Skip entirely** — do not ask about:
- CORS policy (handled by the host platform / manifest permissions)
- Rate limiting & backpressure (not applicable — extension, not a server)
- Graceful shutdown (handled by host platform lifecycle events — `onSuspend`, `deactivate`, etc.)
- Health checks (not applicable)
- Observability infrastructure (skip metrics/tracing — structured logging to extension console is sufficient)
- Process architecture (determined by the host platform — service worker, content script, sidebar, etc.)
- Database migration strategy (extensions use browser storage / VS Code globalState — not traditional databases)

**Default without asking** (use these unless the user volunteers a preference):
- Logging: structured logging to the host platform's console/output channel. Include log levels. For browser extensions, use `console.log`/`console.error` with structured prefixes. For VS Code, use an OutputChannel.
- Error handling: full error hierarchy. Errors shown to users must be actionable ("Could not connect to X. Check your network and try again." not "Error: ECONNREFUSED"). Include error telemetry opt-in if the extension collects usage data.
- Configuration: host platform's settings API (VS Code `contributes.configuration`, browser extension `chrome.storage.sync`). Validate on read, provide defaults for every setting, migrate settings between extension versions.
- Storage: use the host platform's storage APIs. For browser extensions: `chrome.storage.local` for large data, `chrome.storage.sync` for user preferences (synced across devices). For VS Code: `globalState`, `workspaceState`, `secrets` for credentials. Never use `localStorage` in browser extensions (not available in service workers).
- Auth: if the extension needs to authenticate with an external service, use the host platform's auth flow (VS Code `authentication` API, browser extension `identity` API). Never store tokens in plaintext — use the secrets API.
- Security: follow the principle of least privilege for permissions. Request only what's needed. Use optional permissions for features that not all users need. Content Security Policy in manifest. No `eval()`, no inline scripts, no remote code loading.
- CI/CD: full pipeline — lint, build, test (unit + integration), security scan, package extension, publish to store. Include: manifest validation, permission audit, size budget check, screenshot generation for store listing.
- Branching: feature branches with PRs. Main branch is always publishable.
- DX tooling: full — `dev` (launch extension in debug host with hot reload), `test`, `test:unit`, `test:integration`, `lint`, `lint:fix`, `typecheck`, `build`, `package` (create .vsix / .crx / .zip), `clean`, `clean:all`, `check`. VS Code `launch.json` with Extension Host debug configs. Nix flake for environment isolation.

**Still ask about**:
- Core functionality, user workflows
- Target platform(s) (Chrome, Firefox, Safari, Edge? VS Code, JetBrains? Multiple?)
- Manifest version / API version (Manifest V3 for Chrome, VS Code engine version, etc.)
- Required permissions — enumerate each permission and justify it. Store reviewers scrutinize this.
- Content script injection (if browser extension) — which pages, what access level?
- Communication patterns — content script ↔ service worker, sidebar ↔ editor, webview ↔ extension host
- Update strategy — how does the extension handle breaking changes between versions? Settings migration?
- Store listing — name, description, screenshots, categories, privacy policy (required by most stores)
- Edge cases — host platform updates that break APIs, permission revocation mid-session, storage quota exhaustion, network offline behavior, multi-window/multi-tab scenarios

**Interview style**: 8-12 questions. Focus on permissions justification, platform constraints, and user-facing behavior. Present permission defaults as minimal and let the user add more if needed.

## Spec phase overrides

- **FR/SC numbering**: required
- **Enterprise Infrastructure section**: include for: error handling, config (settings API), storage (platform storage APIs), CI/CD. Include a **Permissions** section documenting every requested permission with justification — this is unique to extensions and critical for store review. Skip: logging infra, auth (unless connecting to external services), CORS, security headers, rate limiting, graceful shutdown, health checks, observability.
- **Edge Cases & Failure Modes**: full coverage for: host platform API deprecation, permission revocation, storage quota exhaustion, network offline, multi-window/multi-tab conflicts, extension update with incompatible stored data, content script injection failures (page CSP blocks it), service worker termination mid-operation, host platform version incompatibility.
- **Testing section**: full — unit tests for core logic, integration tests against the host platform's test API (VS Code `@vscode/test-electron`, browser extension testing with Puppeteer/Playwright). Include: permission boundary tests (verify extension works when optional permissions are denied), storage migration tests, cross-platform tests if targeting multiple browsers/IDEs.
- **UI_FLOW.md**: include — extensions almost always have UI (popups, sidebars, panels, webviews, context menus, status bar items). Document every interaction surface.

## Plan phase overrides

- **Phase 1 Test Infrastructure**: full — custom structured reporter and test-logs/ directory. Include host platform test harness setup (launching a test instance of VS Code / Chrome with the extension loaded).
- **Phase 2 Foundational**: include error hierarchy, settings/config module (host platform settings API wrapper), storage module (with migration support between versions), CI/CD pipeline with package + publish steps, manifest validation, Gitleaks pre-commit hook. Skip: logging infra (use host console), graceful shutdown (use host lifecycle), health checks, observability.
- **research.md**: full depth — document every decision. Platform API choices especially need rationale since they're hard to change after users have the extension installed.
- **data-model.md**: include — document the storage schema (what's stored where, format, migration path between versions). Extensions accumulate user data that must survive updates.
- **API contract depth**: include if the extension exposes an API to other extensions (VS Code `contributes.api`, browser extension messaging). Skip for self-contained extensions.
- **Complexity Tracking**: required — extensions should be lean; every abstraction adds to bundle size and review surface
- **Phase Dependencies**: required

### Extension-specific plan sections

- **Manifest / package.json**: full specification of permissions, activation events, contribution points, content scripts, background scripts/service workers. Every permission justified.
- **Platform API usage**: list every host platform API the extension uses, the minimum platform version required for each, and fallback behavior for older versions.
- **Communication architecture**: how components talk to each other (content script ↔ background, webview ↔ extension host, cross-extension messaging). Include message schemas.
- **Storage schema & migration**: what's stored, where, format, and how to migrate between extension versions without data loss.
- **Bundle strategy**: bundler choice (esbuild, webpack, rollup), target format, size budget, tree-shaking for unused platform APIs, source maps.
- **Store publish pipeline**: automated packaging, store API upload, review submission, staged rollout strategy. Include: manifest lint, permission audit, size check, screenshot generation.
- **Permission audit**: table of every permission with: why it's needed, what happens if denied (for optional permissions), and which features depend on it. This table goes into the store listing's privacy section.

## Task phase overrides

- **Fix-validate loop**: required — per phase, runner-enforced
- **`[P]` parallel markers**: include where applicable
- **FR/Story traceability**: required on every task
- **learnings.md**: required
- **Code review**: full — auto-implement necessary fixes, write REVIEW-TODO.md, run fix-validate loop after. Extension-specific review focus: permission scope creep (are we requesting more than needed?), storage schema backwards compatibility, bundle size regression, CSP compliance.
- **Approach note**: `Approach: TDD with fix-validate loop per phase. Full CI/CD with store publish pipeline and Tier 1 security scanning. Enterprise-grade test infrastructure with host platform test harness. Permissions follow least-privilege — every permission justified and documented.`

## What the agent should still know

The full SKILL.md is loaded. If the user later wants to add a companion web service or API backend for the extension, the agent can reference the public/enterprise sections. The key principle: **extensions run with user-granted permissions in a sandboxed environment — respect both. Minimize permissions, validate all external input, handle platform API changes gracefully, and ensure stored data survives updates. The store review is the final gate — design for it from the start, not as an afterthought.**
