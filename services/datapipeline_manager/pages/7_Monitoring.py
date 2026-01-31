import pandas as pd
import streamlit as st

from datapipeline_manager import clickhouse, db, ui


ui.set_page_config("Monitoring")
ui.inject_css()
ui.require_auth()
ui.sidebar()
ui.header("Monitoring & Status", "Ingestion health and operational metrics")


def _worker_status():
    heartbeat = db.fetch_one(
        """
        SELECT worker_id, worker_type, last_seen, status, details
        FROM metadata.worker_heartbeats
        WHERE worker_type = 'opensearch_puller'
        ORDER BY last_seen DESC
        LIMIT 1
        """
    )
    if not heartbeat:
        return {"status": "unknown", "last_seen": None, "age_seconds": None}

    now = ui.utc_now()
    last_seen = heartbeat.get("last_seen")
    age_seconds = (now - last_seen).total_seconds() if last_seen else None

    details = heartbeat.get("details") or {}
    poll_interval = details.get("poll_interval")
    try:
        poll_interval = int(poll_interval) if poll_interval is not None else None
    except (TypeError, ValueError):
        poll_interval = None

    threshold = max(60, (poll_interval or 30) * 2)
    if age_seconds is None:
        status = "unknown"
    elif age_seconds > threshold:
        status = "stale"
    else:
        status = heartbeat.get("status") or "idle"

    return {
        "status": status,
        "last_seen": last_seen,
        "age_seconds": age_seconds,
        "poll_interval": poll_interval,
        "threshold": threshold,
    }


st.markdown("### Puller Status")
worker = _worker_status()
activity_threshold = worker.get("threshold") or 60
if worker["last_seen"]:
    st.metric("OpenSearch Puller", worker["status"], worker["last_seen"].isoformat())
else:
    st.metric("OpenSearch Puller", worker["status"])

st.markdown("### Ingestion Status")
rows = db.fetch_all(
    """
    SELECT s.source_id,
           s.project_id,
           s.name,
           i.index_name,
           i.last_ts,
           i.updated_at,
           i.status,
           i.last_error
    FROM metadata.opensearch_sources s
    LEFT JOIN metadata.ingestion_state i
      ON i.source_id = s.source_id
    ORDER BY s.project_id, s.name
    """
)

project_filter = st.selectbox(
    "Project filter", ["all"] + sorted({r["project_id"] for r in rows}), index=0
)
status_filter = st.selectbox(
    "Status filter", ["all", "active", "idle", "error", "unknown"], index=0
)

filtered = []
now = ui.utc_now()
for row in rows:
    project_ok = project_filter == "all" or row["project_id"] == project_filter
    raw_status = row.get("status") or "idle"
    row["raw_status"] = raw_status
    updated_at = row.get("updated_at")
    age_seconds = (now - updated_at).total_seconds() if updated_at else None
    row["age_seconds"] = age_seconds
    if row.get("last_ts"):
        row["lag_minutes"] = (now - row["last_ts"]).total_seconds() / 60.0
    else:
        row["lag_minutes"] = None
    if raw_status == "error" or row.get("last_error"):
        live_status = "error"
    elif age_seconds is None:
        live_status = "unknown"
    elif age_seconds <= activity_threshold:
        live_status = "active"
    else:
        live_status = "idle"
    row["status"] = live_status
    status_ok = status_filter == "all" or live_status == status_filter
    if project_ok and status_ok:
        filtered.append(row)

df = pd.DataFrame(filtered)
st.dataframe(df, use_container_width=True)

st.markdown("### Operational Metrics")
projects = db.fetch_all("SELECT project_id FROM metadata.projects ORDER BY project_id")
project_ids = [row["project_id"] for row in projects]
selected_project = st.selectbox(
    "Project for metrics", options=project_ids or ["no-projects"], key="metrics_project"
)

col1, col2 = st.columns(2)
with col1:
    if selected_project and selected_project != "no-projects":
        try:
            rows = clickhouse.query_rows(
                f"""
                SELECT count() AS events_last_hour
                FROM {selected_project}_bronze.os_events_raw
                WHERE event_ts >= now() - INTERVAL 1 HOUR
                """
            )
            count = rows[0]["events_last_hour"] if rows else 0
            st.metric("Events (Last Hour)", int(count))
        except Exception as exc:
            st.error(f"ClickHouse query failed: {exc}")
with col2:
    try:
        heartbeat = db.fetch_one(
            """
            SELECT worker_id, worker_type, last_seen, status
            FROM metadata.worker_heartbeats
            ORDER BY last_seen DESC
            LIMIT 1
            """
        )
        if heartbeat:
            st.metric("Worker Heartbeat", heartbeat["last_seen"].isoformat())
        else:
            st.info("No heartbeat data yet.")
    except Exception:
        st.info("Heartbeat table not available.")

st.markdown("### Last Successful Batch")
last_success = db.fetch_one(
    "SELECT MAX(updated_at) AS last_success FROM metadata.ingestion_state WHERE status = 'idle'"
)
if last_success and last_success.get("last_success"):
    st.metric("Last Successful Batch", last_success["last_success"].isoformat())
else:
    st.info("No successful batches recorded yet.")

st.markdown("### Recent Errors")
error_rows = [row for row in filtered if row.get("last_error")]
st.dataframe(pd.DataFrame(error_rows), use_container_width=True)
