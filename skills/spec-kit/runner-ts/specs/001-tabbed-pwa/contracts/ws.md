# WebSocket Contract — tabrunner v1

## Connection

- **URL**: `wss://<tailscale-ip>:<port>/api/v1/ws`
- **Auth**: mTLS — the underlying TLS handshake establishes identity. Server rejects upgrade if no client cert (this is enforced before upgrade by Fastify HTTPS server).
- **Subprotocol**: `tabrunner-v1` (sent in `Sec-WebSocket-Protocol` header; server confirms).
- **One WS connection per PWA tab visibility** — the PWA opens one WS and multiplexes all session events through it.

## Message envelope

Every message in either direction is a JSON object with this shape:

```ts
type Envelope =
  | ClientToServer
  | ServerToClient;

interface BaseEnvelope {
  type: string;
  session_id: string | null;  // null for connection-level events (e.g. hello)
  seq: number;                 // monotonic per session_id; 0 for null session_id
  payload: unknown;            // type-specific; see below
}
```

`seq` is set by the *sender*. For server → client events, seq is monotonic per session_id (server multiplexer tracks). For client → server, seq is monotonic per (connection, session_id).

Replay buffer: server retains the last 60 seconds of `session.*` events per session_id, indexed by seq. On reconnect, client sends `client.resume` with last-seen seq per session_id.

## Server → Client events

### `connection.hello`
Sent immediately after WS upgrade.

```json
{
  "type": "connection.hello",
  "session_id": null,
  "seq": 0,
  "payload": {
    "connection_id": "<uuid>",
    "server_version": "0.1.0",
    "now": "2026-05-24T14:23:11.456Z"
  }
}
```

### `connection.error`
Fatal connection-level error. Client should reconnect after backoff.

```json
{
  "type": "connection.error",
  "session_id": null,
  "seq": 0,
  "payload": {
    "code": "<error_code>",
    "message": "..."
  }
}
```

### `session.created`
A new session row was created (in response to client `client.spawn`, OR from another client's action — multiple PWA windows see each other's session creations).

```json
{
  "type": "session.created",
  "session_id": "<uuid>",
  "seq": 1,
  "payload": {
    "title": "New session",
    "project_path": "/home/max/git/foo",
    "started_at": "2026-05-24T14:23:11.456Z",
    "pinned": false
  }
}
```

### `session.status`
Status changed (pending → running → exited/crashed/terminated).

```json
{
  "type": "session.status",
  "session_id": "<uuid>",
  "seq": 2,
  "payload": {
    "status": "running",
    "pid": 12345,
    "last_activity_at": "2026-05-24T14:23:12.000Z"
  }
}
```

### `session.stdout`
Raw bytes from claude PTY (base64 encoded for transport). Use case: "Show raw" toggle in the PWA tab.

```json
{
  "type": "session.stdout",
  "session_id": "<uuid>",
  "seq": 3,
  "payload": {
    "data_b64": "SGVsbG8gd29ybGQ=",
    "timestamp": "2026-05-24T14:23:12.100Z"
  }
}
```

**Note**: `session.stdout` is emitted continuously as bytes arrive from the PTY. PWA may batch render.

### `session.message`
Parsed message derived from the JSONL watcher. Primary chat-rendering signal.

```json
{
  "type": "session.message",
  "session_id": "<uuid>",
  "seq": 4,
  "payload": {
    "message_id": "<uuid-or-derived>",
    "role": "user" | "assistant" | "tool_call" | "tool_result",
    "content": "...",
    "timestamp": "2026-05-24T14:23:12.500Z",
    "metadata": {
      "tool_name": "Bash",            // only when role=tool_call|tool_result
      "tool_call_id": "<id>",          // links tool_call ↔ tool_result
      "truncated": false               // true if content was server-side truncated
    }
  }
}
```

### `session.exit`
Session has ended.

```json
{
  "type": "session.exit",
  "session_id": "<uuid>",
  "seq": 99,
  "payload": {
    "status": "exited" | "crashed" | "terminated",
    "exit_code": 0,
    "exit_signal": null,
    "exited_at": "2026-05-24T14:30:00.000Z",
    "reason": "operator closed tab" | "claude exited normally" | "process killed by SIGTERM after 10s grace"
  }
}
```

### `session.shutdown_pending`
Sent during server graceful shutdown so PWA can show a banner.

```json
{
  "type": "session.shutdown_pending",
  "session_id": null,
  "seq": 0,
  "payload": {
    "deadline_s": 10,
    "reason": "SIGTERM received"
  }
}
```

### `pair.complete`
Sent on the pairing flow's completion (used by pairing page that opens its own WS).

```json
{
  "type": "pair.complete",
  "session_id": null,
  "seq": 0,
  "payload": {
    "fingerprint": "ab:cd:ef:..."
  }
}
```

### `meta.tool_call` / `meta.tool_result`
Reflected events when the meta agent invokes MCP tools — visible in the Meta tab UI.

```json
{
  "type": "meta.tool_call",
  "session_id": "<meta-session-id>",
  "seq": 10,
  "payload": {
    "audit_id": "<uuid>",
    "tool": "tail_live",
    "args": { "session_id": "<other-session>", "lines": 30 }
  }
}
```

```json
{
  "type": "meta.tool_result",
  "session_id": "<meta-session-id>",
  "seq": 11,
  "payload": {
    "audit_id": "<uuid>",
    "outcome": "ok",
    "result_size_bytes": 1234
  }
}
```

---

## Client → Server commands

### `client.hello`
First message after receiving `connection.hello`. Identifies the PWA's intent and last-seen sequences for resume.

```json
{
  "type": "client.hello",
  "session_id": null,
  "seq": 0,
  "payload": {
    "pwa_version": "0.1.0-abcd1234",
    "resume": {
      "<session-id-1>": 42,
      "<session-id-2>": 7
    }
  }
}
```

Server responds by replaying any buffered events with `seq > resume[<session_id>]` for each session, then resumes live streaming.

### `client.spawn`
Request to create a new session.

```json
{
  "type": "client.spawn",
  "session_id": null,
  "seq": 1,
  "payload": {
    "title": "Refactor auth",
    "resume_id": null
  }
}
```

Server creates the row + spawns; PWA receives `session.created`, then `session.status`, etc.

### `client.input`
Send a prompt to a session's claude PTY.

```json
{
  "type": "client.input",
  "session_id": "<uuid>",
  "seq": 5,
  "payload": {
    "text": "hello\n",
    "append_newline": false
  }
}
```

**Notes**:
- `text` may contain newlines. `append_newline` is true when the operator pressed Enter (without a trailing newline already in text); false for raw-paste flows.
- Server writes `text` (plus `\n` if append_newline) to the PTY's stdin.

### `client.interrupt`
Send Ctrl-C to a session.

```json
{
  "type": "client.interrupt",
  "session_id": "<uuid>",
  "seq": 6,
  "payload": {}
}
```

Server writes `\x03` (Ctrl-C) to the PTY.

### `client.close_tab`
Request to terminate a session (tab closed).

```json
{
  "type": "client.close_tab",
  "session_id": "<uuid>",
  "seq": 7,
  "payload": {}
}
```

Server SIGTERMs the session's PID; emits `session.exit` when done.

### `client.subscribe`
Subscribe to a session's event stream (used when opening an existing session in a new tab).

```json
{
  "type": "client.subscribe",
  "session_id": "<uuid>",
  "seq": 8,
  "payload": {
    "since_seq": 0
  }
}
```

Server replays events from `since_seq` (or whole buffer if `since_seq` is 0) then continues live.

### `client.unsubscribe`
Stop receiving events for a session (PWA closed the tab but session keeps running).

```json
{
  "type": "client.unsubscribe",
  "session_id": "<uuid>",
  "seq": 9,
  "payload": {}
}
```

Server removes this WS connection from the session's subscriber set. Session keeps running unless `client.close_tab` was sent.

---

## Error handling

If the server cannot process a client command, it sends an envelope with `type: "client.error"`:

```json
{
  "type": "client.error",
  "session_id": "<related-session-or-null>",
  "seq": 0,
  "payload": {
    "in_response_to_seq": 5,
    "in_response_to_type": "client.input",
    "code": "session_not_running",
    "message": "Cannot send input to session <id>: status=exited"
  }
}
```

---

## Backpressure

If the server's per-session event queue exceeds 10,000 buffered events for a slow client, the server sends a `connection.error` with code `client_too_slow` and closes the connection. The PWA reconnects and re-fetches via REST.

## Disconnect

Server closes WS with code 1000 (normal) on operator-initiated logout or `client.close_tab` for the last tab. Code 1001 (going away) on server shutdown. Code 1011 (internal error) on unexpected server-side failures.
