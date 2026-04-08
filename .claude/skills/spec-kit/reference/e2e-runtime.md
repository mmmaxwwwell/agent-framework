# E2E Testing with Real Runtimes

When a project targets a platform with its own runtime — Android, iOS, web browsers, desktop — unit tests and in-process integration tests are **necessary but insufficient**. They run in the host environment (JVM, Node, Go), not the target runtime. Code that passes all host-side tests can crash immediately on the real platform because:

- Native libraries aren't linked (gomobile AAR, Rust FFI .so, WASM)
- Platform APIs behave differently than mocks (Android Keystore, Web Crypto, iOS Keychain)
- UI rendering breaks (Compose layout, CSS in real browsers, SwiftUI)
- Cross-process communication fails (deep links, intents, IPC, service workers)
- Platform security policies block operations (permissions, sandboxing, CORS)

**Every project that targets a platform runtime MUST include E2E tests that exercise the real app on the real (or emulated) runtime.** This is the only way to structurally prevent the "tests pass, app crashes" failure mode.

## Runtime selection table

For each target platform, use the real runtime — never a simulation or mock runtime:

| Target platform | Test runtime | Boot mechanism | Interaction mechanism | CI requirements |
|----------------|-------------|----------------|----------------------|-----------------|
| **Android** | Android Emulator (QEMU) | `emulator @avd -no-window -gpu swiftshader_indirect` | UI Automator / Espresso via `adb` + instrumentation | KVM access (`/dev/kvm`), x86_64 system image |
| **iOS** | iOS Simulator | `xcrun simctl boot <device>` | XCUITest via `xcodebuild test` | macOS runner, Xcode installed |
| **Web / PWA** | Real headless browser | Playwright (`chromium.launch()`) or Selenium + ChromeDriver | Playwright API / WebDriver protocol | Xvfb or headless mode, browser binary |
| **Desktop (Electron)** | Real Electron app | `electron .` with `--no-sandbox` | Playwright Electron / Spectron | Xvfb, display server |
| **Desktop (Tauri)** | Real Tauri app | `cargo tauri dev` or built binary | WebDriver (Tauri exposes WebDriver) | Display server, WebKit deps |
| **NixOS service** | NixOS VM (QEMU) | `nix flake check` runs VM test driver | Python test script inside VM | KVM access, Nix |
| **CLI tool** | Real process | Direct invocation | stdin/stdout/exit code | None |

### What "real" means — no fake runtimes

**Android**: Use the Android Emulator with a real system image, NOT Robolectric. Robolectric simulates Android APIs on the JVM — it doesn't run your app in an Android process, doesn't load native `.so` libraries, doesn't exercise the real Android Keystore, and doesn't render Compose UI. `./gradlew testDebugUnitTest` runs Robolectric/JVM tests. `./gradlew connectedDebugAndroidTest` runs on a real emulator. **Both must pass, but only the emulator tests count as E2E.**

**Web/PWA**: Use a real headless browser (Chromium, Firefox, WebKit via Playwright), NOT jsdom/happy-dom. jsdom doesn't implement: Web Crypto API, Service Workers, IndexedDB transactions, CSS rendering, WebSocket connections, `fetch` with real networking, `<canvas>`, WebGL, Web Workers, or any API that requires a real browser engine. If your tests pass on jsdom but the app breaks in Chrome, jsdom is hiding bugs, not finding them.

**iOS**: Use the iOS Simulator, NOT a mock framework. The simulator runs real iOS frameworks (UIKit, SwiftUI, CryptoKit) in an x86_64/arm64 process. It's the only way to test Keychain access, biometric prompts, push notifications, and app lifecycle.

**Desktop**: Launch the real app binary with a real window (or headless display server). Don't test Electron apps with just Node.js unit tests — they miss IPC, preload script isolation, and native module loading.

## Architecture: side-by-side, NOT nested

When E2E tests require multiple runtimes (e.g., an Android app talking to a host daemon over a network), run them **side-by-side on the same host**, NOT nested (e.g., NOT an emulator inside a VM).

**Why**: CI runners (GitHub Actions `ubuntu-latest`) provide KVM but NOT nested KVM. Running an Android emulator inside a NixOS VM requires nested virtualization, which is unavailable. Running both directly on the host uses KVM efficiently.

### Side-by-side layout

```
Host machine (KVM available)
├── Service A (native process — e.g., daemon, server, API)
├── Service B (native process — e.g., headscale, database, mock service)
├── Runtime C (QEMU+KVM — e.g., Android emulator, NixOS VM)
├── Runtime D (headless browser — e.g., Playwright Chromium)
└── test-orchestrator.sh (coordinates everything)
```

The test orchestrator is a shell script (or equivalent) that:
1. Starts all services and runtimes
2. Waits for each to be ready (readiness checks — see below)
3. Runs the test sequence
4. Captures output and artifacts on failure
5. Cleans up everything on exit (trap EXIT)

### When nested IS acceptable

Nested virtualization is acceptable when:
- The NixOS VM test framework is the test driver (e.g., `nix flake check` runs the VM test) AND the test doesn't need an Android/iOS emulator inside it
- The inner runtime is lightweight (a container, not a full VM)
- The CI environment supports nested KVM (self-hosted runners with nested virt enabled)

## Readiness checks

Every runtime and service needs a readiness check before the test proceeds. Without readiness checks, the test races against boot time and fails intermittently.

| Runtime/Service | Readiness check | Timeout |
|----------------|----------------|---------|
| Android Emulator | `adb shell getprop sys.boot_completed` returns `1` | 120s (KVM), 600s (software) |
| Android package manager | `adb shell pm list packages \| wc -l` > 50 | 300s after boot |
| iOS Simulator | `xcrun simctl list devices \| grep Booted` | 60s |
| Headless browser | Playwright `browser.newPage()` succeeds | 30s |
| NixOS VM | VM test driver handles boot internally | Part of test framework |
| Headscale | `curl -sf http://localhost:PORT/health` | 30s |
| Database | Connection succeeds + query returns | 30s |
| HTTP server | `curl -sf http://localhost:PORT/health` returns 200 | 30s |
| gRPC server | `grpcurl -plaintext localhost:PORT grpc.health.v1.Health/Check` | 30s |
| Tailscale | `tailscale status --json` shows connected | 30s |

### Readiness script pattern

```bash
wait_for() {
  local name="$1" cmd="$2" timeout="$3"
  local elapsed=0
  while [ $elapsed -lt "$timeout" ]; do
    if eval "$cmd" >/dev/null 2>&1; then
      echo "[ready] $name (${elapsed}s)"
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  echo "[timeout] $name did not become ready in ${timeout}s" >&2
  return 1
}

wait_for "emulator" "adb shell getprop sys.boot_completed | grep -q 1" 120
wait_for "headscale" "curl -sf http://127.0.0.1:8080/health" 30
wait_for "daemon" "test -S /tmp/agent.sock" 10
```

## Test bypass mechanisms for hardware-dependent features

Real devices have capabilities that emulators/simulators/headless browsers don't: cameras, NFC, Bluetooth, GPS, biometric sensors, hardware security modules. E2E tests MUST bypass these using test-mode hooks in the app — NOT by mocking at the API level (which defeats the purpose of E2E testing).

| Feature | Bypass mechanism | Implementation |
|---------|-----------------|----------------|
| **QR code scanning (camera)** | Deep link with payload | `nix-key://pair?payload=<base64>` intent/URL. Only enabled in debug builds. |
| **Biometric authentication** | Mock biometric API or auto-approve flag | Android: `BiometricManager` mock in test DI module. iOS: enrolled simulated fingerprint in Simulator settings. |
| **GPS/location** | Emulator location injection | `adb emu geo fix <lon> <lat>` for Android. `xcrun simctl location set` for iOS. |
| **NFC/Bluetooth** | Skip with test flag, test protocol layer separately | Feature flag `TEST_SKIP_NFC=1`. Protocol-level tests via loopback socket. |
| **Hardware keystore** | Software keystore fallback in test builds | Android: `setIsStrongBoxBacked(false)` + software-backed keystore. Test the keystore interface, not the hardware. |
| **Push notifications** | Direct API call instead of push | Call the notification handler directly with a test payload. |
| **File picker / camera roll** | `adb push` + intent with file URI | Push test file to emulator, send VIEW intent with the file URI. |
| **OAuth / external auth** | Pre-authorized test token | Inject auth token via test intent/deep link. Skip the OAuth flow. |
| **Service Worker (web)** | Serve from localhost with real HTTPS | Use `mkcert` for localhost TLS cert. Service workers require secure context. |
| **Web Crypto API** | Runs natively in headless browsers | No bypass needed — Playwright/headless Chrome implements Web Crypto. |
| **WebAuthn / passkeys** | Virtual authenticator | Playwright: `cdp.send('WebAuthn.enable')` + `addVirtualAuthenticator`. Chrome DevTools Protocol. |

**Critical rule**: Test bypass mechanisms MUST be gated behind debug/test build flags. They must NEVER be available in release builds. Verify this with a release build test that confirms the bypass is absent.

## UI automation patterns

### Android: UI Automator + Instrumentation

Create a reusable test helper class with methods for common actions:

```kotlin
// android/app/src/androidTest/java/.../e2e/AppE2EHelper.kt
class AppE2EHelper {
    fun waitForApp(timeout: Long = 10_000) { /* UiDevice.wait for activity */ }
    fun navigateTo(screen: String) { /* click nav elements */ }
    fun tapButton(text: String) { /* UiDevice.findObject(By.text(text)).click() */ }
    fun enterText(hint: String, value: String) { /* find field, clear, type */ }
    fun waitForElement(selector: BySelector, timeout: Long) { /* UiDevice.wait */ }
    fun approveDialog() { /* find and tap positive button */ }
    fun denyDialog() { /* find and tap negative button */ }
}
```

Invoke from the test orchestrator via `adb am instrument`:
```bash
adb shell am instrument -w \
  -e class "com.example.e2e.AppE2EHelper" \
  -e method "tapButton" \
  -e text "Connect" \
  "com.example.test/androidx.test.runner.AndroidJUnitRunner"
```

### Web: Playwright (language-agnostic)

Playwright supports Chromium, Firefox, and WebKit. Use it for ANY web/PWA project:

```typescript
// Node.js example — adapt to Python/Java/C# Playwright bindings
import { chromium } from 'playwright';

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
await page.goto('http://localhost:3000');
await page.click('button:has-text("Sign In")');
await page.fill('input[name="email"]', 'test@example.com');
await page.click('button:has-text("Submit")');
await expect(page.locator('.dashboard')).toBeVisible();
```

**PWA-specific considerations**:
- Test service worker registration: `page.evaluate(() => navigator.serviceWorker.ready)`
- Test offline mode: `page.context().setOffline(true)` then verify cached content loads
- Test install prompt: use `beforeinstallprompt` event interception
- Test push notifications: use Playwright's `browserContext.grantPermissions(['notifications'])`

**Important**: Playwright downloads its own browser binaries. In Nix environments, either:
1. Set `PLAYWRIGHT_BROWSERS_PATH` to a writable location and let Playwright download at test time
2. Use `playwright install chromium` in the test setup script
3. Use nixpkgs' `playwright-driver` if available for your nixpkgs version

### iOS: XCUITest

```swift
// MyAppUITests.swift
func testSignInFlow() throws {
    let app = XCUIApplication()
    app.launch()
    
    app.buttons["Sign In"].tap()
    app.textFields["Email"].tap()
    app.typeText("test@example.com")
    app.buttons["Submit"].tap()
    
    XCTAssertTrue(app.staticTexts["Dashboard"].waitForExistence(timeout: 10))
}
```

### Desktop: Playwright Electron / Tauri WebDriver

```typescript
// Electron
const app = await electron.launch({ args: ['path/to/app'] });
const page = await app.firstWindow();
await page.click('#start-button');

// Tauri — uses WebDriver
const driver = await new Builder().forBrowser('webdriver').build();
await driver.get('tauri://localhost');
```

## Multi-runtime E2E orchestration

For projects where the E2E test involves multiple runtimes communicating (e.g., phone app + host daemon + mesh network), the test orchestrator coordinates the full lifecycle:

```bash
#!/usr/bin/env bash
# test/e2e/run-e2e.sh — multi-runtime E2E orchestrator
set -euo pipefail
trap cleanup EXIT

# Phase 1: Start infrastructure
start_mesh_network    # headscale, tailscale nodes
start_backend         # daemon, server, database

# Phase 2: Start runtimes  
boot_emulator         # Android emulator with APK installed
# OR: launch_browser  # Playwright headless Chromium
# OR: boot_simulator  # iOS Simulator with app installed
# OR: launch_desktop  # Electron/Tauri app

# Phase 3: Readiness checks (all must pass)
wait_for "mesh" "..." 30
wait_for "backend" "..." 10  
wait_for "emulator" "..." 120

# Phase 4: Test sequence
test_pairing          # connect runtimes to each other
test_primary_flow     # exercise the main user flow
test_error_handling   # exercise failure paths
test_denial           # exercise rejection/cancellation paths

# Phase 5: Results
collect_logs          # grab logcat, server logs, browser console
report_results        # structured output to test-logs/e2e/
```

### Log collection on failure

When E2E tests fail, collect ALL logs from ALL runtimes:

| Runtime | Log source | Collection command |
|---------|-----------|-------------------|
| Android | logcat | `adb logcat -d > test-logs/e2e/logcat.txt` |
| Browser | console log | Playwright: `page.on('console', ...)` captured during test |
| iOS | system log | `xcrun simctl spawn booted log show --last 5m` |
| NixOS VM | journal | VM test driver captures stdout/stderr automatically |
| Host process | stderr/stdout | Redirect to `test-logs/e2e/<service>.log` at start |
| Network | packet capture | `tcpdump -w test-logs/e2e/capture.pcap` (optional, for protocol debugging) |

Upload `test-logs/e2e/` as a CI artifact on failure.

## Single-runtime constraint on parallelism

When a project uses a single emulator, simulator, or browser instance, **all scenario-level tasks that interact with that runtime are sequential** — even if they touch different files and have no code dependencies. The `[P]` marker must NOT be applied to these tasks.

Tasks that CAN be parallelized in a single-runtime project:
- Writing prompt templates, config files, or documentation (no runtime interaction)
- Writing library code that doesn't need the runtime to validate
- Tasks targeting genuinely different runtimes (e.g., Android emulator + headless browser)

Tasks that CANNOT be parallelized:
- Any scenario that boots, interacts with, or reads state from the shared runtime
- Infrastructure setup tasks that write to the same file (e.g., extracting functions into a shared `infrastructure.sh`)
- Any task that depends on app state created by a previous scenario on the same runtime

The Dependencies section in tasks.md must reflect this: if all user stories share one emulator, they run sequentially in priority order, not in parallel.

## Flakiness handling

Real-runtime E2E tests are inherently flakier than unit tests due to:
- Boot time variance (emulator, browser startup)
- UI animation timing
- Network timing (real sockets, DNS, TLS handshake)
- Resource contention on CI runners

### Mitigation strategies

1. **Retry wrapper** — retry the entire test 2-3 times with cooldown between attempts:
   ```bash
   for attempt in 1 2 3; do
     if run_e2e_test; then exit 0; fi
     echo "Attempt $attempt failed, retrying in 30s..."
     sleep 30
   done
   exit 1
   ```

2. **Generous timeouts** — use 2-3x the expected time for waits:
   ```kotlin
   // Don't: waitForElement(timeout = 1000)
   // Do:    waitForElement(timeout = 10000)
   ```

3. **Explicit waits, never `sleep`** — wait for a specific condition, not a fixed duration:
   ```bash
   # Don't: sleep 5; adb shell pm install app.apk
   # Do:    wait_for "pm" "adb shell pm list packages | wc -l | [ $(cat) -gt 50 ]" 300
   #        adb shell pm install app.apk
   ```

4. **Idempotent test setup** — if a retry reuses the same environment, ensure setup is idempotent (app already installed, service already running = skip, don't fail).

5. **Deterministic test data** — use fixed seeds, pre-generated fixtures, and deterministic timestamps. Never depend on wall-clock time for assertions.

## CI infrastructure per runtime

| Runtime | CI runner | Required features | Setup |
|---------|----------|-------------------|-------|
| Android Emulator | `ubuntu-latest` | KVM (`/dev/kvm`), 8GB+ RAM | `androidenv.emulateApp` in Nix, or `reactivecircus/android-emulator-runner` action |
| iOS Simulator | `macos-latest` | Xcode, 14GB+ RAM | Pre-installed on GitHub macOS runners |
| Headless browser | `ubuntu-latest` | None special | Playwright installs browsers, or use Nix |
| NixOS VM | `ubuntu-latest` | KVM, Nix | `cachix/install-nix-action`, KVM enabled |
| Desktop (Electron) | `ubuntu-latest` | Xvfb | `xvfb-run` wrapper |
| Desktop (Tauri) | `ubuntu-latest` | WebKit deps, Xvfb | `libwebkit2gtk-4.0-dev`, `xvfb-run` |

### KVM access on GitHub Actions

```yaml
- name: Enable KVM
  run: |
    echo 'KERNEL=="kvm", GROUP="kvm", MODE="0666", OPTIONS+="static_node=kvm"' | sudo tee /etc/udev/rules.d/99-kvm4all.rules
    sudo udevadm control --reload-rules
    sudo udevadm trigger --name-match=kvm
```

### KVM access in sandboxed agents (bubblewrap)

The parallel runner executes agents inside a bubblewrap (`bwrap`) sandbox with a synthetic `/dev` (via `--dev /dev`). This synthetic devfs does **not** include host device nodes like `/dev/kvm`. Without `/dev/kvm`, the Android emulator falls back to pure software emulation (`-accel off`), which is ~10x slower — boot takes 5-10 minutes instead of ~30 seconds.

The runner's sandbox automatically bind-mounts `/dev/kvm` into the sandbox when it exists and is writable on the host. If you are running emulator tasks outside the runner's sandbox (e.g., a custom bwrap invocation), add:

```bash
bwrap ... --dev-bind /dev/kvm /dev/kvm ...
```

**Diagnosis**: If the emulator is running with `-accel off` despite KVM being available on the host, check whether the process is inside a bwrap sandbox (`ps aux | grep bwrap`). The `start-emulator` script checks `/dev/kvm` writability at runtime — if it's not visible inside the sandbox, it silently falls back to software emulation.

### Xvfb for headless display

```yaml
- name: Run E2E with virtual display
  run: xvfb-run --auto-servernum -- make e2e-local
```

## Preset behavior

| Preset | E2E runtime testing |
|--------|-------------------|
| **poc** | Skip entirely — no E2E tests |
| **local** | Only if the project targets a platform runtime (e.g., CLI tool = skip, Android app = include) |
| **library** | Skip unless the library has a platform-specific component (e.g., React Native bridge, WASM module) |
| **extension** | Required — extensions must be tested in their host (browser, IDE, etc.) |
| **public** | Required for any platform runtime target |
| **enterprise** | Required for all platform targets, with multi-runtime orchestration for cross-platform interactions |

## What the spec and plan MUST include

- **Spec (Phase 2)**: Identify every platform runtime the project targets. For each, include functional requirements for E2E tests that exercise real user flows on the real runtime.
- **Plan (Phase 5)**: For each platform runtime, decide: emulator/simulator/headless browser setup, test bypass mechanisms for hardware features, UI automation framework, CI infrastructure. Add to the test plan matrix.
- **Tasks (Phase 6)**: See the E2E test harness gap analysis in `phases/tasks.md`. Ensure every prerequisite (build infrastructure, emulator setup, test helper library, bypass mechanisms, CI retry wrapper) has its own task.

## Backend service setup for MCP E2E loops

When the MCP-driven E2E loop needs backend services (databases, API servers, mesh networks, daemons), the runner automatically calls a **project-level setup script** before the first explore agent runs.

### Convention: `test/e2e/setup.sh` and `test/e2e/teardown.sh`

The runner checks for `test/e2e/setup.sh` in the project root. If it exists, it runs it once before booting the emulator/browser/simulator. On teardown, it runs `test/e2e/teardown.sh`.

**`setup.sh` requirements:**
- Start all backend services needed for the app to function end-to-end
- Be **idempotent** (safe to call if services are already running)
- Perform readiness checks (wait for each service to be ready before returning)
- Write PIDs or state to a known location (e.g., `$E2E_PROJECT_DIR/test/e2e/.state/`) for teardown
- Exit 0 when all services are ready, non-zero on failure
- The runner passes `E2E_PROJECT_DIR` as an environment variable

**`teardown.sh` requirements:**
- Stop all services started by `setup.sh`
- Clean up state files
- Be safe to call even if services aren't running

### Example: Android app with mesh network backend

```bash
#!/usr/bin/env bash
# test/e2e/setup.sh — start headscale + tailscale + daemon for E2E
set -euo pipefail

STATE_DIR="${E2E_PROJECT_DIR}/test/e2e/.state"
mkdir -p "$STATE_DIR"

# Skip if already running
if [ -f "$STATE_DIR/setup.pid" ] && kill -0 "$(cat "$STATE_DIR/setup.pid")" 2>/dev/null; then
  echo "Services already running"
  exit 0
fi

# Start headscale
headscale serve &
echo $! > "$STATE_DIR/headscale.pid"
wait_for "headscale" "curl -sf http://127.0.0.1:8080/health" 30

# Start tailscaled and join mesh
tailscaled --state="$STATE_DIR/tailscale" &
echo $! > "$STATE_DIR/tailscaled.pid"
tailscale up --login-server=http://127.0.0.1:8080 --auth-key="..."
wait_for "tailscale" "tailscale status --json" 30

# Start app daemon
nix-key daemon --config="$STATE_DIR/config.yaml" &
echo $! > "$STATE_DIR/daemon.pid"
wait_for "daemon" "test -S /tmp/agent.sock" 10

echo "$$" > "$STATE_DIR/setup.pid"
echo "All E2E backend services ready"
```

### Task generation

When the spec/plan indicates the app communicates with backend services (server, daemon, database, mesh network, etc.), task generation MUST include a setup script task **before** the MCP E2E exploration task:

```markdown
- [ ] T0XX Create E2E backend services setup script (`test/e2e/setup.sh`): starts [list services], waits for readiness, writes PIDs for teardown. Matching `teardown.sh` stops all services. [E2E infra]
  Done when: `bash test/e2e/setup.sh` starts all services and exits 0, `bash test/e2e/teardown.sh` stops them cleanly.

- [ ] T0XX E2E integration test exploration [needs: mcp-android, e2e-loop]
  Done when: all screens and flows from UI_FLOW.md verified on emulator with live backend services.
```

The runner calls `setup.sh` automatically before the E2E loop — no `[needs: e2e-services]` annotation is required. The convention is file-based: if `test/e2e/setup.sh` exists, it runs.

## Task generation guidance

### Infrastructure tasks (foundational phase or early platform phase)

```markdown
- [ ] T0XX Create E2E backend services setup/teardown scripts (`test/e2e/setup.sh`, `test/e2e/teardown.sh`): start all backend services needed for E2E testing, wait for readiness, write PIDs for cleanup. Must be idempotent. [E2E infra]
  Done when: setup starts all services and exits 0, teardown stops them cleanly.

- [ ] T0XX Create E2E test orchestrator script (`test/e2e/run-e2e.sh`): shell script that starts all services/runtimes, waits for readiness, runs test sequence, collects logs on failure, cleans up on exit. Timeout budget: 20 minutes. Retry wrapper: 2 attempts. [E2E infra]
  Done when: script boots all runtimes, waits for readiness, runs a no-op test, cleans up.

- [ ] T0XX Create [platform] test helper library: reusable UI automation helper with methods for common actions (navigate, tap, type, wait, approve/deny dialogs). Include retry logic per method for UI flakiness. Self-test against the app on a local [emulator/browser/simulator]. [E2E infra]
  Done when: each helper method works against the real app on a real runtime.

- [ ] T0XX Add test bypass for [hardware feature]: deep link / test flag / mock API that bypasses [camera/biometrics/NFC/etc.] in debug builds only. Verify bypass is absent in release builds. [E2E infra]
  Done when: bypass works on emulator, release build does NOT expose bypass.
```

### E2E test tasks (late phase, after all unit/integration tests pass)

```markdown
- [ ] T0XX Write [platform] E2E test: exercise full user flow on real [emulator/browser/simulator]. Steps: [enumerate steps from the user story]. Verify final observable result. Test denial/error paths. Timeout: 5 minutes per flow. [Story X, SC-xxx]
  Done when: E2E test passes on real runtime, failure paths verified, logs collected on failure.
```

### Pre-PR integration task

```markdown
- [ ] T0XX Wire E2E into pre-pr gate: add `make e2e-local` to `make pre-pr`. Include timeout (20m), retry (2 attempts), `SKIP_E2E=1` bypass. [DX, pre-pr]
  Done when: `make pre-pr` runs E2E tests after unit/integration/lint/security pass.
```

## MCP-driven E2E exploration (agent-interactive testing)

For projects where the interview confirmed MCP debug tool usage, the runner supports a fully automated **explore-fix-verify loop** using MCP tools. See `reference/mcp-e2e.md` for the complete pattern.

### When to use MCP-driven E2E vs scripted E2E

| Approach | Best for | Strengths | Weaknesses |
|----------|----------|-----------|------------|
| **Scripted E2E** (UI Automator, Playwright) | CI/CD gates, regression suites | Deterministic, fast, repeatable | Only tests what you wrote tests for |
| **MCP-driven exploration** | Bug discovery, visual validation, comprehensive coverage | Finds unexpected bugs, adapts to UI changes | Slower, non-deterministic, needs supervisor |
| **Both** (recommended) | Production apps | Scripted catches regressions, MCP finds new bugs | More infrastructure to maintain |

### MCP E2E task example

```markdown
- [ ] T0XX E2E integration test exploration [needs: mcp-android, e2e-loop]
  Done when: all screens and flows from UI_FLOW.md have been visually verified
  on the Android emulator, all discovered bugs are fixed and verified,
  findings.json shows zero open bugs.
```

The runner handles: emulator boot → APK build+install → MCP server start → explore agent → fix agent → rebuild+install → verify agent → supervisor checks → repeat until clean.

### Integration with scripted E2E

MCP-driven exploration and scripted E2E tests are complementary:
1. **Run MCP exploration first** to discover bugs and validate the app works visually
2. **Then write scripted E2E tests** for each flow verified by MCP exploration, ensuring they stay green in CI
3. **Run MCP exploration periodically** (e.g., on major releases) to catch new visual bugs

The MCP explore agent's `findings.json` can inform what scripted tests to write — each verified flow becomes a regression test.
