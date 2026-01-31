from datetime import datetime, time, timezone

import pandas as pd
import streamlit as st

from datapipeline_manager import db, ui


ui.set_page_config("Backfill")
ui.inject_css()
ui.require_auth()
ui.sidebar()
ui.header("Backfill Jobs", "Run historical loads safely")

sources = db.fetch_all(
    "SELECT source_id, project_id, name FROM metadata.opensearch_sources ORDER BY source_id"
)
source_labels = [f"{row['source_id']} | {row['project_id']} | {row['name']}" for row in sources]
source_map = {label: row["source_id"] for label, row in zip(source_labels, sources)}

st.markdown("### Create Backfill Job")
st.caption("Throttle seconds add a pause between batches during backfill.")
with st.form("create_backfill"):
    source_label = st.selectbox("Source", options=source_labels or ["no-sources"])
    col_a, col_b = st.columns(2)
    with col_a:
        start_date = st.date_input("Start Date", value=datetime.utcnow().date())
        start_time = st.time_input("Start Time (UTC)", value=time(0, 0))
    with col_b:
        end_date = st.date_input("End Date", value=datetime.utcnow().date())
        end_time = st.time_input("End Time (UTC)", value=time(23, 59))
    throttle = st.number_input("Throttle Seconds (optional)", min_value=0, value=0, step=1)
    requested_by = st.text_input("Requested By", value="admin")
    submitted = st.form_submit_button("Create Backfill")
    if submitted:
        if source_label == "no-sources":
            st.error("No sources available.")
        else:
            start_ts = datetime.combine(start_date, start_time, tzinfo=timezone.utc)
            end_ts = datetime.combine(end_date, end_time, tzinfo=timezone.utc)
            if end_ts <= start_ts:
                st.error("End timestamp must be after start timestamp.")
            else:
                db.execute(
                    """
                    INSERT INTO metadata.backfill_jobs (
                      source_id, start_ts, end_ts, status, requested_by, created_at, updated_at, throttle_seconds
                    ) VALUES (%s, %s, %s, 'pending', %s, now(), now(), %s)
                    """,
                    (
                        source_map[source_label],
                        start_ts.isoformat(),
                        end_ts.isoformat(),
                        requested_by,
                        int(throttle),
                    ),
                )
                ui.notify("Backfill job queued.")
                st.rerun()

st.markdown("### Backfill Jobs")
status_filter = st.selectbox(
    "Status filter",
    ["all", "pending", "running", "completed", "failed", "cancelled"],
    index=0,
)
source_filter = st.selectbox("Source filter", ["all"] + source_labels, index=0)
enable_date_filter = st.checkbox("Filter by start date", value=False)
date_filter = (
    st.date_input("Start date (UTC)", value=datetime.utcnow().date())
    if enable_date_filter
    else None
)

jobs = db.fetch_all(
    """
    SELECT job_id, source_id, start_ts, end_ts, status, last_error, updated_at, throttle_seconds
    FROM metadata.backfill_jobs
    ORDER BY created_at DESC
    """
)

filtered = []
for row in jobs:
    status_ok = status_filter == "all" or row["status"] == status_filter
    source_ok = True
    if source_filter != "all":
        source_ok = str(row["source_id"]) == source_filter.split("|", 1)[0].strip()
    date_ok = True
    if date_filter:
        date_ok = row["start_ts"].date() >= date_filter
    if status_ok and source_ok and date_ok:
        filtered.append(row)

df = pd.DataFrame(filtered)
page_size = st.selectbox("Rows per page", [10, 20, 50], index=1)
total_pages = max(1, (len(df) + page_size - 1) // page_size)
page = st.number_input("Page", min_value=1, max_value=total_pages, value=1, key="backfill_page")
start = (page - 1) * page_size
end = start + page_size
st.dataframe(df.iloc[start:end] if not df.empty else df, use_container_width=True)

st.markdown("### Job Actions")
job_ids = [str(row["job_id"]) for row in filtered]
selected_job = st.selectbox("Select job", job_ids or ["none"])
job = next((row for row in jobs if str(row["job_id"]) == selected_job), None)

if job:
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Cancel Job"):
            confirm = st.checkbox("Confirm cancel", key="confirm_cancel")
            if confirm:
                db.execute(
                    """
                    UPDATE metadata.backfill_jobs
                    SET status = 'cancelled', updated_at = now()
                    WHERE job_id = %s
                      AND status IN ('pending', 'running')
                    """,
                    (job["job_id"],),
                )
                ui.notify("Backfill cancelled.")
                st.rerun()
    with col2:
        if st.button("Retry Failed"):
            confirm = st.checkbox("Confirm retry", key="confirm_retry")
            if confirm:
                db.execute(
                    """
                    UPDATE metadata.backfill_jobs
                    SET status = 'pending',
                        last_error = NULL,
                        last_index_name = NULL,
                        last_ts = NULL,
                        last_sort_json = NULL,
                        last_id = NULL,
                        updated_at = now()
                    WHERE job_id = %s
                      AND status = 'failed'
                    """,
                    (job["job_id"],),
                )
                ui.notify("Backfill re-queued.")
                st.rerun()
    with col3:
        st.write(job.get("last_error") or "No error")
