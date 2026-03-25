# Observability Hooks

Beyond logging, the system needs hooks for metrics, tracing, and error reporting. The specific tools are determined during the interview.

## Implementation requirements

**Metrics emission points** — key operations MUST emit metrics:
- **Request metrics**: count, latency histogram, error rate (by endpoint, by status code)
- **Resource metrics**: active connections, queue depth, pool utilization, memory/CPU
- **Business metrics**: operations completed, entities created, sessions active

**Trace context propagation** — a trace/correlation ID MUST be generated at the entry point and propagated through:
- All log entries (see `reference/logging.md` — Correlation IDs)
- HTTP headers to downstream services (`X-Request-ID`, `traceparent` for W3C Trace Context)
- Message queue metadata
- Error reports

**Structured error reporting** — error reports MUST include: stack trace, correlation ID, environment (staging/production), user context (anonymized), and breadcrumbs (recent actions leading to the error).

**Request/response logging** — at DEBUG level, log API requests and responses with enough detail to replay them. **PII omission**: NEVER log personally identifiable information. Mask or redact sensitive fields.

**Documentation** — document the observability strategy in both agentic and human documentation (CLAUDE.md, README).
