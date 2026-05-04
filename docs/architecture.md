# Architecture

## High-level data flow

```
producers ─POST /signals─►  FastAPI (rate-limited, async)
                                 │
                                 │  enqueue (non-blocking)
                                 ▼
                           bounded asyncio.Queue (50 000)
                                 │
                                 │  drained by N async workers
                                 ▼
       ┌────────────┬────────────┴────────────┬─────────────┐
       ▼            ▼                         ▼             ▼
   MongoDB      PostgreSQL                  Redis        TimescaleDB
   raw_signals  work_items + rca            dedup keys   signal_metrics
   (audit log)  signal_links                live feed    (hypertable)
                (transactional)             metrics
```

## Storage roles

| Store     | Holds                                       | Why this store                                                                  |
|-----------|---------------------------------------------|---------------------------------------------------------------------------------|
| MongoDB   | Raw signal payloads, append-only            | Schemaless; arbitrary JSON; aggregation pipeline; cheap to scale write-heavy.   |
| Postgres  | `work_items`, `rca`, `signal_links`         | ACID transactions for lifecycle state; FK from RCA → work item; check constraints for RCA fields (defense in depth). |
| Postgres + TimescaleDB | `signal_metrics`              | One container, two roles. Hypertable on `bucket` gives time-partitioned writes and fast time-window queries with regular SQL. |
| Redis     | Dedup keys, live feed ZSET, throughput hash | Sub-millisecond `SET NX EX` for atomic dedup; ZRANGEBYSCORE for severity-ordered UI; HMSET for metrics polling. |

## Patterns

### Strategy — alerting

`backend/app/patterns/alerting.py`

```python
ALERT_MAP = {
    ComponentType.RDBMS: P0Alerter(),  # PagerDuty + Slack #sev0
    ComponentType.MCP:   P0Alerter(),
    ComponentType.API:   P1Alerter(),  # Slack #alerts
    ComponentType.QUEUE: P1Alerter(),
    ComponentType.CACHE: P2Alerter(),  # Slack #noise
    ComponentType.NOSQL: P2Alerter(),
}
```

The Strategy makes routing changes a one-line edit (rebind a key in the map).
`Alerter.dispatch` is the only contract. Today the alerters log structured
JSON; in production each subclass swaps the body for a PagerDuty webhook,
Slack chat.postMessage, etc., with no caller-side change.

### State — incident lifecycle

`backend/app/patterns/states.py`

```
            ┌──────────┐    ┌─────────────────┐    ┌────────────┐    ┌─────────┐
   create ──►   OPEN   ├───►  INVESTIGATING   ├───►  RESOLVED   ├───►  CLOSED │
            └────┬─────┘    └────────┬────────┘    └─────┬──────┘    └─────────┘
                 │                   │                   │
                 ▲                   ▲                   │
                 │                   │  premature?       │  RCA gate
                 └───────────────────┘                   │  (validate)
                                                         │
                                                         ▼  rejected
                                                  RCARequiredError /
                                                  RCAIncompleteError
```

- Each state class implements only the transitions that are legal *from* it.
  All other transitions raise `IllegalTransitionError`.
- The CLOSE transition out of `ResolvedState` calls `rca_validator.validate(rca)`
  *first*, then computes `mttr_seconds = end_time - start_time`. The gate is on
  the state object itself, so any caller (REST API, scripts, future cron) goes
  through it — the API is just one entry point.
- `ClosedState` has no legal outbound transitions; it is terminal.

### Why the gate lives in the state object

A naive design would put the RCA check in the API endpoint. That fails the
moment a second caller exists (script, cron, gRPC, Kafka consumer). Putting
the check in `ResolvedState.to_closed` makes it impossible to bypass: every
transition flows through `states.transition(work_item, target, rca)`.

## Concurrency model

- The API is a single uvicorn worker running an asyncio event loop. All I/O is
  awaitable; nothing CPU-bound runs in the request path.
- Ingestion is decoupled by the bounded queue (see `docs/backpressure.md`).
- 8 worker tasks (`WORKER_COUNT` env var) drain the queue cooperatively.
- The dedup race is solved by Redis `SET NX EX 10`: at most one worker wins
  the claim per `(component_id, 10-second window)`. Losers attach to the
  existing work item via `signal_count` increment + `signal_links` insert.

## Failure modes and resilience

| Failure                         | Mitigation                                                           |
|---------------------------------|----------------------------------------------------------------------|
| Postgres slow / blip            | `tenacity` exponential backoff (5 attempts) on each repo write.      |
| Mongo write failure             | Logged, signal counted as dropped at the worker level (loop continues).|
| Redis dedup key TTL expires mid-burst | New SET NX EX claim; a fresh work item is created. Acceptable. |
| Backend crash                   | Queue is in-memory; in-flight signals lost. Production fix: Redis Streams or Kafka (see backpressure.md). |
| Backend OOM under sustained 10k/sec | Bounded queue + 503 backpressure prevents OOM by design.        |
| Bad signal payload              | Pydantic validation rejects with 422 before the queue is touched.    |

## Observability

- All logs are structured JSON via `structlog` (loki-friendly).
- `/metrics` exposes queue + throughput JSON for Prometheus scraping (custom exporter is a 20-line wrapper).
- `/health` returns 503 if any of the 3 DBs is unreachable, suitable for k8s readiness probes.
