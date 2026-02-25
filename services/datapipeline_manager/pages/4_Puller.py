import re
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd
import streamlit as st

from datapipeline_manager import clickhouse, db, opensearch, ui


ui.set_page_config("Puller")
ui.inject_css()
ui.require_auth()
ui.sidebar()
ui.header("OpenSearch Puller", "Map existing sources to target tables and monitor ingestion")


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


_NON_IDENT_RE = re.compile(r"[^A-Za-z0-9_]+")
_MULTI_UNDERSCORE_RE = re.compile(r"_+")


def _normalize_token(value: str) -> str:
    token = (value or "").strip()
    if not token:
        return ""
    token = _NON_IDENT_RE.sub("_", token)
    token = _MULTI_UNDERSCORE_RE.sub("_", token)
    token = token.strip("_")
    return token.lower()


def _derive_clickhouse_namespace(project_id: str, name: str, explicit: str) -> str:
    namespace = _normalize_token(explicit)
    if not namespace:
        project_token = _normalize_token(project_id)
        name_token = _normalize_token(name)
        if project_token and project_token[0].isalpha():
            namespace = project_token
        else:
            namespace = name_token or project_token or "project"
    if not namespace[0].isalpha():
        namespace = f"p_{namespace}"
    return namespace


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


def _has_target_routing_columns() -> bool:
    try:
        row = db.fetch_one(
            """
            SELECT count(*) AS count
            FROM information_schema.columns
            WHERE table_schema = 'metadata'
              AND table_name = 'opensearch_sources'
              AND column_name IN ('target_dataset', 'target_table_name')
            """
        )
        return bool(row and int(row.get("count", 0)) >= 2)
    except Exception:
        return False


def _clickhouse_database_exists(database_name: str) -> bool:
    rows = clickhouse.query_rows(
        f"""
        SELECT count() AS count
        FROM system.databases
        WHERE name = '{database_name}'
        """
    )
    return bool(rows and int(rows[0].get("count", 0)) > 0)


_TABLE_REF_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)$")


def _parse_table_ref(value: str) -> Optional[Tuple[str, str]]:
    candidate = (value or "").strip().lower()
    match = _TABLE_REF_RE.match(candidate)
    if not match:
        return None
    return match.group(1), match.group(2)


def _collect_table_refs(selected: List[str], manual_text: str) -> Tuple[List[str], List[str]]:
    refs: List[str] = []
    invalid: List[str] = []

    tokens: List[str] = []
    tokens.extend(selected or [])
    tokens.extend(part.strip() for part in re.split(r"[\r\n,]+", manual_text or ""))

    for token in tokens:
        if not token:
            continue
        parsed = _parse_table_ref(token)
        if not parsed:
            if token not in invalid:
                invalid.append(token)
            continue
        ref = f"{parsed[0]}.{parsed[1]}"
        if ref not in refs:
            refs.append(ref)
    return refs, invalid


def _clickhouse_table_exists(table_ref: str) -> bool:
    parsed = _parse_table_ref(table_ref)
    if not parsed:
        return False
    database, table = parsed
    rows = clickhouse.query_rows(
        f"""
        SELECT count() AS count
        FROM system.tables
        WHERE database = '{database}'
          AND name = '{table}'
        """
    )
    return bool(rows and int(rows[0].get("count", 0)) > 0)


def _build_raw_source_from(table_refs: List[str]) -> str:
    parsed_refs = [_parse_table_ref(item) for item in table_refs]
    safe_refs = [item for item in parsed_refs if item]
    if len(safe_refs) == 1:
        database, table = safe_refs[0]
        return f"`{database}`.`{table}`"

    unions: List[str] = []
    for database, table in safe_refs:
        unions.append(
            f"SELECT event_id, event_ts, raw, ingested_at FROM `{database}`.`{table}`"
        )
    return f"({' UNION ALL '.join(unions)})"


def _resolve_parser_template_path() -> Optional[Path]:
    candidates: List[Path] = []
    here = Path(__file__).resolve()
    try:
        candidates.append(here.parents[3] / "clickhouse" / "init" / "05_raw_table_ingest.sql.tmpl")
    except IndexError:
        pass
    candidates.append(Path("/app/clickhouse/init/05_raw_table_ingest.sql.tmpl"))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _render_parser_apply_sql(template_sql: str, raw_source_from: str) -> str:
    return template_sql.replace("{{RAW_SOURCE_FROM}}", raw_source_from)


def _render_parser_backfill_sql(template_sql: str, raw_source_from: str) -> str:
    replaced = template_sql.replace("{{RAW_SOURCE_FROM}}", raw_source_from)
    output_lines: List[str] = []
    for line in replaced.splitlines():
        stripped = line.strip()
        if stripped.startswith("DROP TABLE IF EXISTS bronze.") and stripped.endswith(";"):
            continue
        if stripped == "CREATE MATERIALIZED VIEW bronze.suricata_events_mv":
            output_lines.append("INSERT INTO bronze.suricata_events_raw")
            continue
        if stripped == "CREATE MATERIALIZED VIEW bronze.wazuh_events_mv":
            output_lines.append("INSERT INTO bronze.wazuh_events_raw")
            continue
        if stripped == "CREATE MATERIALIZED VIEW bronze.zeek_events_mv":
            output_lines.append("INSERT INTO bronze.zeek_events_raw")
            continue
        if stripped in {
            "TO bronze.suricata_events_raw",
            "TO bronze.wazuh_events_raw",
            "TO bronze.zeek_events_raw",
            "AS",
        }:
            continue
        output_lines.append(line)
    return "\n".join(output_lines)


def _split_sql_statements(sql_text: str) -> List[str]:
    statements: List[str] = []
    for chunk in sql_text.split(";"):
        statement = chunk.strip()
        if statement:
            statements.append(statement)
    return statements


def _execute_clickhouse_script(sql_text: str, timeout: int = 120) -> None:
    for statement in _split_sql_statements(sql_text):
        clickhouse.execute_sql(statement, timeout=timeout)


def _default_raw_source_options(source_rows: List[dict]) -> List[str]:
    options: List[str] = []
    for row in source_rows:
        dataset = str(row.get("target_dataset") or "").strip().lower()
        table = str(row.get("target_table_name") or "").strip().lower()
        if not dataset or not table:
            continue
        if not _is_safe_identifier(dataset) or not _is_safe_identifier(table):
            continue
        ref = f"{dataset}.{table}"
        if ref not in options:
            options.append(ref)
    return options


HAS_TARGET_ROUTING = _has_target_routing_columns()


try:
    projects = db.fetch_all(
        "SELECT project_id, name, clickhouse_namespace FROM metadata.projects ORDER BY project_id"
    )
except Exception:
    projects = db.fetch_all(
        "SELECT project_id, name, NULL::text AS clickhouse_namespace FROM metadata.projects ORDER BY project_id"
    )
project_ids = [row["project_id"] for row in projects]
project_db = {
    row["project_id"]: _derive_clickhouse_namespace(
        row["project_id"],
        row.get("name") or "",
        row.get("clickhouse_namespace") or "",
    )
    for row in projects
}

if HAS_TARGET_ROUTING:
    sources = db.fetch_all(
        """
        SELECT s.source_id, s.project_id, s.name, s.base_url, s.auth_type, s.username, s.secret_ref, s.secret_enc,
               s.index_pattern, s.time_field, s.target_dataset, s.target_table_name,
               s.query_filter_json,
               COALESCE(to_jsonb(s)->>'exclude_index_patterns', '') AS exclude_index_patterns,
               s.enabled, s.created_at, s.updated_at
        FROM metadata.opensearch_sources s
        ORDER BY s.source_id
        """
    )
else:
    sources = db.fetch_all(
        """
        SELECT s.source_id, s.project_id, s.name, s.base_url, s.auth_type, s.username, s.secret_ref, s.secret_enc,
               s.index_pattern, s.time_field, s.query_filter_json,
               COALESCE(to_jsonb(s)->>'exclude_index_patterns', '') AS exclude_index_patterns,
               s.enabled, s.created_at, s.updated_at
        FROM metadata.opensearch_sources s
        ORDER BY s.source_id
        """
    )
    for row in sources:
        row["target_dataset"] = None
        row["target_table_name"] = None


tabs = st.tabs(["Source Routing", "Puller Config", "Monitoring", "Parser Runner"])

with tabs[0]:
    st.markdown("### Source Routing")
    st.caption(
        "Source connection and indexing are managed only in the Sources menu. "
        "Use this page to select an existing source and map it to an existing ClickHouse dataset (database) "
        "plus target table."
    )
    if not HAS_TARGET_ROUTING:
        st.warning(
            "Target routing columns are missing. Run metadata migration "
            "for `target_dataset` and `target_table_name`."
        )

    if not sources:
        st.info("No sources available. Create a source first in the Sources menu.")
    else:
        display_rows = [
            {key: value for key, value in row.items() if key != "secret_enc"}
            for row in sources
        ]
        st.dataframe(pd.DataFrame(display_rows), use_container_width=True)

        existing_options = [
            (str(row["source_id"]), f"{row['project_id']} / {row['name']} (id={row['source_id']})")
            for row in sources
        ]
        option_labels = [label for _, label in existing_options]
        selected_label = st.selectbox(
            "Existing Source",
            options=option_labels,
            key="puller_existing_source",
        )
        selected_id = next(
            (source_id for source_id, label in existing_options if label == selected_label),
            None,
        )
        selected_row = next(
            (row for row in sources if str(row["source_id"]) == str(selected_id)),
            None,
        )

        if selected_row and st.button("Test Selected Source Connection", key="puller_test_existing_source"):
            secret_value = _read_secret(selected_row.get("secret_ref"))
            if not secret_value:
                secret_value = ui.decrypt_secret(selected_row.get("secret_enc"))
            ok, message, indices = opensearch.test_connection(
                base_url=selected_row["base_url"],
                index_pattern=selected_row["index_pattern"],
                auth_type=selected_row.get("auth_type"),
                username=selected_row.get("username"),
                secret=secret_value,
                exclude_index_patterns=selected_row.get("exclude_index_patterns"),
            )
            if ok:
                ui.notify(message, "success")
                st.write(indices)
            else:
                st.error(message)

        st.markdown("### Define Target Destination")
        if HAS_TARGET_ROUTING:
            with st.form("puller_set_target_table_form"):
                target_dataset_existing = st.text_input(
                    "Target Dataset (ClickHouse Database)",
                    value=(selected_row.get("target_dataset") if selected_row else "") or "",
                    help="Create this database manually in ClickHouse UI first. Example: myproject_bronze",
                )
                target_table_existing = st.text_input(
                    "Target Table Name",
                    value=(selected_row.get("target_table_name") if selected_row else "") or "",
                    help="Table will be auto-created in the selected dataset if it does not exist.",
                )
                if target_dataset_existing and target_table_existing:
                    st.caption(
                        "Destination preview: "
                        f"`{target_dataset_existing.strip().lower()}.{target_table_existing.strip().lower()}`"
                    )
                submitted_target = st.form_submit_button("Save Destination")
            if submitted_target:
                target_dataset_norm = (target_dataset_existing or "").strip().lower()
                target_table_norm = (target_table_existing or "").strip().lower()
                if not target_dataset_norm:
                    st.error("Target Dataset is required.")
                elif not _is_safe_identifier(target_dataset_norm):
                    st.error("Target Dataset must be alphanumeric + underscore.")
                elif not target_table_norm:
                    st.error("Target Table Name is required.")
                elif not _is_safe_identifier(target_table_norm):
                    st.error("Target Table must be alphanumeric + underscore.")
                else:
                    try:
                        dataset_exists = _clickhouse_database_exists(target_dataset_norm)
                    except Exception as exc:
                        st.error(f"Failed to validate dataset in ClickHouse: {exc}")
                    else:
                        if not dataset_exists:
                            st.error(
                                f"Dataset/database `{target_dataset_norm}` is not found in ClickHouse. "
                                "Create it first in ClickHouse UI."
                            )
                        else:
                            try:
                                db.execute(
                                    """
                                    UPDATE metadata.opensearch_sources
                                    SET target_dataset = %s,
                                        target_table_name = %s,
                                        updated_at = now()
                                    WHERE source_id = %s
                                    """,
                                    (target_dataset_norm, target_table_norm, selected_id),
                                )
                                ui.notify("Target destination updated.")
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Update failed: {exc}")
        else:
            st.info("Run metadata migration first to enable target table mapping.")

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
    if HAS_TARGET_ROUTING:
        ingestion_rows = db.fetch_all(
            """
            SELECT s.source_id,
                   s.project_id,
                   s.name,
                   s.enabled,
                   s.target_dataset,
                   s.target_table_name,
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
    else:
        ingestion_rows = db.fetch_all(
            """
            SELECT s.source_id,
                   s.project_id,
                   s.name,
                   s.enabled,
                   NULL::text AS target_dataset,
                   NULL::text AS target_table_name,
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
        selected_project_db = project_db.get(selected_project, selected_project)
        if not _is_safe_identifier(selected_project_db):
            st.error("Project namespace contains unsupported characters.")
        else:
            try:
                target_routes = set()
                for row in sources:
                    if row.get("project_id") != selected_project or not row.get("enabled"):
                        continue
                    table_name = str(row.get("target_table_name") or "").strip().lower()
                    if not table_name or not _is_safe_identifier(table_name):
                        continue
                    dataset_name = str(row.get("target_dataset") or "").strip().lower()
                    if dataset_name and _is_safe_identifier(dataset_name):
                        database_name = dataset_name
                    else:
                        database_name = f"{selected_project_db}_bronze"
                    if _is_safe_identifier(database_name):
                        target_routes.add((database_name, table_name))

                if not target_routes:
                    st.info("No target destination configured for this project.")
                else:
                    target_routes = sorted(target_routes)
                    total_events_last_hour = 0
                    latest_event_ts = None
                    per_source: dict = {}

                    for database_name, table_name in target_routes:
                        qualified_table = f"`{database_name}`.`{table_name}`"
                        rows = clickhouse.query_rows(
                            f"""
                            SELECT count() AS events_last_hour
                            FROM {qualified_table}
                            WHERE event_ts >= now() - INTERVAL 1 HOUR
                            """
                        )
                        table_count = int(rows[0]["events_last_hour"]) if rows else 0
                        total_events_last_hour += table_count

                        rows = clickhouse.query_rows(
                            f"""
                            SELECT max(event_ts) AS last_event_ts
                            FROM {qualified_table}
                            """
                        )
                        table_last_ts = rows[0]["last_event_ts"] if rows else None
                        if table_last_ts and (latest_event_ts is None or table_last_ts > latest_event_ts):
                            latest_event_ts = table_last_ts

                        rows = clickhouse.query_rows(
                            f"""
                            SELECT source_id,
                                   count() AS events_last_hour,
                                   max(event_ts) AS last_event_ts
                            FROM {qualified_table}
                            WHERE event_ts >= now() - INTERVAL 1 HOUR
                            GROUP BY source_id
                            """
                        )
                        for source_row in rows:
                            source_id = source_row.get("source_id")
                            if not source_id:
                                continue
                            current = per_source.get(source_id, {"events_last_hour": 0, "last_event_ts": None})
                            current["events_last_hour"] += int(source_row.get("events_last_hour") or 0)
                            row_last_ts = source_row.get("last_event_ts")
                            if row_last_ts and (
                                current["last_event_ts"] is None or row_last_ts > current["last_event_ts"]
                            ):
                                current["last_event_ts"] = row_last_ts
                            per_source[source_id] = current

                    st.metric("Events (Last Hour)", total_events_last_hour)
                    st.metric("Latest Event", str(latest_event_ts) if latest_event_ts else "n/a")

                    if per_source:
                        source_rows = [
                            {
                                "source_id": source_id,
                                "events_last_hour": values["events_last_hour"],
                                "last_event_ts": values["last_event_ts"],
                            }
                            for source_id, values in per_source.items()
                        ]
                        source_rows.sort(key=lambda item: item["events_last_hour"], reverse=True)
                        st.dataframe(pd.DataFrame(source_rows), use_container_width=True)
                    scanned_tables = [f"{db_name}.{tbl_name}" for db_name, tbl_name in target_routes]
                    st.caption(f"Tables scanned: {', '.join(scanned_tables)}")
            except Exception as exc:
                st.error(f"ClickHouse query failed: {exc}")

with tabs[3]:
    st.markdown("### Raw Parser Runner")
    st.caption(
        "Run raw-table parser apply/backfill from UI (equivalent to "
        "`05_raw_table_ingest.sh` and `05_raw_table_backfill.sh`)."
    )

    template_path = _resolve_parser_template_path()
    if not template_path:
        st.error(
            "Parser template file `05_raw_table_ingest.sql.tmpl` tidak ditemukan di container UI. "
            "Rebuild image `itsec-datapipeline-manager` setelah update terakhir."
        )
    else:
        default_options = _default_raw_source_options(sources)
        selected_tables = st.multiselect(
            "Raw Source Tables",
            options=default_options,
            default=default_options,
            help="Ambil dari destination source puller yang sudah terdaftar di metadata.",
            key="puller_parser_selected_tables",
        )
        manual_tables = st.text_area(
            "Additional Raw Source Tables (comma/newline separated, format db.table)",
            value="",
            height=80,
            key="puller_parser_manual_tables",
        )

        requested_tables, invalid_tables = _collect_table_refs(selected_tables, manual_tables)
        if invalid_tables:
            st.error(
                "Format table tidak valid: "
                + ", ".join(invalid_tables)
                + ". Gunakan format `database.table` (alphanumeric + underscore)."
            )
        elif not requested_tables:
            st.info("Pilih minimal satu raw source table.")
        else:
            existing_tables: List[str] = []
            missing_tables: List[str] = []
            for table_ref in requested_tables:
                if _clickhouse_table_exists(table_ref):
                    existing_tables.append(table_ref)
                else:
                    missing_tables.append(table_ref)

            if missing_tables:
                st.warning(
                    "Table berikut tidak ditemukan di ClickHouse dan akan dilewati: "
                    + ", ".join(missing_tables)
                )
            if not existing_tables:
                st.error("Tidak ada source table yang valid/tersedia.")
            else:
                st.caption("Source tables yang dipakai: " + ", ".join(existing_tables))

                raw_source_from = _build_raw_source_from(existing_tables)
                with st.expander("Preview RAW_SOURCE_FROM expression"):
                    st.code(raw_source_from, language="sql")

                col_apply, col_backfill = st.columns(2)
                apply_clicked = col_apply.button("Apply Parser Views", key="puller_parser_apply")
                backfill_clicked = col_backfill.button("Run Parser Backfill", key="puller_parser_backfill")

                if apply_clicked or backfill_clicked:
                    try:
                        template_sql = template_path.read_text(encoding="utf-8")
                        if backfill_clicked:
                            rendered_sql = _render_parser_backfill_sql(template_sql, raw_source_from)
                            with st.spinner("Running parser backfill..."):
                                _execute_clickhouse_script(rendered_sql, timeout=300)
                            ui.notify("Parser backfill completed.")
                        else:
                            rendered_sql = _render_parser_apply_sql(template_sql, raw_source_from)
                            with st.spinner("Applying parser materialized views..."):
                                _execute_clickhouse_script(rendered_sql, timeout=180)
                            ui.notify("Parser views applied.")
                    except Exception as exc:
                        st.error(f"Parser execution failed: {exc}")
