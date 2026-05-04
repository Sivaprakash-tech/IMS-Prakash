"""Locust load test for /signals at high rate.

Usage from inside the backend container:
    locust -f /app/scripts/locustfile.py --host=http://backend:8000

Or via docker compose with the load profile:
    docker compose --profile load up locust
    open http://localhost:8089

In the Locust UI, dial in users (e.g. 1000) and spawn rate (e.g. 200/sec).
With wait_time=between(0.1, 0.1), 1000 users => ~10000 req/sec target.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone

from locust import HttpUser, between, task

COMPONENT_TYPES = ["CACHE", "RDBMS", "API", "MCP", "QUEUE", "NOSQL"]
SEVERITIES = ["INFO", "WARN", "ERROR", "CRITICAL"]
COMPONENTS_BY_TYPE: dict[str, list[str]] = {
    "CACHE": [f"CACHE_CLUSTER_{i:02d}" for i in range(1, 6)],
    "RDBMS": [f"RDBMS_PRIMARY_{i:02d}" for i in range(1, 4)],
    "API":   [f"API_GATEWAY_{i:02d}" for i in range(1, 6)],
    "MCP":   [f"MCP_HOST_{i:02d}" for i in range(1, 4)],
    "QUEUE": [f"QUEUE_BROKER_{i:02d}" for i in range(1, 4)],
    "NOSQL": [f"NOSQL_NODE_{i:02d}" for i in range(1, 5)],
}


class IngestUser(HttpUser):
    # Tight wait => high throughput per user. 0.1s + 0.1s = 10 req/sec/user.
    wait_time = between(0.1, 0.1)

    @task(20)
    def post_signal(self) -> None:
        ctype = random.choice(COMPONENT_TYPES)
        cid = random.choice(COMPONENTS_BY_TYPE[ctype])
        payload = {
            "component_id": cid,
            "component_type": ctype,
            "severity": random.choices(
                SEVERITIES, weights=[10, 25, 40, 25], k=1
            )[0],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "trace_id": str(uuid.uuid4()),
                "error": "synthetic load",
                "latency_ms": random.randint(10, 5000),
            },
        }
        with self.client.post(
            "/signals", json=payload, catch_response=True, name="POST /signals"
        ) as resp:
            if resp.status_code in (202, 503):
                # 503 is expected under sustained backpressure; do not fail.
                resp.success()
            else:
                resp.failure(f"unexpected {resp.status_code}: {resp.text[:200]}")

    @task(1)
    def health(self) -> None:
        self.client.get("/health", name="GET /health")
