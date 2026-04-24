# MCP-driven E2E — Android (`mcp-android`)

When to read: you are an E2E sub-agent on a task with `mcp-android`
capability. Read this alongside `mcp-e2e-core.md`.

The Android MCP server drives a running emulator. It exposes the
`State-Tool` primitive (UI element tree + optional vision) plus
interaction tools (click, swipe, type, key press).

## Cost rule (HARD — enforced in every executor prompt)

**The cheap structured tool is the default; vision is only for bug
evidence.** This applies from spawn 1, call 1 — there is no grace
period.

| Task | Tool |
|---|---|
| Navigate / click / inspect state | `State-Tool` **without** `use_vision` (UI element tree) |
| Attach evidence to a bug finding | `State-Tool` with `{"use_vision": true}` |
| Capture a screenshot for a bug finding | `Screenshot` / `Snapshot` |

Every `use_vision:true` call must produce a finding whose
`screenshot_path` points at the file it captured. A vision capture
that doesn't end up in `findings.json` is wasted budget — the runner
counts this in post-hoc cost analysis via
`PlatformDriver.cheap_vs_expensive_calls`.

Why ~10× ratio: a no-vision tree dump is ~200–2 000 tokens. A
screenshot adds a full image block (~1 500–3 000 tokens in Claude's
vision budget, plus the rendered text Claude generates about it). Over
a 15-screen crawl the difference is 30–100k tokens.

### Other hard caps

1. **Maximum 20 screenshots per session** — agents count and stop.
   The cost rule above is primary; this is belt-and-suspenders.
2. **Save screenshots to disk, don't re-read** — reference by path in
   findings.
3. **`MCP_ANDROID_DEFAULT_NO_VISION=1`** is set by the runner so
   `State-Tool` defaults to `use_vision:false` unless the call
   explicitly opts in.

## Android MCP tools

| Tool | Purpose |
|---|---|
| `State-Tool` | Read accessibility/view tree (find selectors). Pass `use_vision:true` only for bug evidence. |
| `Screenshot` / `Snapshot` | Capture screen as PNG |
| `DumpHierarchy` | Raw view-tree dump (alias of `State-Tool` without vision in most fork) |
| `Click` / `ClickBySelector` | Tap UI elements |
| `LongClick` | Long press |
| `Swipe` | Scroll, swipe gestures |
| `Type` / `SetText` | Enter text |
| `Press` | Hardware buttons (BACK, HOME) |
| `WaitForElement` | Poll for element appearance |
| `GetScreenInfo` | Screen dimensions |

## Regression spec writing

Use the element text / semanticsLabel you saw in `State-Tool` output
— those map to Patrol's `$('text')` / `$(#key)` selectors. Assert final
state via HTTP calls to the admin API, not by re-driving into admin
screens.

First line of the spec file must be `// regression for <TASK_ID>` (or
`# regression for <TASK_ID>` in Kotlin). The runner requires the
signature to treat the file as a regression spec.

Typical spec locations:

- Flutter: `<flutter-app>/integration_test/<TASK_ID>_test.dart`
- Pure Gradle Android: `app/src/androidTest/java/<TASK_ID>Test.kt`

Run commands: `patrol test --target <file>` if `patrol_cli` is on
PATH, else `flutter test <file>` inside the app dir. Gradle fallback:
`./gradlew connectedDebugAndroidTest`.

Flutter app detection: any repo-root directory containing
`pubspec.yaml`. Set `ANDROID_BUILD_ROOT` when multiple Flutter apps
exist in the repo.

## Common infrastructure issues

| Symptom | Likely cause | Fix |
|---|---|---|
| `adb reverse` not applied | `setup.sh` didn't wire it after emulator boot | See `reference/e2e-runtime.md § "Android emulator: host-port bridging via adb reverse"` for the canonical block (gated on `E2E_WANT_EMULATOR=1`, reapplied every run because the mappings don't persist across emulator restarts) |
| SuperTokens CDI version mismatch | `supertokens-node` SDK requires newer CDI than the running core | Upgrade SuperTokens core OR downgrade the SDK to a CDI-matching version |
| `formField` mismatch on signup | API's `formFields` list missing a field the app sends | Sync the two sides; filing an infra bug is correct |
| Emulator won't boot | AVD not created or system image missing | `nix develop` provides the SDK; pick `platformVersions` matching the app's `compileSdk` |

## Platform boot

- Emulator via `start-emulator` or `emulator @avd <name>` (the runner
  picks based on platform driver config).
- App build + install: `gradlew assembleDebug` + `adb install` (pure
  Gradle) or `flutter build apk --debug && flutter install` (Flutter).
- MCP server: `nix-mcp-debugkit#mcp-android`.

Emulator boot plus APK install is the long tail of wall-clock; the
agent-token cost dominates the total E2E cost by a wide margin.
