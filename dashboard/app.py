 from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000").rstrip("/")
REFRESH_SECONDS = int(os.environ.get("DASHBOARD_REFRESH_SECONDS", "2"))

SEVERITY_ORDER = {"CRITICAL": 4, "ERROR": 3, "WARN": 2, "INFO": 1}
SEVERITY_BADGE = {
    "CRITICAL": ":red[CRITICAL]",
    "ERROR": ":orange[ERROR]",
    "WARN": ":violet[WARN]",
    "INFO": ":blue[INFO]",
}
STATE_BADGE = {
    "OPEN": ":red[OPEN]",
    "INVESTIGATING": ":orange[INVESTIGATING]",
    "RESOLVED": ":violet[RESOLVED]",
    "CLOSED": ":green[CLOSED]",
}
ROOT_CAUSE_CATEGORIES = [
    "INFRASTRUCTURE",
    "NETWORK",
    "CODE_DEFECT",
    "CONFIG",
    "CAPACITY",
    "DEPENDENCY",
    "HUMAN_ERROR",
    "SECURITY",
    "UNKNOWN",
]

st.set_page_config(page_title="IMS Dashboard", layout="wide")

# ---------- Sidebar ----------
with st.sidebar:
    st.header("Controls")
    auto_refresh = st.toggle("Auto-refresh", value=True)
    st.caption(f"Backend: `{BACKEND_URL}`")
    if st.button("Refresh now"):
        st.rerun()

if auto_refresh:
    st_autorefresh(interval=REFRESH_SECONDS * 1000, key="auto")

# ---------- Helpers ----------
def api_get(path: str, **params: Any) -> Any:
    return requests.get(f"{BACKEND_URL}{path}", params=params).json()

def api_post(path: str, json=None):
    r = requests.post(f"{BACKEND_URL}{path}", json=json)
    return r.status_code, r.json()

def fmt_dt(s):
    return datetime.fromisoformat(s.replace("Z","+00:00")).strftime("%Y-%m-%d %H:%M") if s else "-"

def fmt_mttr(sec):
    return f"{sec:.1f}s" if sec else "-"

# ---------- Header ----------
st.title("Incident Management System")

health = api_get("/health")
healthy = health.get("status") == "ok"

hc1, hc2, hc3, hc4, hc5 = st.columns(5)

# ✅ Updated status indicator
hc1.markdown("🟢 **Backend OK**" if healthy else "🔴 **Backend DOWN**")

metrics = api_get("/metrics")
q = metrics.get("queue", {})
t = metrics.get("throughput", {})

hc2.metric("Queue depth", q.get("queue_depth", 0))
hc3.metric("Queue % full", f"{float(q.get('queue_pct_full', 0))*100:.1f}%")
hc4.metric("Signals/sec", t.get("signals_in_per_sec", 0))
hc5.metric("Dropped", q.get("dropped_total", 0))

# ---------- NEW: Throughput Graph ----------
st.subheader("Throughput (last window)")

try:
    df = pd.DataFrame([{
        "in": float(t.get("signals_in_per_sec", 0)),
        "processed": float(t.get("signals_processed_per_sec", 0))
    }])
    st.line_chart(df)
except Exception:
    st.info("No throughput yet")

# ---------- Tabs ----------
tab_live, tab_closed, tab_detail, tab_rca = st.tabs(
    ["Live Feed", "Closed Incidents", "Incident Detail", "RCA Form"]
)

# ---------- Live Feed ----------
with tab_live:
    incidents = api_get("/incidents")

    if not incidents:
        st.info("No incidents yet")
    else:
        df = pd.DataFrame(incidents)
        st.dataframe(df)

# ---------- NEW: Closed Incidents ----------
with tab_closed:
    st.subheader("Closed incidents")

    try:
        incidents = api_get("/incidents", state="CLOSED", limit=100)
    except:
        incidents = []

    if not incidents:
        st.info("No closed incidents.")
    else:
        rows = []
        for i in incidents:
            rows.append({
                "ID": i["id"],
                "Component": i["component_id"],
                "Severity": i["severity"],
                "MTTR": fmt_mttr(i.get("mttr_seconds")),
                "Closed At": fmt_dt(i.get("end_time")),
            })
        st.dataframe(pd.DataFrame(rows))

# ---------- Detail ----------
with tab_detail:
    wid = st.text_input("Work item ID")
    if wid:
        data = api_get(f"/incidents/{wid}")
        st.json(data)

# ---------- RCA ----------
with tab_rca:
    wid = st.text_input("Work item ID (RCA)")
    if wid:
        category = st.selectbox("Category", ROOT_CAUSE_CATEGORIES)
        fix = st.text_area("Fix")
        prev = st.text_area("Prevention")

        if st.button("Submit RCA"):
            payload = {
                "root_cause_category": category,
                "fix_applied": fix,
                "prevention": prev,
                "rca_start_time": datetime.now(timezone.utc).isoformat(),
                "rca_end_time": datetime.now(timezone.utc).isoformat()
            }
            api_post(f"/incidents/{wid}/rca", payload)
            st.success("RCA submitted")
