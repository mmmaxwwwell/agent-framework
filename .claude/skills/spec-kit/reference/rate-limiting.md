# Rate Limiting & Backpressure

The rate limiting strategy is determined during the interview. When implemented, the following patterns apply:

## Implementation requirements

- **Per-client rate limits**: Sliding window or token bucket, configurable limits per endpoint or globally
- **Rate limit headers**: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` in responses
- **429 response**: Structured error with `Retry-After` header
- **Bounded queues**: For projects that queue work — explicit behavior when full (reject, backpressure, or drop oldest)
- **Connection limits**: Maximum concurrent connections setting as a safety valve
- **Timeout budgets**: Every external call (HTTP, database, DNS) MUST have an explicit timeout

## Documentation

Whatever strategy is chosen (including "deferred"), document it in the project README and agentic documentation. If deferred, include a TODO with the recommended approach so it's not forgotten.
