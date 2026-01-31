import json
import re
from typing import Optional

import pandas as pd
import psycopg2
import streamlit as st

from datapipeline_manager import clickhouse, db, opensearch, ui


ui.set_page_config("Puller")
ui.inject_css()
ui.require_auth()
ui.sidebar()
ui.header("OpenSearch Puller", "Onboard sources, configure ingestion, and monitor health")


DEFAULT_CONFIG = {
    "poll_interval_seconds": 30,
    "overlap_minutes": 10,
    "batch_size": 500,
    "max_retries": 3,
    "backoff_base_seconds": 1.0,
    "rate_limit_seconds": 0.0,
    "opensearch_timeout_seconds": 30,
    "clickhouse_timeout_seconds": 30,
    "opensearch_verify_ssl": True,
}


def _read_secret(secret_ref: Optional[str]) -> Optional[str]:
    if not secret_ref:
        return None
    try:
        with open(secret_ref, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return None


def _is_safe_identifier(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z0-9_]+$", value or ""))


def _fetch_puller_config():
    try:
        return db.fetch_one(
            """
            SELECT poll_interval_seconds,
                   overlap_minutes,
                   batch_size,
                   max_retries,
                   backoff_base_seconds,
                   rate_limit_seconds,
                   opensearch_timeout_seconds,
                   clickhouse_timeout_seconds,
                   opensearch_verify_ssl,
                   updated_by,
                   updated_at
            FROM metadata.opensearch_puller_config
            ORDER BY updated_at DESC
            LIMIT 1
            """
        ), None
    except Exception as exc:
        return None, exc


projects = db.fetch_all("SELECT project_id FROM metadata.projects ORDER BY project_id")
project_ids = [row["project_id"] for row in projects]

sources = db.fetch_all(
    """
    SELECT source_id, project_id, name, base_url, auth_type, username, secret_ref, secret_enc,
           index_pattern, time_field, query_filter_json, enabled, created_at, updated_at
    FROM metadata.opensearch_sources
    ORDER BY source_id
    """
)


tabs = st.tabs(["Add Source", "Puller Config", "Monitoring"])

with tabs[0]:
    st.markdown("### Add OpenSearch Source")
    st.caption("Create a new ingestion pipeline when a new OpenSearch source appears.")

    with st.form("puller_add_source"):
        project_id = st.selectbox(
            "Project",
            options=project_ids or ["no-projects"],
        )
        name = st.text_input("Source Name", value="")

        auth_options = ["none", "basic", "api_key", "bearer"]
        with st.expander("Step 1: Connection", expanded=True):
            base_url = st.text_input("Base URL", value="")
            auth_type = st.selectbox("Auth Type", options=auth_options, index=0)
            username = st.text_input("Username", value="")
            secret_mode = st.radio(
                "Credential Source",
                options=["stored", "secret_ref"],
                index=0,
                horizontal=True,
                help="Store credentials in Postgres or reference a mounted secret file.",
            )
            secret_ref = None
            secret = ""
            if auth_type != "none":
                if secret_mode == "stored":
                    label = "Password" if auth_type == "basic" else "Secret"
                    secret = st.text_input(label, type="password")
                else:
                    secret_ref = st.text_input("Secret Ref (file path)", value="/run/secrets/opensearch_key")
                    st.caption("Secret file must be mounted into /run/secrets.")
            else:
                st.caption("No secret needed for auth_type=none.")

        with st.expander("Step 2: Indexing", expanded=True):
            index_pattern = st.text_input("Index Pattern", value="")
            time_field = st.text_input("Time Field", value="@timestamp")

        with st.expander("Step 3: Filters", expanded=False):
            query_filter_json = st.text_area("Query Filter JSON", value="{}", height=80)

        enabled = st.checkbox("Enabled", value=True)
        col_a, col_b = st.columns(2)
        with col_a:
            submit = st.form_submit_button("Create Source")
        with col_b:
            test = st.form_submit_button("Test Connection")

    if test:
        query_filter = ui.parse_json(query_filter_json)
        if query_filter is None:
            st.error("Query filter JSON is invalid.")
        else:
            secret_value = None
            if auth_type != "none":
                if secret_mode == "stored":
                    secret_value = secret
                else:
                    secret_value = _read_secret(secret_ref)
            if auth_type != "none" and not secret_value:
                label = "Password" if auth_type == "basic" else "Secret"
                st.error(f"{label} is required for the selected auth type.")
            else:
                ok, message, indices = opensearch.test_connection(
                    base_url=base_url,
                    index_pattern=index_pattern,
                    auth_type=None if auth_type == "none" else auth_type,
                    username=username,
                    secret=secret_value,
                )
                if ok:
                    ui.notify(message, "success")
                    st.write(indices)
                else:
                    st.error(message)

    if submit:
        query_filter = ui.parse_json(query_filter_json)
        if query_filter is None:
            st.error("Query filter JSON is invalid.")
        elif project_id == "no-projects":
            st.error("No enabled projects available.")
        elif not name or not base_url or not index_pattern or not time_field:
            st.error("Name, base URL, index pattern, and time field are required.")
        elif auth_type != "none" and secret_mode == "secret_ref" and not secret_ref:
            st.error("Secret ref is required for the selected auth type.")
        elif auth_type != "none" and secret_mode == "stored" and not secret:
            label = "Password" if auth_type == "basic" else "Secret"
            st.error(f"{label} is required for the selected auth type.")
        else:
            secret_ref_value = None
            secret_enc_value = None
            if auth_type != "none":
                if secret_mode == "secret_ref":
                    secret_ref_value = secret_ref
                else:
                    secret_enc_value = ui.encrypt_secret(secret)
            secret_enc_param = (
                psycopg2.Binary(secret_enc_value) if secret_enc_value is not None else None
            )
            try:
                db.execute(
                    """
                    INSERT INTO metadata.opensearch_sources (
                      project_id, name, base_url, auth_type, username, secret_ref,
                      secret_enc, index_pattern, time_field, query_filter_json,
                      enabled, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                    """,
                    (
                        project_id,
                        name,
                        base_url,
                        None if auth_type == "none" else auth_type,
                        username,
                        secret_ref_value,
                        secret_enc_param,
                        index_pattern,
                        time_field,
                        json.dumps(query_filter),
                        enabled,
                    ),
                )
                ui.notify("Source created.")
                st.rerun()
            except Exception as exc:
                st.error(f"Save failed: {exc}")

    st.markdown("### Existing Sources")
    if sources:
        display_rows = [
            {key: value for key, value in row.items() if key != "secret_enc"}
            for row in sources
        ]
        st.dataframe(pd.DataFrame(display_rows), use_container_width=True)
    else:
        st.info("No OpenSearch sources configured yet.")

with tabs[1]:
    st.markdown("### Puller Configuration")
    config_row, config_error = _fetch_puller_config()
    if config_error:
        st.warning(
            "Puller config table not available yet. Run the SQL in README to create "
            "metadata.opensearch_puller_config."
        )

    effective = {**DEFAULT_CONFIG, **(config_row or {})}
    updated_by = effective.get("updated_by") or st.session_state.get("username", "admin")

    with st.form("puller_config_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            poll_interval = st.number_input(
                "Poll Interval (seconds)",
                min_value=5,
                value=int(effective["poll_interval_seconds"]),
                step=5,
            )
            overlap_minutes = st.number_input(
                "Overlap Minutes",
                min_value=0,
                value=int(effective["overlap_minutes"]),
                step=1,
            )
            batch_size = st.number_input(
                "Batch Size",
                min_value=1,
                value=int(effective["batch_size"]),
                step=50,
            )
        with col2:
            max_retries = st.number_input(
                "Max Retries",
                min_value=0,
                value=int(effective["max_retries"]),
                step=1,
            )
            backoff_base = st.number_input(
                "Backoff Base Seconds",
                min_value=0.0,
                value=float(effective["backoff_base_seconds"]),
                step=0.5,
            )
            rate_limit = st.number_input(
                "Rate Limit Seconds",
                min_value=0.0,
                value=float(effective["rate_limit_seconds"]),
                step=0.5,
            )
        with col3:
            os_timeout = st.number_input(
                "OpenSearch Timeout (seconds)",
                min_value=5,
                value=int(effective["opensearch_timeout_seconds"]),
                step=5,
            )
            ch_timeout = st.number_input(
                "ClickHouse Timeout (seconds)",
                min_value=5,
                value=int(effective["clickhouse_timeout_seconds"]),
                step=5,
            )
            verify_ssl = st.checkbox(
                "Verify OpenSearch SSL",
                value=bool(effective["opensearch_verify_ssl"]),
            )

        updated_by = st.text_input("Updated By", value=updated_by)
        submitted = st.form_submit_button("Save Configuration")

    if submitted:
        try:
            db.execute(
                """
                INSERT INTO metadata.opensearch_puller_config (
                  config_id, poll_interval_seconds, overlap_minutes, batch_size,
                  max_retries, backoff_base_seconds, rate_limit_seconds,
                  opensearch_timeout_seconds, clickhouse_timeout_seconds, opensearch_verify_ssl,
                  updated_by, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (config_id) DO UPDATE SET
                  poll_interval_seconds = EXCLUDED.poll_interval_seconds,
                  overlap_minutes = EXCLUDED.overlap_minutes,
                  batch_size = EXCLUDED.batch_size,
                  max_retries = EXCLUDED.max_retries,
                  backoff_base_seconds = EXCLUDED.backoff_base_seconds,
                  rate_limit_seconds = EXCLUDED.rate_limit_seconds,
                  opensearch_timeout_seconds = EXCLUDED.opensearch_timeout_seconds,
                  clickhouse_timeout_seconds = EXCLUDED.clickhouse_timeout_seconds,
                  opensearch_verify_ssl = EXCLUDED.opensearch_verify_ssl,
                  updated_by = EXCLUDED.updated_by,
                  updated_at = now()
                """,
                (
                    1,
                    int(poll_interval),
                    int(overlap_minutes),
                    int(batch_size),
                    int(max_retries),
                    float(backoff_base),
                    float(rate_limit),
                    int(os_timeout),
                    int(ch_timeout),
                    bool(verify_ssl),
                    updated_by,
                ),
            )
            ui.notify("Puller configuration saved.")
            st.rerun()
        except Exception as exc:
            st.error(f"Save failed: {exc}")

    st.markdown("### Effective Configuration")
    if config_row:
        st.dataframe(pd.DataFrame([config_row]), use_container_width=True)
    else:
        st.dataframe(pd.DataFrame([effective]), use_container_width=True)

with tabs[2]:
    st.markdown("### Puller Status")
    heartbeat = db.fetch_one(
        """
        SELECT worker_id, worker_type, last_seen, status, details
        FROM metadata.worker_heartbeats
        WHERE worker_type = 'opensearch_puller'
        ORDER BY last_seen DESC
        LIMIT 1
        """
    )

    now = ui.utc_now()
    details = (heartbeat or {}).get("details") or {}
    poll_interval = details.get("poll_interval")
    try:
        poll_interval = int(poll_interval) if poll_interval is not None else None
    except (TypeError, ValueError):
        poll_interval = None

    threshold = max(60, (poll_interval or DEFAULT_CONFIG["poll_interval_seconds"]) * 2)
    last_seen = heartbeat.get("last_seen") if heartbeat else None
    age_seconds = (now - last_seen).total_seconds() if last_seen else None
    if not heartbeat:
        status = "unknown"
    elif age_seconds is not None and age_seconds > threshold:
        status = "stale"
    else:
        status = heartbeat.get("status") or "idle"

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Puller Status", status)
    col2.metric("Last Seen", last_seen.isoformat() if last_seen else "n/a")
    col3.metric("Heartbeat Age (sec)", int(age_seconds) if age_seconds is not None else "n/a")
    col4.metric("Poll Interval (sec)", poll_interval or DEFAULT_CONFIG["poll_interval_seconds"])

    st.markdown("### Runtime Config Snapshot")
    if details:
        st.json(details)
    else:
        st.info("No heartbeat details available yet.")

    st.markdown("### Ingestion Overview")
    ingestion_rows = db.fetch_all(
        """
        SELECT s.source_id,
               s.project_id,
               s.name,
               s.enabled,
               i.index_name,
               i.last_ts,
               i.updated_at,
               i.status,
               i.last_error
        FROM metadata.opensearch_sources s
        LEFT JOIN metadata.ingestion_state i
          ON i.source_id = s.source_id
        ORDER BY s.project_id, s.name, i.index_name
        """
    )

    enriched = []
    for row in ingestion_rows:
        updated_at = row.get("updated_at")
        age_seconds = (now - updated_at).total_seconds() if updated_at else None
        lag_minutes = None
        if row.get("last_ts"):
            lag_minutes = (now - row["last_ts"]).total_seconds() / 60.0
        if row.get("last_error"):
            live_status = "error"
        elif age_seconds is None:
            live_status = "unknown"
        elif age_seconds <= threshold:
            live_status = "active"
        else:
            live_status = "idle"
        row = dict(row)
        row["age_seconds"] = age_seconds
        row["lag_minutes"] = lag_minutes
        row["live_status"] = live_status
        enriched.append(row)

    total_sources = len({row["source_id"] for row in ingestion_rows})
    enabled_sources = len({row["source_id"] for row in ingestion_rows if row.get("enabled")})
    total_indices = len([row for row in ingestion_rows if row.get("index_name")])
    error_indices = len([row for row in enriched if row.get("live_status") == "error"])
    active_indices = len([row for row in enriched if row.get("live_status") == "active"])

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Sources (enabled/total)", f"{enabled_sources}/{total_sources}")
    col2.metric("Indices Tracked", total_indices)
    col3.metric("Active Indices", active_indices)
    col4.metric("Error Indices", error_indices)

    project_filter = st.selectbox(
        "Project filter",
        options=["all"] + sorted({row["project_id"] for row in ingestion_rows}),
        index=0,
    )
    status_filter = st.selectbox(
        "Status filter", ["all", "active", "idle", "error", "unknown"], index=0
    )
    filtered = []
    for row in enriched:
        project_ok = project_filter == "all" or row["project_id"] == project_filter
        status_ok = status_filter == "all" or row["live_status"] == status_filter
        if project_ok and status_ok:
            filtered.append(row)

    if filtered:
        df = pd.DataFrame(filtered)
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No ingestion rows match the filters.")

    st.markdown("### Backfill Queue")
    backfill_rows = db.fetch_all(
        """
        SELECT job_id, source_id, start_ts, end_ts, status, last_error, updated_at
        FROM metadata.backfill_jobs
        ORDER BY updated_at DESC
        LIMIT 50
        """
    )
    if backfill_rows:
        backfill_df = pd.DataFrame(backfill_rows)
        st.dataframe(backfill_df, use_container_width=True)
    else:
        st.info("No backfill jobs recorded.")

    st.markdown("### ClickHouse Activity")
    selected_project = st.selectbox(
        "Project for metrics",
        options=project_ids or ["no-projects"],
        key="puller_metrics_project",
    )
    if selected_project and selected_project != "no-projects":
        if not _is_safe_identifier(selected_project):
            st.error("Project id contains unsupported characters.")
        else:
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

                rows = clickhouse.query_rows(
                    f"""
                    SELECT max(event_ts) AS last_event_ts
                    FROM {selected_project}_bronze.os_events_raw
                    """
                )
                last_event_ts = rows[0]["last_event_ts"] if rows else None
                st.metric("Latest Event", str(last_event_ts) if last_event_ts else "n/a")

                rows = clickhouse.query_rows(
                    f"""
                    SELECT source_id,
                           count() AS events_last_hour,
                           max(event_ts) AS last_event_ts
                    FROM {selected_project}_bronze.os_events_raw
                    WHERE event_ts >= now() - INTERVAL 1 HOUR
                    GROUP BY source_id
                    ORDER BY events_last_hour DESC
                    """
                )
                if rows:
                    st.dataframe(pd.DataFrame(rows), use_container_width=True)
            except Exception as exc:
                st.error(f"ClickHouse query failed: {exc}")
