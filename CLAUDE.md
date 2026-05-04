# Incident Management System (IMS) — Claude Code Build Context

## Mission

Build a production-grade IMS in a single repo within 1-2 hours. The user is a senior SRE/DevOps engineer (code-allergic, infra-fluent). You write the code. He runs the containers and verifies. No hand-holding on Docker, networking, git, or CLI tooling. He knows that cold.

**Deadline: ship a working `docker compose up` demo today.**

---

## The original assignment (decoded)

A take-home that builds a resilient IMS to ingest error signals, deduplicate, manage incident lifecycle, and force RCA before closure.

### Hard requirements (rubric-driving)

1. **Ingest 10,000 signals/sec** without crashing if the persistence layer is slow → bounded async queue, backpressure, async workers.
2. **Debounce** duplicate signals: 100 signals for the same `component_id` within 10 seconds = ONE work item, but all 100 raw signals linked to it.
3. **Four storage layers**, each with a clear job:
   - **MongoDB** — raw signal payloads (audit log, append-only, queryable).
   - **PostgreSQL** — work items + RCA records (transactional source of truth).
   - **Redis** — real-time dashboard cache + dedup keys with TTL.
   - **TimescaleDB extension on Postgres** — timeseries aggregations (signals/min). One Postgres container, two roles.
4. **Two design patterns, explicitly named in code:**
   - **Strategy pattern** for alerting (P0 for RDBMS failure, P1 for API, P2 for cache).
   - **State pattern** for work item lifecycle: `OPEN → INVESTIGATING → RESOLVED → CLOSED`.
5. **Mandatory RCA gate:** transition to `CLOSED` MUST fail if RCA object is missing or has empty `fix_applied` / `prevention` / `category`. Validation lives inside the State object, not just the API layer.
6. **Auto-compute MTTR** on closure: `end_time - start_time` where `start_time` = first signal timestamp, `end_time` = RCA submission time.
7. **Frontend dashboard:** Live feed sorted by severity, incident detail page (raw signals from Mongo), RCA form (start/end datetime, root cause dropdown, fix applied textarea, prevention textarea).
8. **Resilience:**
   - Token-bucket rate limiter on `/signals` endpoint.
   - `/health` endpoint.
   - Throughput log every 5 seconds (signals/sec to stdout).
   - Retry decorator on DB writes (`tenacity`).
   - Unit tests for RCA validator + state transitions.
9. **Submission artifacts:**
   - Single repo with `/backend`, `/dashboard`, `/scripts`, `/docs`.
   - `README.md` with architecture diagram, setup instructions, **backpressure section**.
   - `docker-compose.yml` — single command brings everything up.
   - Sample data script simulating RDBMS outage → MCP failure cascade.
   - `/docs/prompts/` folder containing every Claude Code prompt used (this file goes there too).

---

## Tech stack (locked in)

| Layer | Pick | Reason |
|---|---|---|
| Backend | **FastAPI 0.115+** (Python 3.11) | Async-native, `asyncio.Queue` integrates cleanly. |
| Raw signals | **MongoDB 7** | Schemaless JSON dumps, aggregation pipeline for queries. |
| Transactional | **PostgreSQL 16** with **TimescaleDB extension** | Real ACID + hypertables for aggregations. One container, two jobs. |
| Cache | **Redis 7** | Sorted sets for severity-ordered live feed, TTL keys for dedup window. |
| Frontend | **Streamlit** | User is code-allergic. Streamlit = Python only, no HTML/CSS/JS. README justifies the deviation from "React/Vue/HTMX". |
| Load gen | **Locust** | Web UI, demo-friendly. |
| Tests | **pytest + pytest-asyncio + httpx** | Standard async stack. |
| Rate limiter | **slowapi** | Drop-in for FastAPI. |
| Retries | **tenacity** | Decorator-based, clean. |

**Do NOT introduce:** Kafka, RabbitMQ, Kubernetes, Helm, Terraform, React, Vue, HTMX, Celery. None of these earn points for this rubric, and all of them burn time.

---

## Repo structure to create

```
ims/
├── docker-compose.yml
├── README.md
├── .env.example
├── .gitignore
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app, /signals, /health, /incidents, /rca
│   │   ├── config.py               # env vars, settings
│   │   ├── ingestion.py            # rate limiter, queue producer
│   │   ├── workers.py              # async worker pool, debouncer, throughput logger
│   │   ├── storage/
│   │   │   ├── __init__.py
│   │   │   ├── mongo.py            # raw signal writes
│   │   │   ├── postgres.py         # work items, RCA, MTTR
│   │   │   └── redis_cache.py      # dashboard state, dedup keys
│   │   ├── patterns/
│   │   │   ├── __init__.py
│   │   │   ├── alerting.py         # Strategy: P0Alerter, P1Alerter, P2Alerter
│   │   │   └── states.py           # State: Open, Investigating, Resolved, Closed
│   │   ├── models.py               # SQLAlchemy + Pydantic schemas
│   │   └── rca_validator.py        # mandatory RCA logic
│   └── tests/
│       ├── test_states.py
│       ├── test_rca_validator.py
│       └── test_debouncer.py
├── dashboard/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py                      # Streamlit, 3 tabs: Live / Detail / RCA
├── scripts/
│   ├── simulate_outage.py          # RDBMS failure → MCP cascade
│   └── locustfile.py               # 10k/sec load test
├── docs/
│   ├── architecture.md
│   ├── backpressure.md
│   └── prompts/
│       └── claude_code_session.md  # log of every Claude Code prompt used
└── init-db/
    └── 01_schema.sql               # work_items, rca, signal_links tables + Timescale hypertables
```

---

## Critical implementation details (don't miss these)

### Ingestion API contract

```
POST /signals
Body:
{
  "component_id": "CACHE_CLUSTER_01",
  "component_type": "CACHE" | "RDBMS" | "API" | "MCP" | "QUEUE" | "NOSQL",
  "severity": "INFO" | "WARN" | "ERROR" | "CRITICAL",
  "timestamp": "2026-05-02T10:00:00Z",
  "payload": { ... arbitrary error data ... }
}
Returns: 202 Accepted (NEVER blocks on DB writes)
Rate limit: 1000 req/sec per IP via slowapi
```

### Debouncer logic (the core trick)

- Redis key: `dedup:{component_id}` with 10-second TTL.
- Value: the `work_item_id` of the open incident.
- On signal arrival:
  - If key exists, append `signal_id` to `signal_links` table for that work item.
  - If key does NOT exist, SET key with NX flag (atomic), create work item in Postgres, fire Strategy alerter.
- Use `SET key value NX EX 10`. Atomic check-and-set prevents race conditions when two workers see "no key" simultaneously.

### State pattern enforcement

```python
class ResolvedState(State):
    def close(self, work_item):
        rca_validator.validate(work_item.rca)  # raises RCARequired or RCAIncomplete
        work_item.state = ClosedState()
        work_item.end_time = datetime.utcnow()
        work_item.mttr_seconds = (work_item.end_time - work_item.start_time).total_seconds()
```

The validator MUST live in the State object, not the API. Anyone calling `work_item.transition_to('CLOSED')` from anywhere (API, script, future cron) gets the same protection.

### Strategy alerter

```python
ALERT_MAP = {
    "RDBMS": P0Alerter(),    # PagerDuty + Slack #sev0
    "MCP":   P0Alerter(),
    "API":   P1Alerter(),    # Slack #alerts
    "QUEUE": P1Alerter(),
    "CACHE": P2Alerter(),    # Slack #noise
    "NOSQL": P2Alerter(),
}
```

In dev, alerters just log structured JSON. README mentions production swap to PagerDuty/Slack webhooks.

### Backpressure (README must explain this, graded)

- **Bounded queue:** `asyncio.Queue(maxsize=50_000)`.
- **At 80% full:** API returns `503 Service Unavailable` with `Retry-After: 5` header. Increment dropped-signal counter.
- **Throughput logger** prints every 5 seconds: `signals_in_per_sec`, `signals_processed_per_sec`, `queue_depth`, `queue_pct_full`, `dropped_count`.
- **Production upgrade path** (mention in README): swap `asyncio.Queue` for Redis Streams or Kafka for durability across restarts.

---

## Setup and run flow (what the user will execute)

```bash
# Bootstrap (one-time)
git clone <repo> && cd ims
cp .env.example .env

# Bring everything up
docker compose up --build

# Seed sample data
docker compose exec backend python /app/scripts/simulate_outage.py

# Open dashboards
# Streamlit:    http://localhost:8501
# FastAPI docs: http://localhost:8000/docs
# Locust:       http://localhost:8089

# Run load test
docker compose exec backend locust -f /app/scripts/locustfile.py --host=http://backend:8000

# Run unit tests
docker compose exec backend pytest -v
```

**Ports (chosen to avoid common collisions):**
- 8000  FastAPI
- 8501  Streamlit
- 8089  Locust
- 5433  Postgres
- 27018 MongoDB
- 6380  Redis

---

## Build order (Claude Code execution plan)

Claude Code should build in this exact order. Each step ends with a working checkpoint.

1. **Skeleton + docker-compose** — all containers boot green, even if backend is just `/health`.
2. **Postgres schema + Mongo init** — `init-db/01_schema.sql` runs on container start.
3. **Models + storage adapters** — Mongo writer, Postgres CRUD, Redis cache helpers.
4. **State + Strategy patterns** — pure Python classes, fully unit-tested before wiring.
5. **RCA validator + tests** — pytest passes for all transition + RCA scenarios.
6. **Ingestion API + queue + workers + debouncer** — load test must hit 10k/sec without 5xx errors.
7. **REST endpoints** — `/incidents`, `/incidents/{id}`, `/incidents/{id}/signals`, `/rca`.
8. **Streamlit dashboard** — three tabs, polls backend every 2s.
9. **Locust + simulate_outage script** — proves backpressure works.
10. **README + architecture diagram + backpressure doc + prompts log.**

**Commit after every step** with a clear message: `feat: add state pattern with RCA gate`, `feat: ingestion API with 50k bounded queue`, etc. Graders check git history.

---

## Pitfalls Claude Code must avoid

- `await db.write(signal)` inside the request handler. Wrong. Push to queue, return 202.
- Single shared dedup dict instead of Redis. Wrong. Won't survive a restart, won't scale beyond one worker.
- RCA validation only in the API endpoint. Wrong. Must be in State object.
- `asyncio.Queue()` without `maxsize`. Wrong. That's an unbounded memory leak waiting to OOM.
- Catching all exceptions in the worker loop with bare `except:`. Wrong. Use `except Exception as e: log.exception(); continue` so the worker doesn't die silently.
- MTTR computed in Python from `datetime.now()` of two different machines. Wrong. Use Postgres `now() - start_time` or always UTC from the same source.
- Forgetting to commit prompts to `/docs/prompts/`. Free 10% of the score.

---

## Definition of done

- [ ] `docker compose up` brings all 5 containers green.
- [ ] `curl -X POST localhost:8000/signals -d '...'` returns 202.
- [ ] Locust at 10k/sec runs for 60 seconds, zero 5xx, queue stays under 80%.
- [ ] Dashboard at localhost:8501 shows live incidents sorted by severity.
- [ ] Cannot close a work item without complete RCA (returns 400 with clear error).
- [ ] MTTR auto-populated on closure.
- [ ] `pytest` passes all tests in `backend/tests/`.
- [ ] `simulate_outage.py` produces RDBMS to MCP cascade visible in dashboard.
- [ ] README has architecture diagram, setup, backpressure section.
- [ ] All Claude Code prompts saved to `/docs/prompts/`.
- [ ] Git history shows incremental commits with meaningful messages.

---

## Style preferences (user is senior SRE)

- Production-safe defaults. No hardcoded secrets. All config via env vars.
- Structured logging (JSON), easy to grep, easy to ship to Loki later.
- `/health` returns 200 only when all 3 databases are reachable.
- Type hints on every function. `mypy --strict` should pass.
- Comments explain **why**, not what. Code says what.
- No emojis in code or logs. No marketing fluff in docstrings.

---

## What Claude Code should do FIRST when invoked

1. Confirm the target directory is empty or only contains this `CLAUDE.md`.
2. Generate the entire repo structure above in one pass.
3. Print the exact commands the user should run to verify each checkpoint.
4. Stop after every major step and let the user run `docker compose up` to validate.
5. Save this CLAUDE.md and every subsequent prompt the user issues into `/docs/prompts/claude_code_session.md`.

---

## Permissions

You have full permissions to the current folder only to install official/legitimate packages automatically, but not to uninstall packages or delete files/folders.

GO.
