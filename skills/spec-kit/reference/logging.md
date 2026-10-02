# Structured Logging

Every project MUST implement structured logging with a consistent strategy across all modules. The logging library is determined during the interview phase.

## Log levels

Use the standard 5-level hierarchy. Every log statement must use the correct level — agents tend to over-use ERROR and under-use WARN:

| Level | When to use | Examples |
|-------|-------------|---------|
| **DEBUG** | Internal state useful only during development/troubleshooting. Never enable in production by default. | Variable values, function entry/exit, cache hit/miss, SQL queries, request/response bodies (PII omitted) |
| **INFO** | Lifecycle events and significant state changes. The "story" of what the system is doing. | Server started on port 3000, request completed (method, path, status, duration), session created, migration applied, shutdown initiated |
| **WARN** | Recoverable issues that may indicate a problem. The system continues but something is degraded or unexpected. | Retry succeeded after 2 attempts, deprecated API called, connection pool near capacity, rate limit approaching, config fallback used |
| **ERROR** | Operation failed but the system continues serving other requests. Requires investigation but not immediate action. | Request handler threw exception, external service returned 500, database query failed, file write failed |
| **FATAL** | System cannot continue. Process will exit after logging. | Database connection failed on startup, required config missing, port already in use, unrecoverable corruption detected |

## Output format

All logs MUST be structured JSON. No exceptions, even for "simple" projects. Structured logs are machine-parseable, filterable, and aggregatable — critical for both human debugging and agentic fix-validate loops.

Every log entry MUST include these fields:

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string (ISO 8601) | When the event occurred |
| `level` | string | DEBUG, INFO, WARN, ERROR, FATAL |
| `message` | string | Human-readable description of the event |
| `module` | string | Component/module name (e.g., `http-server`, `session-manager`, `onboarding`) |
| `correlationId` | string (optional) | Request/operation trace ID — present for all log entries within a single request/operation flow |

Additional fields for ERROR/FATAL:

| Field | Type | Description |
|-------|------|-------------|
| `error` | string | Error message |
| `errorCode` | string | Machine-readable error code (e.g., `ERR_SESSION_CONFLICT`) |
| `stack` | string | Stack trace |

## Log destination

Configure via the logging library — do not use raw `console.log` or `print`. The standard convention:
- **Application logs** → stderr (structured JSON)
- **Structured output/data** → stdout (if applicable)

The logging library must support configurable log levels (e.g., set to WARN in production, DEBUG in development) via environment variable or config file.

## What the plan MUST include

- Logging infrastructure as an early task (before feature work)
- Log level usage guidelines in the coding standards section of the plan

## Correlation IDs

For server/API projects: every incoming request generates a correlation ID at the entry point. This ID is attached to every log entry for that request's lifecycle and propagated to downstream calls (via HTTP headers, message metadata, etc.). For non-request-driven operations (cron jobs, background workers), generate a correlation ID per operation. This enables filtering all logs for a single request/operation across all modules and services.
