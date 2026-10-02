# Health Checks

Every deployable project MUST implement health check endpoints (servers) or health check commands (CLIs/batch jobs).

## Server projects — two endpoints

**`GET /health`** (liveness):
- Returns **200** if the process is alive, regardless of dependency state
- Body includes full status for human/dashboard consumption:
```json
{
  "status": "ok",
  "uptime": 12345,
  "version": "1.2.3",
  "ready": true,
  "dependencies": {
    "database": "ok",
    "redis": { "status": "timeout", "latency": null },
    "external-api": "ok"
  }
}
```
- Kubernetes uses the status code (200 = alive); humans/dashboards read the body

**`GET /ready`** (readiness):
- Returns **200** when the service can accept traffic
- Returns **503** during startup (still initializing), during shutdown (draining), or when a critical dependency is down
- Same response body as `/health`
- Kubernetes uses this to control traffic routing

## Dependency check strategy

The plan MUST specify how readiness probes check dependencies — active checks (ping on each probe, simpler but adds latency) vs. cached/background checks (faster probes but potentially stale).

## CLI tools

Implement a `--check` or `--validate` flag that:
- Verifies all dependencies are available (tools installed, services reachable, config valid)
- Exits 0 if everything is OK, exits 1 with a clear error message if not

## Batch/cron jobs

Exit code is the primary health signal:
- Exit 0 = success
- Exit non-zero = failure
- Structured JSON output on completion: `{ "status": "ok", "processed": 42, "failed": 0, "duration": 12340 }`

## Libraries

Skip health checks — health is the consumer's responsibility.
