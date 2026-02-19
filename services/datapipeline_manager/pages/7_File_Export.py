import json
import re
import tempfile
import zipfile
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import requests
import streamlit as st

from datapipeline_manager import config, db, seaweed, ui


ui.set_page_config("File Export")
ui.inject_css()
ui.require_auth()
ui.sidebar()
ui.header("OpenSearch File Export", "Export source data to SeaweedFS (S3-compatible)")


def _ensure_export_table() -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata.file_export_jobs (
          job_id BIGSERIAL PRIMARY KEY,
          source_id BIGINT NOT NULL,
          source_name TEXT NOT NULL,
          index_name TEXT NOT NULL,
          start_ts TIMESTAMPTZ NOT NULL,
          end_ts TIMESTAMPTZ NOT NULL,
          file_format TEXT NOT NULL,
          bucket_name TEXT NOT NULL,
          folder_prefix TEXT,
          object_key TEXT,
          row_count BIGINT,
          file_size_bytes BIGINT,
          status TEXT NOT NULL DEFAULT 'pending',
          requested_by TEXT,
          last_error TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT file_export_jobs_source_fk
            FOREIGN KEY (source_id)
            REFERENCES metadata.opensearch_sources (source_id)
            ON UPDATE CASCADE
            ON DELETE CASCADE
        );
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_file_export_jobs_status
          ON metadata.file_export_jobs (status);
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_file_export_jobs_created_at
          ON metadata.file_export_jobs (created_at DESC);
        """
    )


def _safe_json_load(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return {}
        try:
            loaded = json.loads(value)
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _build_session(auth_type: Optional[str], username: Optional[str], secret: Optional[str]) -> requests.Session:
    session = requests.Session()
    auth = (auth_type or "").strip().lower()
    if auth == "basic" and username and secret:
        session.auth = (username, secret)
    elif auth == "api_key" and secret:
        session.headers["Authorization"] = f"ApiKey {secret}"
    elif auth == "bearer" and secret:
        session.headers["Authorization"] = f"Bearer {secret}"
    return session


def _read_secret(secret_ref: Optional[str]) -> Optional[str]:
    if not secret_ref:
        return None
    try:
        with open(secret_ref, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return None


def _resolve_secret(source: Dict[str, Any]) -> Optional[str]:
    auth_type = (source.get("auth_type") or "none").strip().lower()
    if auth_type == "none":
        return None
    secret_ref = source.get("secret_ref")
    if secret_ref:
        return _read_secret(secret_ref)
    return ui.decrypt_secret(source.get("secret_enc"))


def _request_with_error_details(response: requests.Response, action: str) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        body = response.text or ""
        body = body.strip().replace("\n", " ")
        if len(body) > 300:
            body = body[:300] + "..."
        raise RuntimeError(f"{action} failed ({response.status_code}): {body}") from exc


def _build_query(
    time_field: str,
    start_ts: datetime,
    end_ts: datetime,
    query_filter_json: Any,
) -> Dict[str, Any]:
    filters: List[Dict[str, Any]] = [
        {
            "range": {
                time_field: {
                    "gte": start_ts.astimezone(timezone.utc).isoformat(),
                    "lte": end_ts.astimezone(timezone.utc).isoformat(),
                }
            }
        }
    ]
    extra_filter = _safe_json_load(query_filter_json)
    if extra_filter:
        if "query" in extra_filter and isinstance(extra_filter["query"], dict):
            filters.append(extra_filter["query"])
        else:
            filters.append(extra_filter)
    return {"bool": {"filter": filters}}


def _list_indices(
    source: Dict[str, Any],
    timeout: int = 20,
) -> List[str]:
    secret = _resolve_secret(source)
    auth_type = (source.get("auth_type") or "none").strip().lower()
    if auth_type != "none" and not secret:
        raise RuntimeError("Source credential is missing. Update the source secret first.")

    session = _build_session(source.get("auth_type"), source.get("username"), secret)
    url = source["base_url"].rstrip("/") + f"/_cat/indices/{source['index_pattern']}"
    response = session.get(
        url,
        params={"format": "json", "h": "index,status"},
        timeout=timeout,
        verify=config.OPENSEARCH_VERIFY_SSL,
    )
    if response.status_code == 404:
        return []
    _request_with_error_details(response, "Index discovery")

    result: List[str] = []
    for row in response.json():
        if row.get("status") == "close":
            continue
        index_name = row.get("index")
        if index_name:
            result.append(str(index_name))
    return sorted(set(result))


def _iter_hits(
    session: requests.Session,
    base_url: str,
    index_name: str,
    query: Dict[str, Any],
    batch_size: int,
    timeout: int = 60,
) -> Iterable[List[Dict[str, Any]]]:
    search_url = base_url.rstrip("/") + f"/{index_name}/_search"
    scroll_url = base_url.rstrip("/") + "/_search/scroll"
    scroll_id: Optional[str] = None
    try:
        first = session.post(
            search_url,
            params={"scroll": "2m", "ignore_unavailable": "true"},
            json={"size": int(batch_size), "sort": ["_doc"], "query": query},
            timeout=timeout,
            verify=config.OPENSEARCH_VERIFY_SSL,
        )
        _request_with_error_details(first, f"Initial search for index {index_name}")
        payload = first.json()
        scroll_id = payload.get("_scroll_id")
        hits = payload.get("hits", {}).get("hits", [])
        while hits:
            yield hits
            if not scroll_id:
                break
            nxt = session.post(
                scroll_url,
                json={"scroll": "2m", "scroll_id": scroll_id},
                timeout=timeout,
                verify=config.OPENSEARCH_VERIFY_SSL,
            )
            _request_with_error_details(nxt, f"Scroll search for index {index_name}")
            payload = nxt.json()
            scroll_id = payload.get("_scroll_id", scroll_id)
            hits = payload.get("hits", {}).get("hits", [])
    finally:
        if scroll_id:
            try:
                session.delete(
                    scroll_url,
                    json={"scroll_id": [scroll_id]},
                    timeout=timeout,
                    verify=config.OPENSEARCH_VERIFY_SSL,
                )
            except Exception:
                pass


def _normalize_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _rows_from_hits(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for hit in hits:
        source = hit.get("_source") or {}
        row = {key: _normalize_value(val) for key, val in source.items()}
        row["_id"] = hit.get("_id")
        row["_index"] = hit.get("_index")
        rows.append(row)
    return rows


def _safe_file_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", value or "")
    token = token.strip("._-")
    return token or "export"


def _format_time_token(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _rows_to_file(
    rows: List[Dict[str, Any]],
    file_format: str,
    index_name: str,
    start_ts: datetime,
    end_ts: datetime,
    workdir: str,
) -> str:
    safe_index = _safe_file_token(index_name)
    start_token = _format_time_token(start_ts)
    end_token = _format_time_token(end_ts)
    run_token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    base_name = f"{safe_index}_{start_token}_{end_token}_{run_token}"
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["_id", "_index"])

    if file_format == "csv":
        output_path = str(Path(workdir) / f"{base_name}.csv")
        df.to_csv(output_path, index=False)
        return output_path

    if file_format == "parquet":
        output_path = str(Path(workdir) / f"{base_name}.parquet")
        df.to_parquet(output_path, index=False, engine="pyarrow")
        return output_path

    # zip format: always zip a CSV payload.
    csv_path = str(Path(workdir) / f"{base_name}.csv")
    zip_path = str(Path(workdir) / f"{base_name}.zip")
    df.to_csv(csv_path, index=False)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(csv_path, arcname=Path(csv_path).name)
    return zip_path


def _human_size(value: Optional[int]) -> str:
    if not value:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    unit = units[0]
    for candidate in units:
        unit = candidate
        if size < 1024 or candidate == units[-1]:
            break
        size /= 1024
    if unit == "B":
        return f"{int(size)} {unit}"
    return f"{size:.2f} {unit}"


def _insert_job(
    source: Dict[str, Any],
    index_name: str,
    start_ts: datetime,
    end_ts: datetime,
    file_format: str,
    bucket_name: str,
    folder_prefix: str,
    requested_by: str,
) -> int:
    row = db.fetch_one(
        """
        INSERT INTO metadata.file_export_jobs (
          source_id, source_name, index_name, start_ts, end_ts, file_format,
          bucket_name, folder_prefix, status, requested_by, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, now(), now())
        RETURNING job_id
        """,
        (
            source["source_id"],
            source["name"],
            index_name,
            start_ts.isoformat(),
            end_ts.isoformat(),
            file_format,
            bucket_name,
            folder_prefix,
            requested_by,
        ),
    )
    return int(row["job_id"])


def _set_job_running(job_id: int) -> None:
    db.execute(
        """
        UPDATE metadata.file_export_jobs
        SET status = 'running',
            last_error = NULL,
            updated_at = now()
        WHERE job_id = %s
        """,
        (job_id,),
    )


def _set_job_completed(job_id: int, object_key: str, row_count: int, file_size_bytes: int) -> None:
    db.execute(
        """
        UPDATE metadata.file_export_jobs
        SET status = 'completed',
            object_key = %s,
            row_count = %s,
            file_size_bytes = %s,
            last_error = NULL,
            updated_at = now()
        WHERE job_id = %s
        """,
        (object_key, row_count, file_size_bytes, job_id),
    )


def _set_job_failed(job_id: int, last_error: str) -> None:
    db.execute(
        """
        UPDATE metadata.file_export_jobs
        SET status = 'failed',
            last_error = %s,
            updated_at = now()
        WHERE job_id = %s
        """,
        (last_error[:1500], job_id),
    )


_ensure_export_table()

sources = db.fetch_all(
    """
    SELECT source_id, project_id, name, base_url, auth_type, username, secret_ref, secret_enc,
           index_pattern, time_field, query_filter_json, enabled
    FROM metadata.opensearch_sources
    WHERE enabled = TRUE
    ORDER BY source_id
    """
)

if not sources:
    st.info("No enabled source found. Create and enable a source in the Sources menu first.")
    st.stop()

source_options = [
    (str(row["source_id"]), f"{row['project_id']} / {row['name']} (id={row['source_id']})")
    for row in sources
]
selected_label = st.selectbox(
    "Existing Source",
    options=[label for _, label in source_options],
    key="file_export_source",
)
selected_source_id = next(
    (source_id for source_id, label in source_options if label == selected_label),
    None,
)
selected_source = next(
    (row for row in sources if str(row["source_id"]) == str(selected_source_id)),
    None,
)

if selected_source and st.button("Load Matched Indices", key="file_export_load_indices"):
    try:
        indices = _list_indices(selected_source)
        st.session_state["file_export_source_id"] = int(selected_source["source_id"])
        st.session_state["file_export_indices"] = indices
        if indices:
            ui.notify(f"Found {len(indices)} indices.", "success")
        else:
            st.warning("No matching open indices found.")
    except Exception as exc:
        st.error(f"Failed to load indices: {exc}")

loaded_indices = []
if selected_source and st.session_state.get("file_export_source_id") == int(selected_source["source_id"]):
    loaded_indices = list(st.session_state.get("file_export_indices") or [])

with st.form("file_export_form"):
    st.markdown("### Export Configuration")
    if loaded_indices:
        selected_indices = st.multiselect(
            "Indices to export (one file per index)",
            options=loaded_indices,
            default=loaded_indices,
        )
    else:
        st.info("Load matched indices first.")
        selected_indices = []

    col_a, col_b = st.columns(2)
    with col_a:
        start_date = st.date_input("Start Date (UTC)", value=datetime.utcnow().date())
        start_time = st.time_input("Start Time (UTC)", value=time(0, 0))
    with col_b:
        end_date = st.date_input("End Date (UTC)", value=datetime.utcnow().date())
        end_time = st.time_input("End Time (UTC)", value=time(23, 59))

    format_value = st.selectbox("File Format", options=["csv", "parquet", "zip"], index=0)
    bucket_name = st.text_input("Bucket Name", value="")
    folder_prefix = st.text_input("Folder Prefix", value="", help="Optional. Example: exports/security/")
    requested_by = st.text_input(
        "Requested By",
        value=str(st.session_state.get("username") or "admin"),
    )

    st.caption(
        "Note: ZIP format contains a CSV file. All validation and UI messages are in English."
    )
    submitted = st.form_submit_button("Start Export")

if submitted:
    if not selected_source:
        st.error("Source is required.")
    elif not selected_indices:
        st.error("Select at least one index.")
    elif not bucket_name.strip():
        st.error("Bucket name is required.")
    else:
        start_ts = datetime.combine(start_date, start_time, tzinfo=timezone.utc)
        end_ts = datetime.combine(end_date, end_time, tzinfo=timezone.utc)
        if end_ts <= start_ts:
            st.error("End timestamp must be after start timestamp.")
            st.stop()

        try:
            client = seaweed.s3_client()
            normalized_prefix = seaweed.normalize_prefix(folder_prefix)
            if not seaweed.bucket_exists(client, bucket_name.strip()):
                st.error("Bucket doesn't exist.")
                st.stop()
            if normalized_prefix and not seaweed.folder_exists(client, bucket_name.strip(), normalized_prefix):
                st.error("Bucket doesn't exist.")
                st.stop()
        except ValueError as exc:
            st.error(str(exc))
            st.stop()
        except Exception as exc:
            st.error(f"SeaweedFS validation failed: {exc}")
            st.stop()

        secret = _resolve_secret(selected_source)
        auth_type = (selected_source.get("auth_type") or "none").strip().lower()
        if auth_type != "none" and not secret:
            st.error("Source credential is missing. Update source secret first.")
            st.stop()

        session = _build_session(selected_source.get("auth_type"), selected_source.get("username"), secret)
        total_ok = 0
        total_failed = 0
        try:
            query = _build_query(
                selected_source["time_field"],
                start_ts,
                end_ts,
                selected_source.get("query_filter_json"),
            )

            progress = st.progress(0)
            status_box = st.empty()

            for idx, index_name in enumerate(selected_indices, start=1):
                job_id = _insert_job(
                    selected_source,
                    index_name,
                    start_ts,
                    end_ts,
                    format_value,
                    bucket_name.strip(),
                    normalized_prefix,
                    requested_by.strip() or "admin",
                )
                _set_job_running(job_id)
                status_box.info(f"Exporting index {index_name} ({idx}/{len(selected_indices)})...")
                try:
                    rows: List[Dict[str, Any]] = []
                    for hits in _iter_hits(
                        session,
                        selected_source["base_url"],
                        index_name,
                        query,
                        batch_size=config.FILE_EXPORT_BATCH_SIZE,
                    ):
                        rows.extend(_rows_from_hits(hits))

                    with tempfile.TemporaryDirectory(prefix="os_export_") as tmpdir:
                        file_path = _rows_to_file(rows, format_value, index_name, start_ts, end_ts, tmpdir)
                        file_size = seaweed.file_size_bytes(file_path)
                        object_key = normalized_prefix + Path(file_path).name
                        seaweed.upload_file(client, file_path, bucket_name.strip(), object_key)
                        _set_job_completed(job_id, object_key, len(rows), file_size)
                    total_ok += 1
                except Exception as exc:
                    _set_job_failed(job_id, str(exc))
                    total_failed += 1

                progress.progress(int((idx / len(selected_indices)) * 100))
        finally:
            session.close()

        if total_failed == 0:
            ui.notify(f"Export completed. {total_ok} file(s) uploaded.", "success")
        else:
            st.warning(f"Export finished with partial failures. Success: {total_ok}, Failed: {total_failed}.")
        st.rerun()

st.markdown("### Export History")
status_filter = st.selectbox(
    "Status Filter",
    options=["all", "pending", "running", "completed", "failed"],
    index=0,
    key="file_export_status_filter",
)

history = db.fetch_all(
    """
    SELECT job_id, source_id, source_name, index_name, file_format, bucket_name, folder_prefix,
           object_key, row_count, file_size_bytes, status, requested_by, last_error, created_at, updated_at
    FROM metadata.file_export_jobs
    ORDER BY created_at DESC
    LIMIT 300
    """
)

if status_filter != "all":
    history = [row for row in history if row.get("status") == status_filter]

history_df = pd.DataFrame(history)
if not history_df.empty:
    history_df["file_size"] = history_df["file_size_bytes"].apply(_human_size)

page_size = st.selectbox("Rows per page", [10, 20, 50], index=1, key="file_export_page_size")
total_pages = max(1, (len(history_df) + page_size - 1) // page_size)
page = st.number_input(
    "Page",
    min_value=1,
    max_value=total_pages,
    value=1,
    key="file_export_page",
)
start = (page - 1) * page_size
end = start + page_size
st.dataframe(history_df.iloc[start:end] if not history_df.empty else history_df, use_container_width=True)
