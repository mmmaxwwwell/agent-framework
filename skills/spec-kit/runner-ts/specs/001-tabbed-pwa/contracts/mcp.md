# MCP Contract — tabrunner meta-agent tools

The tabrunner MCP server runs on stdio and is attached to the meta agent's `claude` session via `.mcp.json`:

```json
{
  "mcpServers": {
    "tabrunner": {
      "command": "node",
      "args": ["dist/meta-agent/mcp-server.js"],
      "env": {
        "TABRUNNER_DATA_DIR": "${TABRUNNER_DATA_DIR}",
        "TABRUNNER_PROJECT": "${TABRUNNER_PROJECT}"
      }
    }
  }
}
```

All tools are **read-only**. There are no spawn/kill/edit/shell tools. Every tool call is audited via the audit channel (FR-063).

## Tools

### `query_sessions`

List sessions with optional filters.

**Input schema** (zod):
```ts
z.object({
  project: z.string().optional(),
  status: z.enum(["pending","running","exited","crashed","terminated"]).optional(),
  pinned: z.boolean().optional(),
  since: z.string().datetime().optional(),
  limit: z.number().int().min(1).max(200).default(50)
})
```

**Output**:
```ts
z.object({
  sessions: z.array(z.object({
    id: z.string().uuid(),
    project_path: z.string(),
    title: z.string(),
    status: z.enum(["pending","running","exited","crashed","terminated"]),
    started_at: z.string().datetime(),
    last_activity_at: z.string().datetime(),
    exited_at: z.string().datetime().nullable(),
    exit_code: z.number().int().nullable(),
    exit_signal: z.string().nullable(),
    pid: z.number().int().nullable(),
    pinned: z.boolean(),
    message_count: z.number().int()
  })),
  next_cursor: z.string().nullable()
})
```

### `read_session`

Read parsed messages from one session.

**Input**:
```ts
z.object({
  session_id: z.string().uuid(),
  since_seq: z.number().int().min(0).default(0),
  limit: z.number().int().min(1).max(200).default(50)
})
```

**Output**:
```ts
z.object({
  session_id: z.string().uuid(),
  messages: z.array(z.object({
    message_id: z.string(),
    seq: z.number().int(),
    role: z.enum(["user","assistant","tool_call","tool_result"]),
    content: z.string(),
    timestamp: z.string().datetime(),
    metadata: z.object({
      tool_name: z.string().optional(),
      tool_call_id: z.string().optional(),
      truncated: z.boolean().default(false)
    }).optional()
  })),
  next_cursor: z.number().int().nullable()
})
```

### `tail_live`

Get the last N raw stdout bytes from a running session's PTY.

**Input**:
```ts
z.object({
  session_id: z.string().uuid(),
  lines: z.number().int().min(1).max(1000).default(50)
})
```

**Output**:
```ts
z.object({
  session_id: z.string().uuid(),
  buffer: z.string(),       // utf-8 decoded raw bytes; invalid bytes replaced with U+FFFD
  exited: z.boolean(),       // true if session has terminated
  exit_code: z.number().int().nullable(),
  last_activity_at: z.string().datetime()
})
```

**Error**: `session_not_found` if the session id is unknown to the server.

### `list_running`

Enumerate active (status=running) sessions.

**Input**: `z.object({})` (no args)

**Output**:
```ts
z.object({
  running: z.array(z.object({
    session_id: z.string().uuid(),
    pid: z.number().int(),
    project_path: z.string(),
    title: z.string(),
    started_at: z.string().datetime(),
    last_activity_at: z.string().datetime()
  }))
})
```

### `search_messages`

FTS5 search over message content.

**Input**:
```ts
z.object({
  query: z.string().min(1),
  scope: z.object({
    session_id: z.string().uuid().optional(),
    project: z.string().optional(),
    since: z.string().datetime().optional(),
    role: z.enum(["user","assistant","tool_call","tool_result"]).optional()
  }).optional(),
  limit: z.number().int().min(1).max(100).default(20)
})
```

**Output**:
```ts
z.object({
  matches: z.array(z.object({
    session_id: z.string().uuid(),
    message_id: z.string(),
    role: z.string(),
    snippet: z.string(),           // FTS5 snippet() with highlight markers
    timestamp: z.string().datetime(),
    rank: z.number()                // FTS5 bm25 rank (lower = better)
  })),
  pending_index: z.boolean()         // true if FTS indexer hasn't caught up to recent sessions
})
```

### `search_sessions`

FTS over session metadata (title, first user message, project path).

**Input**:
```ts
z.object({
  query: z.string().min(1),
  limit: z.number().int().min(1).max(100).default(20)
})
```

**Output**:
```ts
z.object({
  matches: z.array(z.object({
    session_id: z.string().uuid(),
    title: z.string(),
    project_path: z.string(),
    snippet: z.string(),
    rank: z.number()
  }))
})
```

### `read_project_file`

Read a file in the watched project directory. Path-traversal guard MUST resolve the real path (following symlinks) and reject anything outside `config.project`.

**Input**:
```ts
z.object({
  path: z.string().min(1),    // relative to watched project OR absolute (must be inside)
  encoding: z.enum(["utf-8","base64"]).default("utf-8"),
  max_bytes: z.number().int().min(1).max(1_000_000).default(100_000)
})
```

**Output**:
```ts
z.object({
  path: z.string(),            // normalized, absolute
  content: z.string(),
  encoding: z.enum(["utf-8","base64"]),
  size_bytes: z.number().int(),
  truncated: z.boolean()       // true if file exceeds max_bytes
})
```

**Errors**:
- `path_outside_project` (403): file resolves outside `config.project`. Audited.
- `not_found` (404).
- `is_directory` (422).
- `not_readable` (403): permission denied.

### `list_project_files`

Glob files in the watched project.

**Input**:
```ts
z.object({
  glob: z.string().default("**/*"),
  max_results: z.number().int().min(1).max(10_000).default(1000),
  include_hidden: z.boolean().default(false)
})
```

**Output**:
```ts
z.object({
  matches: z.array(z.object({
    path: z.string(),          // relative to project root
    size_bytes: z.number().int(),
    modified_at: z.string().datetime(),
    is_directory: z.boolean()
  })),
  truncated: z.boolean()
})
```

Same path-traversal guard as `read_project_file`.

### `get_session_summary`

Cached (60s TTL) summary of a session.

**Input**:
```ts
z.object({ session_id: z.string().uuid() })
```

**Output**:
```ts
z.object({
  session_id: z.string().uuid(),
  first_user_message: z.string().nullable(),
  last_assistant_message: z.string().nullable(),
  tool_call_count: z.number().int(),
  message_count: z.number().int(),
  started_at: z.string().datetime(),
  last_activity_at: z.string().datetime(),
  status: z.string()
})
```

---

## Tool registration

```ts
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = new Server(
  { name: "tabrunner", version: "0.1.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    { name: "query_sessions", description: "...", inputSchema: zodToJsonSchema(queryInput) },
    // ... 8 more
  ]
}));

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  const audit_id = crypto.randomUUID();
  logger.info({ channel: "audit", audit_id, actor: "meta-agent", tool: req.params.name, args: req.params.arguments }, "mcp_tool_call");
  try {
    const result = await tools[req.params.name](req.params.arguments);
    logger.info({ channel: "audit", audit_id, outcome: "ok" }, "mcp_tool_result");
    return { content: [{ type: "text", text: JSON.stringify(result) }] };
  } catch (e) {
    logger.warn({ channel: "audit", audit_id, outcome: "error", reason: e.message }, "mcp_tool_error");
    throw e;
  }
});

await server.connect(new StdioServerTransport());
```

## What is forbidden

The MCP server MUST NOT define any tool that:

- Spawns a process
- Sends a signal
- Writes a file
- Modifies a database row
- Runs a shell command
- Returns content from outside `config.project` directory
- Returns content from `<data_dir>/` (CA key, server cert key)

A test (`tests/contract/mcp-tools.test.ts`) enumerates registered tools and asserts none match these names: `spawn`, `kill`, `write_file`, `exec`, `shell`, `update`, `delete`, `revoke`, `create`. Adding a forbidden tool causes the test to fail, blocking the commit at the pre-PR gate.
