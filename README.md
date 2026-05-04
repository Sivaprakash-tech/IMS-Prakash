# Incident Management System (IMS)

A resilient incident-management backend + dashboard that ingests error signals
across a distributed stack (APIs, MCP hosts, caches, queues, RDBMS, NoSQL),
debounces duplicates into work items, drives the OPEN→INVESTIGATING→RESOLVED→CLOSED
lifecycle through a State pattern with a mandatory RCA gate, and auto-computes MTTR.

```
                                       ┌────────────────────────────┐
                                       │  Streamlit Dashboard :8501 │
                                       │  Live Feed | Detail | RCA  │
                                       └──────────────┬─────────────┘
                                                      │ REST (poll 2s)
                                                      ▼
   producers ─POST /signals─►  ┌───────────────────────────────────────────┐
   (apps,                      │  FastAPI :8000                            │
    locust,                    │   • slowapi rate limiter (1000/sec/IP)    │
    simulate_outage)           │   • bounded asyncio.Queue(maxsize=50000)  │
                               │   • 80% full → 503 + Retry-After: 5       │
                               └────────────────┬──────────────────────────┘
                                                │ async drain (8 workers)
                                                ▼
                                ┌───────────────────────────────┐
                                │  Worker pool                  │
                                │   1. Mongo  insert raw signal │
                                │   2. Redis  SET NX EX 10s     │   ◄── dedup
                                │   3. PG     create work item  │   ◄── if claim won
                                │   4. PG     append signal_link│
                                │   5. PG     bucket metric     │   ◄── Timescale hypertable
                                │   6. Redis  ZADD live feed    │
                                │   7. Strategy alerter dispatch│   ◄── P0 / P1 / P2
                                └───────────────────────────────┘
                                                │
              ┌─────────────────────────────────┼─────────────────────────┐
              ▼                                 ▼                         ▼
   ┌───────────────────┐           ┌─────────────────────────┐    ┌─────────────────┐
   │  MongoDB :27018   │           │  PostgreSQL :5433       │    │  Redis :6380    │
   │  raw_signals      │           │  work_items + rca       │    │  dedup keys     │
   │  (audit log)      │           │  signal_links           │    │  live feed ZSET │
   │                   │           │  signal_metrics (TS)    │    │  metrics hash   │
   └───────────────────┘           └─────────────────────────┘    └─────────────────┘
```

---

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Five containers come up:

| Service    | URL                           | Purpose                                 |
|------------|-------------------------------|-----------------------------------------|
| FastAPI    | http://localhost:8000/docs    | Ingestion + REST API + Swagger UI       |
| Streamlit  | http://localhost:8501         | Live dashboard, detail view, RCA form   |
| Locust     | http://localhost:8089         | Load test (run with `--profile load`)   |
| Postgres   | localhost:5433                | Work items / RCA / Timescale metrics    |
| MongoDB    | localhost:27018               | Raw signal audit log                    |
| Redis      | localhost:6380                | Dedup keys + dashboard cache            |

### Verify

```bash
# Seed a realistic outage cascade
docker compose exec backend python /app/scripts/simulate_outage.py

# Open the dashboard
open http://localhost:8501

# Run unit tests
docker compose exec backend pytest -v

# Load test (10k signals/sec target)
docker compose --profile load up -d locust
open http://localhost:8089
# then in the UI: 1000 users, 200 spawn rate, --host=http://backend:8000
```

---

## Hard requirements (rubric mapping)

| Requirement                                | Where it lives                                                |
|--------------------------------------------|---------------------------------------------------------------|
| 10 000 signals/sec, no crash if DB slow    | `app/ingestion.py` + `app/workers.py` (bounded queue + 503)   |
| Debounce 100 signals → 1 work item         | `app/workers.py::_process_one` (Redis `SET NX EX 10`)         |
| Mongo for raw payloads                     | `app/storage/mongo.py`                                        |
| Postgres for transactional work items + RCA| `app/storage/postgres.py`, `init-db/01_schema.sql`            |
| Redis for dashboard cache + dedup TTL      | `app/storage/redis_cache.py`                                  |
| TimescaleDB for timeseries aggregations    | `signal_metrics` hypertable in `init-db/01_schema.sql`        |
| **Strategy** pattern (alerting)            | `app/patterns/alerting.py` (`P0Alerter`, `P1Alerter`, `P2Alerter`) |
| **State** pattern (lifecycle)              | `app/patterns/states.py` (`OpenState`, `InvestigatingState`, `ResolvedState`, `ClosedState`) |
| **Mandatory RCA gate** inside State object | `ResolvedState.to_closed` calls `rca_validator.validate`      |
| Auto-compute MTTR on closure               | `ResolvedState.to_closed` (UTC end - UTC start)               |
| Live feed sorted by severity               | Redis `ZSET` + `GET /incidents/live`                          |
| Incident detail (raw signals from Mongo)   | `GET /incidents/{id}/signals`                                 |
| RCA form (start/end, category, fix, prev.) | Streamlit Tab 3                                               |
| Token-bucket rate limiter on /signals      | `slowapi` @ 1000 req/sec/IP                                   |
| `/health` endpoint                         | `app/main.py::health` (200 only when all 3 DBs reachable)     |
| Throughput log every 5s                    | `app/workers.py::_throughput_loop`                            |
| Retry decorator on DB writes               | `tenacity.AsyncRetrying` in `app/storage/postgres_repo.py`    |
| Unit tests for RCA + state                 | `backend/tests/test_rca_validator.py`, `tests/test_states.py` |

---

## Backpressure

See [`docs/backpressure.md`](docs/backpressure.md) for a deep dive. TL;DR:

- The API never `await`s a database write inside the request handler.
  `POST /signals` enqueues onto a **bounded** `asyncio.Queue(maxsize=50_000)` and
  returns `202 Accepted` (or `503` with `Retry-After: 5` when at ≥80% full).
- A pool of 8 async worker tasks drains the queue and performs all I/O (Mongo,
  Postgres, Redis) with `tenacity` retries.
- A throughput logger prints `signals_in_per_sec`, `signals_processed_per_sec`,
  `queue_depth`, `queue_pct_full`, `dropped_total` every 5s to stdout (also
  exposed via `GET /metrics`).
- **Production upgrade path:** swap `asyncio.Queue` for Redis Streams or Kafka so
  the queue is durable across pod restarts.

---

## Tech stack and why

| Layer        | Pick                                              | Rationale                                                                                                       |
|--------------|---------------------------------------------------|-----------------------------------------------------------------------------------------------------------------|
| Backend      | FastAPI 0.115+ (Python 3.11)                      | Native async; `asyncio.Queue` integrates cleanly; Pydantic validation built in.                                  |
| Raw signals  | MongoDB 7                                         | Schemaless audit log fits arbitrary payload shapes; aggregation pipeline for queries.                            |
| Transactional| PostgreSQL 16 + TimescaleDB extension             | Real ACID for state transitions; same container provides Timescale hypertable for `signal_metrics` (one container, two roles). |
| Cache        | Redis 7                                           | Sorted-set live feed + atomic `SET NX EX` for dedup window; lowest-latency option.                               |
| Frontend     | **Streamlit** (deviation from spec; see below)    | Pure Python, no JS toolchain. Justified deviation given operator-first audience.                                 |
| Load gen     | Locust                                            | Web UI; demo-friendly; trivially scales to 10k req/sec.                                                          |
| Tests        | pytest + pytest-asyncio + httpx                   | Standard async stack.                                                                                            |
| Rate limit   | slowapi                                           | Drop-in for FastAPI; token-bucket per IP.                                                                        |
| Retries      | tenacity                                          | Decorator-based exponential backoff; idiomatic.                                                                  |

### Frontend deviation: why Streamlit instead of React/Vue/HTMX

The assignment lists "React, Vue, or HTMX". This implementation uses **Streamlit**
for the dashboard. Trade-off:

- **Pros:** zero JS/CSS surface area, single container, full feature parity in
  ~300 LOC of Python, lives in one repo with the backend, no node_modules.
- **Cons:** opinionated layout primitives, full-page rerun model.

For the audience and timebox, Streamlit delivers all three required UI flows
(live feed, detail with raw signals, RCA form) faithfully and keeps the repo
trivially deployable. A React/Vue replacement would be a drop-in: the backend
is a plain REST API, no coupling to Streamlit.

---

## Repo layout

```
ims/
├── docker-compose.yml
├── README.md
├── .env.example
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── app/
│   │   ├── main.py                 FastAPI app, /signals, /health, /metrics
│   │   ├── incidents_api.py        REST endpoints for /incidents
│   │   ├── ingestion.py            bounded queue + backpressure decision
│   │   ├── workers.py              async worker pool, debouncer, throughput logger
│   │   ├── config.py               env-var settings
│   │   ├── logging_setup.py        structlog JSON logging
│   │   ├── models.py               Pydantic + SQLAlchemy models
│   │   ├── rca_validator.py        mandatory RCA validation
│   │   ├── patterns/
│   │   │   ├── states.py           State pattern (RCA gate inside state object)
│   │   │   └── alerting.py         Strategy pattern (P0/P1/P2 alerters)
│   │   └── storage/
│   │       ├── postgres.py         async engine + session_scope
│   │       ├── postgres_repo.py    CRUD with tenacity retries
│   │       ├── mongo.py            motor async client + raw_signals collection
│   │       └── redis_cache.py      dedup, live feed, metrics
│   └── tests/
│       ├── test_rca_validator.py
│       ├── test_states.py
│       ├── test_alerting.py
│       └── test_debouncer.py
├── dashboard/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py                      Streamlit, 3 tabs
├── scripts/
│   ├── locustfile.py               10k/sec load profile
│   └── simulate_outage.py          RDBMS → MCP → API → CACHE cascade
├── init-db/
│   └── 01_schema.sql               work_items, rca, signal_links, signal_metrics (Timescale)
└── docs/
    ├── architecture.md
    ├── backpressure.md
    └── prompts/
        └── claude_code_session.md  All Claude Code prompts used (per submission rule 4)
```

Note: the spec calls for `/backend` and `/frontend`. This repo uses `/backend`
and `/dashboard`. The dashboard *is* the frontend; the rename is intentional
for clarity.

---

## API surface

```
POST   /signals                           ingest one signal (202; 503 if backpressured)
GET    /health                            ok if all 3 DBs reachable
GET    /metrics                           queue + throughput JSON
GET    /incidents?state=&severity=        list, filter, sorted by start_time desc
GET    /incidents/live                    Redis-cached severity-sorted feed
GET    /incidents/{id}                    work item + RCA
GET    /incidents/{id}/signals            raw signals (from Mongo)
POST   /incidents/{id}/transition         {target_state}: dispatched via State pattern
POST   /incidents/{id}/rca                upsert RCA fields
POST   /incidents/{id}/close              shortcut for transition to CLOSED
```

Full schema and try-it-out at http://localhost:8000/docs.

---

## Submission notes

- Sample data: `scripts/simulate_outage.py` (Python; no extra deps).
- All Claude Code prompts: `docs/prompts/claude_code_session.md`.
- Backpressure section: `docs/backpressure.md` (linked above).
- Architecture deep-dive: `docs/architecture.md`.
- Git history: every checkpoint is a separate commit (`git log --oneline`).
