"""IMS Streamlit dashboard.

Three tabs per the spec:
  1. Live Feed — active incidents sorted by severity
  2. Incident Detail — work item + raw signals from Mongo + status controls
  3. RCA Form — start/end pickers, root cause dropdown, fix/prevention
"""
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

st.set_page_config(page_title="IMS Dashboard", layout="wide", initial_sidebar_state="expanded")


# ---------- Sidebar controls ----------

with st.sidebar:
    st.header("Controls")
    auto_refresh = st.toggle("Auto-refresh", value=True, help=f"Refresh every {REFRESH_SECONDS}s")
    st.caption(f"Backend: `{BACKEND_URL}`")
    st.divider()
    if st.button("Refresh now", use_container_width=True):
        st.rerun()

if auto_refresh:
    st_autorefresh(interval=REFRESH_SECONDS * 1000, key="ims_autorefresh")


# ---------- HTTP helpers ----------

def api_get(path: str, **params: Any) -> Any:
    r = requests.get(f"{BACKEND_URL}{path}", params=params, timeout=5)
    r.raise_for_status()
    return r.json()


def api_post(path: str, json: dict[str, Any] | None = None) -> tuple[int, Any]:
    r = requests.post(f"{BACKEND_URL}{path}", json=json, timeout=10)
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text}
    return r.status_code, body


def fmt_dt(s: str | None) -> str:
    if not s:
        return "—"
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return str(s)


def fmt_mttr(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        return f"{seconds/60:.1f}m"
    return f"{seconds/3600:.2f}h"


# ---------- Header ----------

st.title("Incident Management System")

try:
    health = api_get("/health")
    healthy = health.get("status") == "ok"
except Exception as e:
    st.error(f"Cannot reach backend at {BACKEND_URL}: {e}")
    st.stop()

hc1, hc2, hc3, hc4, hc5 = st.columns(5)
hc1.metric("Backend", "OK" if healthy else "DEGRADED")

try:
    metrics = api_get("/metrics")
    q = metrics.get("queue", {}) or {}
    t = metrics.get("throughput", {}) or {}
    hc2.metric("Queue depth", q.get("queue_depth", 0))
    hc3.metric("Queue % full", f"{float(q.get('queue_pct_full', 0))*100:.1f}%")
    hc4.metric("Signals/sec in", t.get("signals_in_per_sec", "—"))
    hc5.metric("Dropped (total)", q.get("dropped_total", 0))
except Exception as e:
    st.warning(f"metrics unavailable: {e}")


tab_live, tab_detail, tab_rca = st.tabs(["Live Feed", "Incident Detail", "RCA Form"])


# ---------- Tab 1: Live Feed ----------

with tab_live:
    st.subheader("Active incidents — sorted by severity")
    fcol1, fcol2 = st.columns([1, 1])
    only_open = fcol1.checkbox("Hide CLOSED", value=True, key="only_open")
    sev_filter = fcol2.multiselect(
        "Severity",
        options=list(SEVERITY_ORDER.keys()),
        default=list(SEVERITY_ORDER.keys()),
        key="sev_filter",
    )

    try:
        incidents = api_get("/incidents", limit=200)
    except Exception as e:
        st.error(f"failed to load incidents: {e}")
        incidents = []

    if only_open:
        incidents = [i for i in incidents if i.get("state") != "CLOSED"]
    if sev_filter:
        incidents = [i for i in incidents if i.get("severity") in sev_filter]
    incidents.sort(
        key=lambda i: (SEVERITY_ORDER.get(i.get("severity", "INFO"), 0), i.get("start_time") or ""),
        reverse=True,
    )

    if not incidents:
        st.info("No incidents match the current filters. Send signals via /signals or run scripts/simulate_outage.py.")
    else:
        rows = []
        for i in incidents:
            rows.append(
                {
                    "ID": i["id"],
                    "Severity": SEVERITY_BADGE.get(i["severity"], i["severity"]),
                    "State": STATE_BADGE.get(i["state"], i["state"]),
                    "Component": i["component_id"],
                    "Type": i["component_type"],
                    "Signals": i["signal_count"],
                    "Started": fmt_dt(i["start_time"]),
                    "MTTR": fmt_mttr(i.get("mttr_seconds")),
                }
            )
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(f"{len(rows)} incidents shown.")


# ---------- Tab 2: Incident Detail ----------

with tab_detail:
    st.subheader("Incident detail")
    wid_input = st.text_input("Work item ID", key="detail_wid")
    if not wid_input.strip().isdigit():
        st.caption("Enter a numeric work item ID above (find one on the Live Feed tab).")
    else:
        wid = int(wid_input.strip())
        try:
            data = api_get(f"/incidents/{wid}")
        except requests.HTTPError as e:
            body = e.response.text if e.response is not None else str(e)
            st.error(f"not found: {body}")
            data = None
        except Exception as e:
            st.error(str(e))
            data = None

        if data:
            wi = data["work_item"]
            rca = data.get("rca")
            cA, cB, cC, cD = st.columns(4)
            cA.markdown(f"**Severity:** {SEVERITY_BADGE.get(wi['severity'], wi['severity'])}")
            cB.markdown(f"**State:** {STATE_BADGE.get(wi['state'], wi['state'])}")
            cC.markdown(f"**Component:** `{wi['component_id']}`")
            cD.markdown(f"**MTTR:** {fmt_mttr(wi.get('mttr_seconds'))}")

            st.write(
                f"**Type:** {wi['component_type']}  |  **Signals:** {wi['signal_count']}  "
                f"|  **Started:** {fmt_dt(wi['start_time'])}  |  **Ended:** {fmt_dt(wi.get('end_time'))}"
            )
            if wi.get("summary"):
                st.info(wi["summary"])

            st.divider()

            st.markdown("##### Lifecycle controls")
            cur = wi["state"]
            tcols = st.columns(4)
            for col, target in zip(tcols, ["OPEN", "INVESTIGATING", "RESOLVED", "CLOSED"]):
                with col:
                    disabled = target == cur
                    if st.button(f"Move to {target}", disabled=disabled, key=f"btn_{wid}_{target}"):
                        code, body = api_post(f"/incidents/{wid}/transition", {"target_state": target})
                        if 200 <= code < 300:
                            st.success(f"moved to {target}")
                            st.rerun()
                        else:
                            st.error(f"transition rejected ({code}): {body}")

            st.divider()

            st.markdown("##### Raw signals (from MongoDB)")
            try:
                sigs = api_get(f"/incidents/{wid}/signals", limit=200)
                if sigs.get("count", 0) == 0:
                    st.info("No raw signals linked yet.")
                else:
                    st.caption(f"{sigs['count']} signals (newest first)")
                    sig_rows: list[dict[str, Any]] = []
                    for s in sigs.get("signals", []):
                        sig_rows.append(
                            {
                                "timestamp": s.get("timestamp", ""),
                                "severity": s.get("severity", ""),
                                "component_id": s.get("component_id", ""),
                                "payload": str(s.get("payload", ""))[:240],
                            }
                        )
                    st.dataframe(pd.DataFrame(sig_rows), use_container_width=True, hide_index=True)
            except Exception as e:
                st.warning(f"could not load signals: {e}")

            st.divider()

            st.markdown("##### RCA")
            if rca:
                st.json(rca)
            else:
                st.warning("No RCA submitted yet. Use the **RCA Form** tab.")


# ---------- Tab 3: RCA Form ----------

with tab_rca:
    st.subheader("Submit RCA")
    st.caption("All fields are mandatory. Closing an incident without a complete RCA is rejected by the backend.")

    rca_wid = st.text_input("Work item ID", key="rca_wid")
    if not rca_wid.strip().isdigit():
        st.caption("Enter a numeric work item ID above.")
    else:
        wid = int(rca_wid.strip())
        try:
            existing = api_get(f"/incidents/{wid}")
        except Exception as e:
            st.error(f"failed to load incident: {e}")
            existing = None

        if existing:
            wi = existing["work_item"]
            existing_rca = existing.get("rca") or {}
            st.markdown(
                f"**Component:** `{wi['component_id']}` | "
                f"**Severity:** {SEVERITY_BADGE.get(wi['severity'], wi['severity'])} | "
                f"**State:** {STATE_BADGE.get(wi['state'], wi['state'])}"
            )

            try:
                inc_start = datetime.fromisoformat(wi["start_time"].replace("Z", "+00:00"))
            except Exception:
                inc_start = datetime.now(timezone.utc)

            with st.form(key=f"rca_form_{wid}", clear_on_submit=False):
                col1, col2 = st.columns(2)
                with col1:
                    sd = st.date_input("Incident start date", value=inc_start.date(), key=f"sd_{wid}")
                    stt = st.time_input("Incident start time", value=inc_start.time(), key=f"stt_{wid}")
                with col2:
                    ed = st.date_input("Incident end date", value=datetime.now(timezone.utc).date(), key=f"ed_{wid}")
                    ett = st.time_input("Incident end time", value=datetime.now(timezone.utc).time(), key=f"ett_{wid}")

                category_default = (
                    ROOT_CAUSE_CATEGORIES.index(existing_rca["root_cause_category"])
                    if existing_rca.get("root_cause_category") in ROOT_CAUSE_CATEGORIES
                    else 0
                )
                category = st.selectbox(
                    "Root cause category",
                    options=ROOT_CAUSE_CATEGORIES,
                    index=category_default,
                    key=f"cat_{wid}",
                )
                fix_applied = st.text_area(
                    "Fix applied",
                    value=existing_rca.get("fix_applied", ""),
                    placeholder="What you actually changed to stop the bleeding.",
                    height=120,
                    key=f"fix_{wid}",
                )
                prevention = st.text_area(
                    "Prevention",
                    value=existing_rca.get("prevention", ""),
                    placeholder="How this won't happen again. Monitoring, tests, runbooks.",
                    height=120,
                    key=f"prev_{wid}",
                )

                colA, colB = st.columns(2)
                save_only = colA.form_submit_button("Save RCA", use_container_width=True)
                save_and_close = colB.form_submit_button(
                    "Save RCA + Close incident", use_container_width=True, type="primary"
                )

                if save_only or save_and_close:
                    start_dt = datetime.combine(sd, stt).replace(tzinfo=timezone.utc)
                    end_dt = datetime.combine(ed, ett).replace(tzinfo=timezone.utc)
                    if end_dt < start_dt:
                        st.error("End time must be on/after start time.")
                    elif not fix_applied.strip() or not prevention.strip():
                        st.error("Fix applied and prevention are required.")
                    else:
                        payload = {
                            "root_cause_category": category,
                            "fix_applied": fix_applied,
                            "prevention": prevention,
                            "rca_start_time": start_dt.isoformat(),
                            "rca_end_time": end_dt.isoformat(),
                        }
                        code, body = api_post(f"/incidents/{wid}/rca", payload)
                        if not (200 <= code < 300):
                            st.error(f"RCA save rejected ({code}): {body}")
                        else:
                            st.success("RCA saved.")
                            if save_and_close:
                                cur_state = wi["state"]
                                if cur_state == "OPEN":
                                    api_post(f"/incidents/{wid}/transition", {"target_state": "INVESTIGATING"})
                                    api_post(f"/incidents/{wid}/transition", {"target_state": "RESOLVED"})
                                elif cur_state == "INVESTIGATING":
                                    api_post(f"/incidents/{wid}/transition", {"target_state": "RESOLVED"})
                                code2, body2 = api_post(
                                    f"/incidents/{wid}/transition", {"target_state": "CLOSED"}
                                )
                                if 200 <= code2 < 300:
                                    st.success("Incident closed. MTTR auto-computed.")
                                    st.json(body2)
                                else:
                                    st.error(f"close rejected ({code2}): {body2}")
