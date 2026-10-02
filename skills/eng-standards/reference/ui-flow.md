# UI_FLOW.md — Living UI Reference Document

For any project with a user interface (web app, mobile app, PWA, desktop app, or any combination), agents MUST create and incrementally maintain a `UI_FLOW.md` file at the project root. This is the authoritative, single-source-of-truth reference for all screens, routes, user actions, API calls, real-time connections, state transitions, and field validations.

**Skip this entirely** for libraries, CLI tools without interactive UI, API-only services, or any project with no visual interface.

## When to create and update

- **Create** `UI_FLOW.md` when the first UI-related task lands (first screen, first route, first component)
- **Update** it every time a task adds, modifies, or removes a screen, route, API endpoint, WebSocket path, state transition, or field validation. The document MUST stay in sync with the implementation at all times — never let it drift.
- **At phase boundaries**, the implementing agent MUST verify UI_FLOW.md reflects all screens and flows implemented in that phase before marking the phase complete

## Required structure

UI_FLOW.md MUST contain all of the following sections that apply to the project. Omit sections that don't apply (e.g., no Android section if there's no Android client), but never omit a section that does apply. Only include node types and colors for platforms the project actually targets.

### 1. Main Flow Diagram
Mermaid flowchart showing the complete navigation graph. Color-coded nodes:
- **Blue** — top-level web/PWA screens (each has its own route/hash)
- **Orange** — inline components that render within a screen (no route change)
- **Green** — Android native screens (Activities, Dialogs, Fragments)
- **Purple** — iOS native screens (ViewControllers, Sheets)
- **Red** — Desktop native windows/dialogs (Electron, Tauri, etc.)

Arrow types: solid = user-triggered actions and navigation, dotted = on-load API calls (automatic GETs), double-line = persistent real-time connections (WebSocket, SSE).

### 2. State Machines
Mermaid state diagrams for every domain object with non-trivial lifecycle states. Examples:
- Session states (running → waiting-for-input → completed/failed)
- Project/resource status (onboarding → active → error → archived)
- Workflow phases (draft → review → approved → published)
- Connection states (connecting → connected → disconnected → reconnecting)

Each state diagram MUST show all valid transitions, the trigger for each transition, and any terminal states.

### 3. Screen-by-Screen Details
For every screen/view in the application:

| Field | Description |
|-------|-------------|
| **Route** | URL path, hash route, or native screen identifier |
| **Component** | File path to the component/view implementation |
| **On-load API calls** | Endpoints called automatically when the screen loads |
| **User actions** | Every interactive element and what it triggers (navigation, API call, state change) |
| **Field validations** | Per-field validation rules (see Field Validation Reference Table below) |
| **Real-time updates** | WebSocket/SSE channels this screen subscribes to and the message types it handles |
| **Navigation** | Where the user can go from this screen and what triggers it |
| **Error states** | How errors are displayed (inline, toast, redirect, modal) and recovery actions |

### 4. Platform-Native Screens (when applicable)
For projects with native platform components, a dedicated subsection per platform:

- **Android**: Activities, Dialogs, Fragments — lifecycle, Intent extras, JavaScript bridge methods (`window.<BridgeName>.<method>()`)
- **iOS**: ViewControllers, Sheets, SwiftUI views — presentation style, delegate callbacks, JavaScript bridge methods
- **Desktop**: Windows, dialogs, system tray interactions — IPC channels, native menu items

Include how native screens communicate with the web layer (JavaScript bridges, deep links, IPC, intent filters).

### 5. API Sequence Diagrams
Mermaid sequence diagrams for every major multi-step flow. Examples:
- Onboarding/signup flow
- Authentication handshake
- Real-time collaboration lifecycle
- File upload → processing → notification pipeline
- Payment/checkout flow
- Any flow involving more than 2 participants

Each diagram MUST show the participant (client, server, external service, native app), every HTTP request/response, every WebSocket message, and every state change.

### 6. API Endpoint Summary
Table of all REST/RPC endpoints:

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/projects` | required | List all projects |
| POST | `/api/sessions` | required | Create new session |

### 7. Real-Time Paths
Table of all WebSocket, SSE, or other persistent connection endpoints:

| Path | Direction | Messages | Purpose |
|------|-----------|----------|---------|
| `/ws/session/:id` | bidirectional | `output`, `input-request`, `state-change` | Session streaming |

### 8. Generated Files Reference (when applicable)
If the application generates files as part of its workflow:

| File | Created during | Location | Purpose |
|------|---------------|----------|---------|
| `transcript.md` | Interview phase | `specs/<feature>/` | Raw interview transcript |

### 9. Field Validation Reference Table
Comprehensive table of every input field across all screens:

| Screen | Field | Required | Client Validation | Server Validation | Error Message |
|--------|-------|----------|-------------------|-------------------|---------------|
| Project Setup | Project name | yes | 1-100 chars, no special chars | unique check | "Project name already exists" |

Include both explicit validations (form rules) and implicit server-side validations (404 on missing resource, 409 on conflict, etc.).

## Tie to end-to-end testing

Every flow documented in UI_FLOW.md MUST have a corresponding end-to-end test. Each e2e test MUST include a comment referencing the specific UI_FLOW.md section it validates:

```typescript
// Validates: UI_FLOW.md > Onboarding Flow > Step 3: Project creation
test('onboarding creates project and redirects to dashboard', async () => {
  // ...
});
```

When writing the spec (Phase 2), include a functional requirement that e2e tests cover every flow in UI_FLOW.md. When generating tasks (Phase 6), include a late-phase task to verify all UI_FLOW.md flows have corresponding e2e tests.

## CLAUDE.md instruction

When a spec-kit project has a UI, the agent MUST add the following to the project's `CLAUDE.md`:

```markdown
## UI_FLOW.md — Keep It Up to Date

UI_FLOW.md is the single source of truth for all screens, routes, API calls, real-time connections, state transitions, and field validations. **Every agent that adds, modifies, or removes UI elements MUST update UI_FLOW.md in the same commit.** This includes:

- Adding/removing screens or routes
- Changing navigation between screens
- Adding/modifying API endpoints that the UI calls
- Adding/modifying WebSocket or SSE channels
- Changing field validations
- Adding/modifying state machines
- Adding platform-native screens or bridges

Never let UI_FLOW.md drift from the implementation. If you touch UI code, check UI_FLOW.md.
```
