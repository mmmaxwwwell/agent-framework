# Error Handling Strategy

Every project MUST implement a consistent error handling strategy. Without explicit guidance, agents create different error patterns per module — some throw strings, some use Error subclasses, some return null, some swallow errors silently.

## Error hierarchy

Every project MUST define a project-level error base class with typed subclasses. The hierarchy below is a starting template — **customize it for the project** based on decisions made during the interview (e.g., add domain-specific error types, adjust HTTP mappings, rename the base class to match the project):

```
AppError (base)
├── ValidationError      — invalid input (400)
├── NotFoundError        — resource doesn't exist (404)
├── ConflictError        — state conflict (409)
├── AuthenticationError  — identity not verified (401)
├── AuthorizationError   — insufficient permissions (403)
├── ExternalServiceError — downstream service failed (502)
├── RateLimitError       — too many requests (429)
└── InternalError        — unexpected failure (500)
```

Each error class MUST include:
- **Error code**: Machine-readable string (e.g., `ERR_PROJECT_NOT_FOUND`, `ERR_SESSION_CONFLICT`). Clients use these to handle specific errors programmatically.
- **HTTP status mapping**: For API projects, each error type maps to a status code.
- **User-facing flag**: Whether the error message is safe to show to end users. Internal errors expose a generic message; validation errors expose the specific issue.

## Error propagation pattern

1. **Throw at the point of failure** with full context (what was attempted, what failed, relevant IDs)
2. **Catch at the boundary** (API handler, CLI entry point, event loop top)
3. **Log with full context at the catch site** — stack trace, error code, correlation ID, relevant entity IDs
4. **Return a sanitized response** to the caller — user-facing message, error code, HTTP status
5. **Never swallow errors** — every caught error is either handled (with logging) or re-thrown
6. **Never log-and-rethrow** — this causes double logging. Either handle it (log + respond) or let it propagate

## Unhandled rejection / uncaught exception handling

Every project MUST register a global handler for unhandled exceptions and unhandled promise rejections that:
1. Logs the error at FATAL level with full stack trace and context
2. Triggers the graceful shutdown sequence (see `reference/shutdown.md`)
3. Exits with a non-zero exit code

This prevents silent crashes where the process dies and nobody knows why.
