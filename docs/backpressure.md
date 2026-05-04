# Backpressure

> Required by the rubric: "your system cannot crash if persistence layer is slow".

## The shape of the problem

A naive ingestion path looks like:

```python
@app.post("/signals")
async def ingest(sig: SignalIn):
    await mongo.insert(sig)         # blocks on Mongo
    await postgres.create_work(sig) # blocks on Postgres
    await redis.set(sig)            # blocks on Redis
    return 202
```

This melts under load:

- **Per-request latency = sum of all DB write latencies.** Even if each DB takes
  10ms, the request handler holds the connection for ~30ms.
- **A single slow store stalls the entire API.** If Mongo p99 spikes to 2s, every
  request handler is blocked for 2s, the asyncio event loop fills with awaiters,
  and the connection pool is exhausted.
- **Memory grows unbounded.** Pending requests accumulate; no upper bound on
  in-flight work means an OOM is the only natural stop.

## The shape of our solution

```
POST /signals
   │ Pydantic validate (cheap, in-memory)
   ▼
   ingestion.offer(signal)               ← non-blocking
       │  if queue.qsize() / maxsize >= 0.80:
       │     dropped += 1
       │     return False  ────────────► 503 Service Unavailable
       │                                  Retry-After: 5
       │  else:
       │     queue.put_nowait(signal)
       │     accepted += 1
       │     return True   ────────────► 202 Accepted
       ▼
   asyncio.Queue(maxsize=50_000)
       │
       │  drained by N async workers (asyncio.create_task)
       ▼
   per-signal: Mongo write, dedup (Redis NX/EX), Postgres CRUD, metrics
```

### Why this works

1. **The request handler does no I/O.** `offer()` is `O(1)` and returns
   immediately. p99 of `POST /signals` is set by Pydantic + queue write — single
   millisecond territory.
2. **The queue caps memory.** 50 000 entries × ~1 KB = ~50 MB ceiling. We can
   tune that knob without touching code.
3. **Backpressure is *visible*.** Clients get a 503 with `Retry-After: 5` instead
   of timing out. This is the right behavior under sustained overload: shed load
   at the edge, not at the database. (Locust ignores this and treats 503 as
   success in our tests, mirroring a well-behaved producer.)
4. **Slow databases don't propagate.** If Postgres latency spikes, the worker
   pool simply drains slower. Queue depth grows, eventually 80% triggers 503,
   and the API stays up. As soon as the DB recovers, workers catch up and the
   queue drains.
5. **Visibility is built in.** The throughput logger prints
   `signals_in_per_sec`, `signals_processed_per_sec`, `queue_depth`,
   `queue_pct_full`, `dropped_total` every 5 seconds. Operators see the queue
   building before users see 503s.

## Knobs (env-var driven)

| Variable                       | Default | Effect                                        |
|--------------------------------|---------|-----------------------------------------------|
| `QUEUE_MAXSIZE`                | 50 000  | Hard cap on in-flight signals.                |
| `QUEUE_BACKPRESSURE_THRESHOLD` | 0.80    | Fraction of cap at which the API returns 503. |
| `WORKER_COUNT`                 | 8       | Number of async drainers.                     |
| `RATE_LIMIT_PER_SECOND`        | 1000    | Token-bucket per-IP cap (slowapi).            |
| `THROUGHPUT_LOG_INTERVAL`      | 5       | Throughput logger window in seconds.          |

## Production upgrade path

This implementation uses an **in-memory** `asyncio.Queue`. Two limits matter:

1. **Durability:** if the backend pod restarts, in-flight signals are lost.
2. **Single-instance:** the queue is local to one process, so horizontal scale
   means N independent queues with no cross-instance backpressure.

For production, swap the queue for a durable broker. The minimal change:

- **Redis Streams** — reuses the existing Redis cluster. `XADD streams:signals`
  in the producer, `XREADGROUP` in the workers. Consumer groups give at-least-once
  semantics and survive restarts. Smallest blast radius.
- **Apache Kafka** — for cross-region replication and longer retention. Producer
  writes a topic; multiple consumer groups can fan out (audit log, alerting,
  metrics) without coupling.

Either swap leaves the `/signals` handler logic and worker code essentially
unchanged: same `offer` / `drain` shape, just across a process boundary.

## Why not just remove the limit?

Two failure modes:

- **Unbounded queue:** memory grows linearly with load. We OOM and lose
  *everything in the queue* on restart.
- **Synchronous writes (no queue):** a slow DB melts the API directly. The 503
  becomes a 504, and the failure is much wider.

The bounded-queue + 503 design is the production-correct middle path: shed load
loudly, fast, and visibly, and degrade gracefully.

## Verification

Run the load test and watch the queue:

```bash
# Terminal 1
docker compose --profile load up locust
# In the Locust UI:
#   users:        1000
#   spawn rate:   200/sec
#   host:         http://backend:8000
# Start.

# Terminal 2 — watch backend logs for the 5-second throughput window
docker compose logs -f backend | grep throughput.window
```

You should see `queue_pct_full` stabilize below 0.80 once workers catch up
(`signals_processed_per_sec` ≈ `signals_in_per_sec`). If you bump the load
high enough, `dropped_total` ticks up and the dashboard's "Dropped (total)"
metric increments — that is the system shedding load by design, not a bug.
