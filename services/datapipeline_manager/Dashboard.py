import pandas as pd
import streamlit as st

from datapipeline_manager import clickhouse, db, ui


ui.set_page_config("Dashboard")
ui.inject_css()
ui.require_auth()
ui.sidebar()
ui.header("ITSEC Datapipeline Manager", "Dashboard overview")


def metric_card(label: str, value: str, caption: str = "", accent: str = "#38bdf8") -> None:
    st.markdown(
        f"""
        <div class="itsec-card itsec-card--metric" style="border-left-color: {accent};">
          <div class="itsec-muted">{label}</div>
          <div class="itsec-metric">{value}</div>
          <div class="itsec-metric-caption">{caption}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


project_count = db.fetch_one("SELECT COUNT(*) AS count FROM metadata.projects") or {"count": 0}
source_enabled = db.fetch_one(
    "SELECT COUNT(*) AS count FROM metadata.opensearch_sources WHERE enabled = TRUE"
) or {"count": 0}
backfill_active = db.fetch_one(
    """
    SELECT COUNT(*) AS count
    FROM metadata.backfill_jobs
    WHERE status IN ('pending', 'running')
    """
) or {"count": 0}
last_status = db.fetch_one(
    """
    SELECT status, COUNT(*) AS count
    FROM metadata.ingestion_state
    GROUP BY status
    ORDER BY count DESC
    LIMIT 1
    """
)

col1, col2, col3, col4 = st.columns(4)
with col1:
    metric_card("Projects", str(project_count["count"]), "Total onboarded", "#38bdf8")
with col2:
    metric_card("Enabled Sources", str(source_enabled["count"]), "Active ingest targets", "#34d399")
with col3:
    metric_card("Active Backfills", str(backfill_active["count"]), "Queued or running", "#f59e0b")
with col4:
    status_label = last_status["status"] if last_status else "n/a"
    metric_card("Last Ingestion Status", status_label, "Most common status", "#818cf8")

st.markdown("### Ingestion Lag by Source")
lag_rows = db.fetch_all(
    """
    SELECT s.project_id,
           s.name,
           i.last_ts,
           i.status,
           i.updated_at
    FROM metadata.opensearch_sources s
    LEFT JOIN metadata.ingestion_state i
      ON i.source_id = s.source_id
    ORDER BY s.project_id, s.name
    """
)

if lag_rows:
    now = ui.utc_now()
    for row in lag_rows:
        last_ts = row.get("last_ts")
        row["lag_minutes"] = (
            (now - last_ts).total_seconds() / 60.0 if last_ts else None
        )
    lag_df = pd.DataFrame(lag_rows)
    chart_df = lag_df.dropna(subset=["lag_minutes"]).set_index("name")
    if not chart_df.empty:
        st.bar_chart(chart_df["lag_minutes"])
    st.dataframe(
        lag_df[["project_id", "name", "status", "last_ts", "lag_minutes"]],
        use_container_width=True,
    )
else:
    st.info("No ingestion state yet.")

st.markdown("### Ingestion Trends (Last 24 Hours)")
projects = db.fetch_all("SELECT project_id FROM metadata.projects ORDER BY project_id")
project_ids = [row["project_id"] for row in projects]
selected_project = st.selectbox(
    "Project for ClickHouse metrics", options=project_ids or ["no-projects"]
)

if selected_project and selected_project != "no-projects":
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Events per Hour**")
        try:
            rows = clickhouse.query_rows(
                f"""
                SELECT toStartOfHour(event_ts) AS hour, count() AS events
                FROM {selected_project}_bronze.os_events_raw
                WHERE event_ts >= now() - INTERVAL 24 HOUR
                GROUP BY hour
                ORDER BY hour
                """
            )
            if rows:
                events_df = pd.DataFrame(rows)
                events_df["hour"] = pd.to_datetime(events_df["hour"])
                events_df = events_df.set_index("hour")
                st.line_chart(events_df["events"])
            else:
                st.info("No events in the last 24 hours.")
        except Exception as exc:
            st.error(f"ClickHouse query failed: {exc}")
    with col2:
        st.markdown("**Ingestion Lag (minutes)**")
        try:
            lag_rows = clickhouse.query_rows(
                f"""
                SELECT toStartOfHour(ingested_at) AS hour,
                       avg(dateDiff('minute', event_ts, ingested_at)) AS lag_minutes
                FROM {selected_project}_bronze.os_events_raw
                WHERE ingested_at >= now() - INTERVAL 24 HOUR
                GROUP BY hour
                ORDER BY hour
                """
            )
            if lag_rows:
                lag_df = pd.DataFrame(lag_rows)
                lag_df["hour"] = pd.to_datetime(lag_df["hour"])
                lag_df = lag_df.set_index("hour")
                st.line_chart(lag_df["lag_minutes"])
            else:
                st.info("No lag data in the last 24 hours.")
        except Exception as exc:
            st.error(f"Lag query failed: {exc}")

st.markdown("### Recent Errors")
errors_ingestion = db.fetch_all(
    """
    SELECT source_id, index_name, last_error, updated_at
    FROM metadata.ingestion_state
    WHERE last_error IS NOT NULL
    ORDER BY updated_at DESC
    LIMIT 10
    """
)
errors_backfill = db.fetch_all(
    """
    SELECT job_id, source_id, last_error, updated_at
    FROM metadata.backfill_jobs
    WHERE last_error IS NOT NULL
    ORDER BY updated_at DESC
    LIMIT 10
    """
)

col_a, col_b = st.columns(2)
with col_a:
    st.markdown("**Ingestion errors**")
    st.dataframe(errors_ingestion, use_container_width=True)
with col_b:
    st.markdown("**Backfill errors**")
    st.dataframe(errors_backfill, use_container_width=True)
