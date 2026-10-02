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

- Flutter (single-app repo): `<flutter-app>/integration_test/<TASK_ID>_test.dart`
- Flutter (multi-app repo): write under the app named in the task's
  `[android-app: <dir>]` annotation, e.g. `admin/integration_test/<TASK_ID>_test.dart`.
  The runner uses that same value to pick the build/install target, so
  this is unambiguous. If the annotation is missing, file a finding
  asking the planner to add it — do NOT guess.
- Pure Gradle Android: `app/src/androidTest/java/<TASK_ID>Test.kt`

**`<TASK_ID>` = the task you are currently working on.** Not a task
mentioned in the description. Not a task named in the "Done when"
clause. The runner's gate looks up `<your current TASK_ID>_test.dart`
(or `T<your current TASK_ID>Test.kt`) and fails the task if that exact
file is missing, regardless of what other files you produced.

If the task description names a *different* regression path (e.g. a
backfill task whose deliverable is authoring regressions for *other*
tasks), you must produce **both**: the file(s) the task description
names, AND a file at the runner-expected path for the current
`TASK_ID`. The latter can be a thin delegator (import the other spec's
test functions and re-run them, or duplicate the assertions). Its
purpose is to satisfy the mechanical `missing_regression_spec` gate so
the task can close. First line signature must reference the current
`TASK_ID`, not the other task's id.

Run commands: `patrol test --target <file>` if `patrol_cli` is on
PATH, else `flutter test <file>` inside the app dir. Gradle fallback:
`./gradlew connectedDebugAndroidTest`.

Flutter app detection: any repo-root directory containing
`pubspec.yaml`. In multi-app monorepos, the runner picks which app a
task targets from the task's `[android-app: <dir>]` annotation; see
the next section.

## Multi-app monorepos

When the repo has more than one Flutter app at the root (e.g. `admin/`
+ `customer/`), every `[needs: mcp-android]` task MUST carry an
`[android-app: <dir>]` annotation in its task line:

```
- [ ] T099 E2E: full fulfillment + shipping [needs: mcp-android, e2e-loop] [android-app: admin]
- [ ] T097 E2E: customer checkout [needs: mcp-android, e2e-loop] [android-app: customer]
```

The runner uses this to pick:

1. **Which APK to build and install** (build-detect / `_build_install_android`)
2. **Which package name to health-check** (`_detect_android_package`)
3. **Where to write and look for the regression spec**
   (`<dir>/integration_test/<TASK_ID>_test.dart`)

All three reads share a per-task thread-local override; they will be
consistent within one task and can differ between concurrent tasks.

**Cross-app tasks** (a single E2E that exercises both admin and
customer): annotate with the app whose UI the test *drives*. Verify the
other app's state via API calls, not by re-driving its UI from the
same task. The runner only installs one APK per task; trying to drive
both UIs from one E2E means the second one isn't installed.

**Do NOT set a project-wide `ANDROID_BUILD_ROOT` default in your
devshell** (e.g. `flake.nix`, `.envrc`, `direnv`). It looks like a
convenience but silently breaks every task targeting the *other* app:
the runner picks that env value for the build, install, package
health-check, and regression-spec lookup, so a task annotated for the
non-default app may run against the wrong APK. Leave the env unset and
let `[android-app: <dir>]` annotations drive everything per-task.

If a task is missing the annotation in a multi-app repo, the runner
falls back to env, then to scanning all apps; the regression-spec gate
is permissive (it will accept a spec under any Flutter app) but the
build/install steps still need a single pick. Annotate explicitly.

## Common infrastructure issues

| Symptom | Likely cause | Fix |
|---|---|---|
| `adb reverse` not applied | `setup.sh` didn't wire it after emulator boot | See `reference/e2e-runtime.md § "Android emulator: host-port bridging via adb reverse"` for the canonical block (gated on `E2E_WANT_EMULATOR=1`, reapplied every run because the mappings don't persist across emulator restarts) |
| SuperTokens CDI version mismatch | `supertokens-node` SDK requires newer CDI than the running core | Upgrade SuperTokens core OR downgrade the SDK to a CDI-matching version |
| `formField` mismatch on signup | API's `formFields` list missing a field the app sends | Sync the two sides; filing an infra bug is correct |
| Emulator won't boot | AVD not created or system image missing | `nix develop` provides the SDK; pick `platformVersions` matching the app's `compileSdk` |
| Source fix landed but app still behaves like pre-fix | Gradle incremental cache reused pre-fix APK; build reports exit 0 + "Built app-debug.apk" but binary is stale | `cd <app> && flutter clean && flutter build apk --debug && adb install -r build/app/outputs/flutter-apk/app-debug.apk`. Verify with `unzip -p <apk> assets/flutter_assets/kernel_blob.bin \| strings \| grep <post-fix-symbol>`. Full pattern + verify.sh sample: `reference/e2e-failure-patterns.md § stale-android-apk-after-source-fix`. |

## Platform boot

- Emulator via `start-emulator` or `emulator @avd <name>` (the runner
  picks based on platform driver config).
- App build + install: `gradlew assembleDebug` + `adb install -r <apk>`
  (pure Gradle) or `flutter build apk --debug && adb install -r
  build/app/outputs/flutter-apk/app-debug.apk` (Flutter).
- **`flutter clean` is mandatory after any source change.** Gradle's
  incremental cache will silently reuse a pre-fix APK and still print
  "exit 0 / Built app-debug.apk" — the binary is stale, the build log
  lies. Always run `flutter clean` (or `gradlew clean`) before
  rebuilding when you have edited source files. Project setup scripts
  (`scripts/e2e-install-apks.sh`, `test/e2e/setup.sh`) detect staleness
  and run it automatically; if you build outside those scripts you own
  the clean step. See `reference/e2e-failure-patterns.md
  § stale-android-apk-after-source-fix` for the full diagnostic recipe.
- **Post-install verification:** confirm the device actually swapped
  binaries before declaring a fix verified — `adb shell dumpsys package
  <pkg> | grep lastUpdateTime` must postdate the build, and for
  code-fix bugs, content-grep the installed APK: `unzip -p <apk>
  assets/flutter_assets/kernel_blob.bin | strings | grep <post-fix-symbol>`.
  Both checks belong in the bug's `verify.sh`.
- MCP server: `nix-mcp-debugkit#mcp-android`.

Emulator boot plus APK install is the long tail of wall-clock; the
agent-token cost dominates the total E2E cost by a wide margin.
`flutter clean` adds ~30–60s per stale-cache rebuild — cheap insurance
against the multi-iteration loop the cache-stale trap creates.
