# MCP Emulator Server — Design Prompt

This file is a prompt for building an MCP (Model Context Protocol) server that wraps Android emulators, iOS simulators, and headless browsers, giving Claude agents visual access to running apps for E2E test development and debugging.

**Status**: Not yet implemented. This is a design spec for a future standalone tool.

---

## Problem

When agents write E2E tests for mobile/web apps, they're scripting UI interactions blind — they don't know what's on screen, what selectors to use, what the layout looks like, or why a test failed. They generate UI Automator helpers, Playwright scripts, and XCUITest code based on source code alone, which leads to:

- Wrong selectors (element doesn't exist, wrong ID, content description mismatch)
- Wrong interaction sequences (screen hasn't loaded yet, dialog blocking, unexpected navigation state)
- Undiagnosable failures (test fails but agent can't see what the screen looks like at failure time)

## Solution

An MCP server that exposes running app runtimes as Claude tools. The agent can take screenshots, tap coordinates, type text, swipe, read accessibility trees, and inspect view hierarchies — the same way a human developer would use an emulator/browser while writing tests.

## Target Runtimes

| Runtime | Underlying tool | Screenshot | Touch/Click | Type | Accessibility tree |
|---------|----------------|------------|-------------|------|--------------------|
| Android Emulator | `adb` | `adb exec-out screencap -p` | `adb shell input tap x y` | `adb shell input text "..."` | `adb shell uiautomator dump` |
| iOS Simulator | `xcrun simctl` | `xcrun simctl io booted screenshot` | `xcrun simctl io booted tap x y` | `xcrun simctl io booted keyboard type "..."` | `xcrun simctl ui booted accessibilityinfo` (or Accessibility Inspector CLI) |
| Headless Browser | Playwright CDP | `page.screenshot()` | `page.click(selector)` / `page.mouse.click(x, y)` | `page.fill(selector, text)` / `page.keyboard.type(text)` | `page.accessibility.snapshot()` |
| Desktop (Electron) | Playwright Electron | Same as browser | Same as browser | Same as browser | Same as browser |

## MCP Tools to Expose

### Core tools (all runtimes)

```
screenshot(runtime_id?) -> image
  Returns a PNG screenshot of the current screen.
  If multiple runtimes are running, specify which one.
  The image is returned as a base64-encoded PNG for Claude's vision.

tap(x, y, runtime_id?)
  Tap/click at pixel coordinates (x, y).
  For touch devices: single tap. For browsers: left click.

long_press(x, y, duration_ms?, runtime_id?)
  Long press at coordinates. Default duration: 1000ms.

swipe(x1, y1, x2, y2, duration_ms?, runtime_id?)
  Swipe gesture from (x1,y1) to (x2,y2).

type_text(text, runtime_id?)
  Type text via keyboard input. Works with currently focused field.

press_key(key, runtime_id?)
  Press a specific key: ENTER, BACK, HOME, TAB, ESCAPE, etc.
  Android: maps to adb keyevent codes.
  Browser: maps to Playwright keyboard.press().

get_view_tree(runtime_id?) -> json
  Returns the accessibility/view hierarchy as structured JSON.
  Android: uiautomator dump → parsed XML → JSON
  iOS: accessibility tree
  Browser: page.accessibility.snapshot()
  
  This is the primary tool for finding selectors — the agent reads the
  tree to find element IDs, content descriptions, text labels, and
  bounds, then uses those to script interactions.

find_element(selector, runtime_id?) -> {found: bool, bounds: {x, y, w, h}, text?, id?}
  Search for an element by: text content, accessibility ID, resource ID,
  content description, or CSS selector (browser only).
  Returns its bounds and metadata if found.

wait_for_element(selector, timeout_ms?, runtime_id?) -> {found: bool, elapsed_ms}
  Poll for an element to appear. Returns when found or timeout.

launch_app(package_or_url, runtime_id?)
  Android: adb shell am start -n <package>/.MainActivity
  iOS: xcrun simctl launch booted <bundle_id>
  Browser: page.goto(url)

install_app(path, runtime_id?)
  Android: adb install <apk_path>
  iOS: xcrun simctl install booted <app_path>
  Browser: N/A

send_deep_link(uri, runtime_id?)
  Android: adb shell am start -a android.intent.action.VIEW -d <uri>
  iOS: xcrun simctl openurl booted <uri>
  Browser: page.goto(uri)
```

### Runtime management tools

```
list_runtimes() -> [{id, type, status, name}]
  List all managed runtimes (emulators, simulators, browsers).

start_runtime(type, config?) -> runtime_id
  Boot a new runtime instance.
  type: "android", "ios", "chromium", "firefox", "webkit"
  config: API level, device profile, viewport size, etc.

stop_runtime(runtime_id)
  Shut down a runtime instance.

get_logs(runtime_id?, lines?) -> string
  Android: adb logcat -d (last N lines)
  iOS: xcrun simctl spawn booted log show --last 1m
  Browser: collected console.log output
```

## Architecture

```
┌─────────────────────────────────────────┐
│ Claude Agent                            │
│ (uses MCP tools to see/interact with    │
│  running apps while writing E2E tests)  │
└──────────────┬──────────────────────────┘
               │ MCP protocol (stdio or SSE)
               ▼
┌─────────────────────────────────────────┐
│ MCP Emulator Server                     │
│ ├─ Tool router (screenshot, tap, etc.)  │
│ ├─ Runtime registry (tracks instances)  │
│ ├─ Android adapter (adb commands)       │
│ ├─ iOS adapter (xcrun simctl commands)  │
│ ├─ Browser adapter (Playwright CDP)     │
│ └─ Screenshot cache (dedup rapid calls) │
└──────────────┬──────────────────────────┘
               │ subprocess / CDP / adb
               ▼
┌──────────┐ ┌──────────┐ ┌──────────────┐
│ Android  │ │   iOS    │ │   Headless   │
│ Emulator │ │Simulator │ │   Browser    │
└──────────┘ └──────────┘ └──────────────┘
```

## Implementation Notes

### Language choice
TypeScript or Python — both have mature MCP SDK support and good subprocess handling. Python is simpler for shelling out to `adb`/`xcrun`. TypeScript is better if Playwright integration is primary.

### Screenshot optimization
- Resize screenshots to ~1280px wide before returning (save tokens, Claude can still read UI)
- Cache the last screenshot and return it if requested within 500ms (agent often screenshots → reads → screenshots again)
- Return resolution metadata alongside the image so the agent can compute tap coordinates

### Coordinate system
- All coordinates are in **device pixels** (not CSS pixels, not dp)
- The `screenshot` tool returns the image dimensions alongside the PNG
- The agent computes tap coordinates from the screenshot dimensions and element positions
- For browser: Playwright handles device pixel ratio internally

### View tree format
Return a simplified JSON tree, not raw XML. The agent needs:
```json
{
  "type": "Button",
  "text": "Approve",
  "id": "com.nixkey:id/approve_btn",
  "contentDescription": "Approve sign request",
  "bounds": {"x": 100, "y": 500, "width": 200, "height": 48},
  "enabled": true,
  "focused": false,
  "children": []
}
```

### Error handling
- If the runtime isn't running: return a clear error, not a crash
- If `adb` isn't available: return "Android runtime requires adb in PATH"
- If screenshot fails (screen off, emulator frozen): return last successful screenshot with a warning
- Timeout on all subprocess calls (5s default)

### Security
- The MCP server only controls LOCAL emulators/simulators/browsers
- No network exposure — stdio transport only (or localhost SSE)
- No access to host filesystem beyond what adb/simctl expose
- No credential handling — the agent manages auth tokens via the app's test bypass mechanisms

## Use Cases

### 1. Writing UI Automator helpers
Agent boots emulator → installs APK → takes screenshot → reads view tree → identifies selectors → writes helper methods → tests them interactively → iterates until helpers work.

### 2. Debugging E2E test failures
E2E test fails at "approve sign request" step → agent takes screenshot → sees the dialog isn't showing → reads logcat → discovers the gRPC connection failed → fixes the connection issue → retakes screenshot → dialog is visible → test passes.

### 3. Exploring an unfamiliar app
Agent is asked to write E2E tests for an existing app → boots emulator → installs APK → screenshots each screen → reads view trees → maps the navigation graph → writes comprehensive E2E tests covering all flows.

### 4. Visual regression verification
Agent makes a UI change → takes before/after screenshots → compares layout → confirms the change looks correct before committing.

## Future extensions (not in v1)

- **Video recording**: `adb screenrecord` / `xcrun simctl io recordVideo` for capturing test runs
- **Network interception**: proxy for capturing/mocking API calls
- **Performance metrics**: frame rate, memory usage, battery drain via `adb shell dumpsys`
- **Multi-device coordination**: run tests across multiple emulators simultaneously
- **OCR fallback**: when accessibility tree is incomplete, use vision to read screen text
