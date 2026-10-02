# Preset: Published Library / Package

**Goal**: Enterprise-grade engineering for a library published to a package registry (npm, PyPI, crates.io, etc.). Same rigor as production systems — comprehensive tests, full CI/CD with publish pipeline, thorough documentation — but scoped to the concerns of a library: API surface design, backwards compatibility, semver, bundling, documentation generation, and multi-consumer support. No server, no deployment, no auth.

## Interview phase overrides

**Skip entirely** — do not ask about:
- Authentication & authorization (not applicable — libraries don't auth)
- CORS policy (not applicable)
- Rate limiting & backpressure (not applicable)
- Security headers (not applicable)
- Graceful shutdown (not applicable)
- Health checks (not applicable)
- Observability infrastructure (not applicable — consumers bring their own)
- Process architecture & statefulness (not applicable)
- Deployment target (not applicable — published to a registry, not deployed)
- API versioning via URL paths (not applicable — use semver instead)

**Default without asking** (use these unless the user volunteers a preference):
- Logging: no built-in logging. If the library needs to emit diagnostics, use a pluggable logger interface (e.g., accept a `logger` option) so consumers choose their own. Never import a logging library as a dependency.
- Error handling: full error hierarchy with descriptive messages. Every thrown error should have a unique code, a human-readable message, and enough context to debug without reading source. Errors are part of the public API — document them.
- Configuration: options objects with defaults, validated at construction time. No env vars, no config files — consumers pass config in code. Use TypeScript types / Python dataclasses / Rust builder patterns for type-safe config.
- Migration: not applicable (no database). If the library has persistent state (cache files, config), provide a migration function between major versions.
- CI/CD: full pipeline — lint, build, test (unit + integration), security scan, documentation generation, publish to registry. Automated releases via semantic-release or similar. Changesets or conventional commits for changelog.
- Branching: feature branches with PRs. Main branch is always publishable. Release branches for major version maintenance if needed.
- Semver: strict. Breaking changes = major. New features = minor. Fixes = patch. Document the policy. Include a BREAKING CHANGES section in changelog for major versions.
- DX tooling: full — `dev` (watch mode for tests), `test`, `test:unit`, `test:integration`, `lint`, `lint:fix`, `typecheck`, `build`, `clean`, `clean:all`, `check`, `docs` (generate API docs), `docs:serve` (preview docs locally). `.env.example` if env vars are used for testing. VS Code `launch.json` with debugger configs. Nix flake for environment isolation.

**Still ask about**:
- Core functionality, API surface design, use cases
- Non-goals — "anything this library should deliberately NOT do?" Critical for libraries where scope creep bloats the public API surface.
- Target consumers (who will use this? what environments? Node, browser, both? Python 3.9+? Rust stable?)
- Target registries (npm, PyPI, crates.io, GitHub Packages)
- Bundling strategy (ESM, CJS, UMD, dual-publish? tree-shakeable?)
- Documentation approach (TypeDoc, Sphinx, rustdoc, JSDoc, README-only?)
- Minimum supported versions (Node 18+? Python 3.10+? Rust MSRV?)
- Peer dependencies vs bundled dependencies
- Edge cases for API misuse — what happens when consumers pass wrong types, call methods in wrong order, exceed limits?
- Platform compatibility (Node-only? Browser-compatible? Isomorphic?)

**Interview style**: Be exhaustive — cover every applicable topic until the spec has no gaps. Focus on API design, consumer experience, and compatibility guarantees. Propose sensible defaults and confirm.

## Spec phase overrides

- **FR/SC numbering**: required
- **Examples on FRs**: mandatory on any FR flagged during analyze; encouraged on public API methods (examples serve double duty as documentation)
- **Non-Goals section**: required — critical for libraries to document what's out of scope of the public API
- **Operational workflows**: skip (not applicable to libraries)
- **Enterprise Infrastructure section**: include for: error handling (errors are public API), config (options validation). Skip: logging infra, auth, CORS, security headers, rate limiting, graceful shutdown, health checks, observability.
- **Edge Cases & Failure Modes**: full coverage for: invalid input to every public API method, type misuse, concurrent usage, version mismatches, missing peer dependencies, environment-specific failures (Node vs browser), resource cleanup (memory leaks, event listener cleanup, connection pooling).
- **Testing section**: full — unit tests for every public API method, integration tests for complex workflows, compatibility tests across target environments/versions. Include: error case testing (every documented error code has a test), edge case testing for API misuse, benchmark tests for performance-sensitive APIs.
- **UI_FLOW.md**: skip unless the library has a UI component (e.g., React component library).
- **API documentation**: required — every public export must have documentation with examples, parameter descriptions, return types, thrown errors, and `@since` version tags.

## Plan phase overrides

- **Phase 1 Test Infrastructure**: full — custom structured reporter and test-logs/ directory. Include cross-environment test matrix if targeting multiple runtimes (Node + browser, multiple Python versions).
- **Phase 2 Foundational**: include error hierarchy (public API errors), config validation module, build pipeline (bundler config for target formats), CI/CD pipeline with publish step, documentation generation setup, Gitleaks pre-commit hook. Skip: logging infra, graceful shutdown, health checks, observability.
- **research.md**: full depth — document every decision. API design decisions especially need clear rationale since they become permanent commitments after publish.
- **data-model.md**: include if the library has internal data structures that consumers interact with (e.g., a state machine, a cache, a tree). Skip for pure-function libraries.
- **API contract depth**: critical — this IS the product. Full request/response (input/output) schemas for every public method, all parameter types, return types, error cases, side effects.
- **Complexity Tracking**: required — libraries should be especially simple since consumers inherit your complexity
- **Phase Dependencies**: required
- **Interface contracts**: include if the library has internal modules that share state. Skip for pure-function libraries.
- **Runtime state machines**: include if the library manages stateful objects (connection pools, state machines, caches). Skip for stateless utilities.
- **Critical path (user perspective)**: required — identify the consumer's first-use flow (install, import, call, get result)
- **Test plan matrix**: required — map every SC to test tier and target environment matrix

### Library-specific plan sections

- **Public API surface**: exhaustive list of every export — functions, classes, types, constants. Each with: purpose, parameters, return type, errors, example. This is the contract consumers depend on.
- **Bundling strategy**: ESM/CJS/UMD targets, tree-shaking considerations, source maps, minification, package.json `exports` field (or equivalent).
- **Backwards compatibility policy**: what constitutes a breaking change, deprecation workflow (warn for N minor versions before removing), migration guides for major versions.
- **Documentation generation**: tool choice, hosting (GitHub Pages, Read the Docs), auto-deploy from CI, versioned docs for major versions.
- **Release pipeline**: automated version bumping, changelog generation, registry publish, GitHub release with notes, tag creation.
- **Dependency policy**: minimize dependencies (each dep is a liability for consumers). Justify every runtime dependency. Prefer peer dependencies for large shared deps. Dev dependencies are fine.

## Task phase overrides

- **Fix-validate loop**: required — per phase, runner-enforced
- **`[P]` parallel markers**: include where applicable
- **Done criteria**: required on every task
- **Interface contract tags**: include where applicable
- **Critical path checkpoints**: required
- **FR/Story traceability**: required on every task
- **Non-goals awareness**: reference in approach note
- **Spec amendment process**: supported
- **learnings.md**: required
- **Code review**: full — auto-implement necessary fixes, write REVIEW-TODO.md, run fix-validate loop after. API surface review is especially important — look for: inconsistent naming, missing error cases, undocumented behavior, accidental public exports.
- **Approach note**: `Approach: TDD with fix-validate loop per phase. Full CI/CD with publish pipeline and Tier 1 security scanning. Enterprise-grade test infrastructure across target environments. Public API is the product — every export documented, every error tested, strict semver. See Non-Goals for intentional API scope boundaries.`

## What the agent should still know

The full SKILL.md is loaded. If the user later wants to add a CLI wrapper, a server, or a web UI around the library, the agent can reference the local/public/enterprise sections. The key principle: **the public API is a contract — once published, it's permanent. Every decision about the API surface deserves the same rigor as a production deployment decision, because consumers will depend on it for years.**
