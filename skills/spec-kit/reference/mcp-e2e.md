# MCP-driven E2E — split by platform

This file previously bundled web, Android, and iOS E2E guidance into
one 600-line document. It has been split for cost reasons — E2E
sub-agents should read only the platform-neutral core plus the one
platform file that matches their `mcp_caps`, not all three.

## Read this instead

| You are working on | Read |
|---|---|
| Any E2E task (platform-neutral: loop, findings, regression, env) | `mcp-e2e-core.md` |
| Web (`mcp-browser`) | `mcp-e2e-core.md` + `mcp-e2e-web.md` |
| Android (`mcp-android`) | `mcp-e2e-core.md` + `mcp-e2e-android.md` |
| iOS (`mcp-ios`) | `mcp-e2e-core.md` + `mcp-e2e-ios.md` |

The runner injects the right pair automatically for E2E sub-agents;
you should not need to pick manually.

## Why the split

One agent session running a web E2E task was reading all Android
`State-Tool` / emulator / Patrol content it would never use — 9.6k
tokens × 300 turns × $0.30/M cache-read = $0.86 per agent in pure
waste. Multiply by every E2E role in every iteration and the cost
compounds.

See `cost-guardrails.md` § "Reference injection" for the broader
pattern this is an instance of.
