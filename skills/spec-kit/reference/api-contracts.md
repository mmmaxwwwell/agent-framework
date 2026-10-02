# API Contract Depth

Spec-kit's plan phase produces contract documentation. The skill mandates minimum depth — implementing agents need unambiguous references.

## For REST/RPC APIs — per endpoint:

1. **Method + path** (e.g., `POST /api/sessions`)
2. **Request schema** with a concrete JSON example showing all fields
3. **Response schema** with concrete JSON examples for success and each error case
4. **All status codes** with their meaning and trigger:
   | Status | Meaning | Trigger |
   |--------|---------|---------|
   | 201 | Created | Session successfully started |
   | 400 | Bad Request | Missing required field `projectId` |
   | 404 | Not Found | Project ID doesn't exist |
   | 409 | Conflict | Active session already exists for this project |
5. **Authentication/authorization** requirements per endpoint

## For WebSocket/SSE/real-time channels — per channel:

1. **Path** and connection parameters
2. **Message types** with direction (client→server, server→client, bidirectional)
3. **Payload schema** with concrete JSON example for each message type
4. **Connection lifecycle** — what happens on connect, disconnect, reconnect
5. **Sequencing/replay** — how clients resume after disconnection

## For binary/custom protocols (IPC, Unix sockets, custom wire formats):

1. **Wire format** — byte order, length prefixes, header structure, message type codes
2. **Message type enumeration** with byte values
3. **Payload format** per message type with annotated byte layout
4. **Flow diagrams** showing message exchange sequences

## For inter-process communication (JavaScript bridges, Android Intents, IPC channels):

1. **Method signatures** with parameter types and return types
2. **Async behavior** — which calls are synchronous, which return promises/callbacks
3. **Error propagation** — how errors cross the boundary
