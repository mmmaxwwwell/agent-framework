# MCP-driven E2E — iOS (`mcp-ios`)

When to read: you are an E2E sub-agent on a task with `mcp-ios`
capability. Read this alongside `mcp-e2e-core.md`.

iOS support is **deferred**. `IOSDriver.regression_spec_candidates` is
not yet implemented, so every iOS task currently falls through to the
MCP explore loop (no regression fast-path).

## Platform boot

- `xcrun simctl boot` to start a simulator.
- Build and install with `xcodebuild build` + `simctl install`.
- MCP server: `nix-mcp-debugkit#mcp-ios`.

## Cost rule

Mirror the Android cost rule: the cheap structured tool (view tree
dump) is the default; vision is only for bug evidence. The concrete
tool names depend on the debug-kit fork version — check the tool list
at session start and prefer any `_without_vision` variants.

## Status

Until the regression fast-path lands, every iOS task cycles through
the full explore-research-fix-verify loop on every run. Keep tasks
narrow (one screen/flow) to limit the per-run cost.
