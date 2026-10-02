# Graceful Shutdown

Every server/daemon project MUST implement graceful shutdown.

## Signal handling

Register handlers for SIGTERM and SIGINT that trigger a shutdown sequence. The shutdown MUST be logged at INFO level at every step.

## Shutdown sequence

Execute in this order (reverse of initialization):

1. **Log** `INFO: Shutdown initiated (signal: SIGTERM)` with timestamp
2. **Stop accepting new work** — close HTTP listeners, stop consuming from queues, reject new connections
3. **Log** `INFO: Stopped accepting new connections`
4. **Mark health endpoint as draining** — return 503 from `/ready` so load balancers stop routing traffic
5. **Drain in-flight work** — let active requests complete, wait for in-progress operations to finish
6. **Log** `INFO: Drained N in-flight requests in Xms`
7. **Close external connections** — database pools, message queue connections, WebSocket connections
8. **Log** `INFO: Closed external connections`
9. **Flush logs** — ensure all buffered log entries are written
10. **Log** `INFO: Shutdown complete, exiting`
11. **Exit** with code 0

## Shutdown timeout

Mandate a maximum shutdown window (configurable, default 30 seconds). If cleanup doesn't complete within the window:
1. **Log** `WARN: Shutdown timeout (30s) exceeded, force exiting`
2. Force-close remaining connections
3. Exit with code 1

## Shutdown hook registry

Provide a registration mechanism where modules register their cleanup functions during initialization. The shutdown sequence calls these hooks in reverse registration order (last registered = first cleaned up).
