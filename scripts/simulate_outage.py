"""Simulate a real production outage cascade: RDBMS -> MCP -> API.

Story:
  T+0s    RDBMS_PRIMARY_01 starts emitting CRITICAL errors.
  T+5s    Repeated bursts. Same component_id => debouncer batches into ONE work item.
  T+10s   MCP_HOST_01 cannot reach RDBMS, starts paging (P0).
  T+20s   API_GATEWAY_01 cascades to ERROR; users see 5xx.
  T+30s   CACHE warns about stale entries (P2 noise).

Run:
    docker compose exec backend python /app/scripts/simulate_outage.py
"""
from __future__ import annotations

import asyncio
import json
import random
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

BACKEND = "http://localhost:8000"


def post_signal(signal: dict) -> tuple[int, str]:
    req = urllib.request.Request(
        f"{BACKEND}/signals",
        data=json.dumps(signal).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:
        return 0, str(e)


def make(component_id: str, component_type: str, severity: str, payload: dict) -> dict:
    return {
        "component_id": component_id,
        "component_type": component_type,
        "severity": severity,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


def burst(component_id: str, component_type: str, severity: str, count: int, payload_template: dict) -> int:
    sent = 0
    for _ in range(count):
        body = dict(payload_template)
        body["trace_id"] = str(uuid.uuid4())
        code, _ = post_signal(make(component_id, component_type, severity, body))
        if code == 202:
            sent += 1
        time.sleep(0.01)
    return sent


def main() -> None:
    print("=== IMS outage simulator ===")
    print(f"backend: {BACKEND}")

    # Phase 1: RDBMS starts failing.
    print("\n[T+0s] RDBMS_PRIMARY_01 emits 50 CRITICAL signals. Should produce ONE work item (dedup).")
    sent = burst(
        "RDBMS_PRIMARY_01",
        "RDBMS",
        "CRITICAL",
        50,
        {"error": "FATAL: too many connections", "code": "53300"},
    )
    print(f"  sent={sent}/50 (rest may be 503 if backpressured)")

    time.sleep(3)

    print("\n[T+3s] another 30 signals on the SAME component within the dedup window.")
    sent = burst(
        "RDBMS_PRIMARY_01",
        "RDBMS",
        "CRITICAL",
        30,
        {"error": "FATAL: connection refused", "code": "53300"},
    )
    print(f"  sent={sent}/30 — these should ATTACH to the same work item, not create new ones.")

    time.sleep(8)  # Past the 10-second window: should get a new work item if it fires again.

    # Phase 2: MCP cascade.
    print("\n[T+11s] MCP_HOST_01 cascades (cannot reach RDBMS). 25 CRITICAL signals.")
    sent = burst(
        "MCP_HOST_01",
        "MCP",
        "CRITICAL",
        25,
        {"error": "model context provider unreachable", "depends_on": "RDBMS_PRIMARY_01"},
    )
    print(f"  sent={sent}/25 — P0 pager should fire for MCP failure.")

    time.sleep(2)

    # Phase 3: API gateway cascade.
    print("\n[T+13s] API_GATEWAY_01 starts returning 5xx. 40 ERROR signals.")
    sent = burst(
        "API_GATEWAY_01",
        "API",
        "ERROR",
        40,
        {"error": "upstream MCP timeout", "status": 502},
    )
    print(f"  sent={sent}/40 — P1 alert in #alerts.")

    time.sleep(2)

    # Phase 4: cache noise.
    print("\n[T+15s] CACHE_CLUSTER_03 emits stale-entry warnings. 15 WARN signals.")
    sent = burst(
        "CACHE_CLUSTER_03",
        "CACHE",
        "WARN",
        15,
        {"error": "stale cache entries", "ttl_violations": random.randint(50, 500)},
    )
    print(f"  sent={sent}/15 — P2 noise channel.")

    print("\n=== done ===")
    print("Check the dashboard:  http://localhost:8501")
    print("API docs:             http://localhost:8000/docs")
    print("Backend logs:         docker compose logs -f backend")


if __name__ == "__main__":
    main()
