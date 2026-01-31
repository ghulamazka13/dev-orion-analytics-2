import base64
import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras
import requests
from cryptography.fernet import Fernet, InvalidToken

from . import config
from .utils import (
    format_timestamp,
    format_timestamp_ch,
    parse_timestamp,
    quote_identifier,
    require_identifier,
    safe_json_load,
)


class PgStore:
    def __init__(self, dsn: str) -> None:
        self.conn = psycopg2.connect(dsn)
        self.conn.autocommit = True

    def close(self) -> None:
        self.conn.close()

    def fetch_sources(self) -> List[Dict]:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT s.source_id,
                       s.project_id,
                       s.name,
                       s.base_url,
                       s.auth_type,
                       s.username,
                       s.secret_ref,
                       s.secret_enc,
                       s.index_pattern,
                       s.time_field,
                       s.query_filter_json,
                       s.enabled,
                       p.timezone
                FROM metadata.opensearch_sources s
                JOIN metadata.projects p
                  ON p.project_id = s.project_id
                WHERE s.enabled = TRUE
                  AND p.enabled = TRUE
                ORDER BY s.source_id
                """
            )
            return list(cur.fetchall())

    def fetch_puller_config(self) -> Optional[Dict]:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
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
                       updated_at,
                       updated_by
                FROM metadata.opensearch_puller_config
                ORDER BY updated_at DESC
                LIMIT 1
                """
            )
            return cur.fetchone()

    def fetch_backfill_job(self, source_id: int) -> Optional[Dict]:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT job_id,
                       source_id,
                       start_ts,
                       end_ts,
                       throttle_seconds,
                       status,
                       last_error,
                       last_index_name,
                       last_ts,
                       last_sort_json,
                       last_id
                FROM metadata.backfill_jobs
                WHERE source_id = %s
                  AND status IN ('pending', 'running')
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (source_id,),
            )
            return cur.fetchone()

    def fetch_backfill_job_by_id(self, job_id: int) -> Optional[Dict]:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT job_id,
                       source_id,
                       start_ts,
                       end_ts,
                       throttle_seconds,
                       status,
                       last_error,
                       last_index_name,
                       last_ts,
                       last_sort_json,
                       last_id
                FROM metadata.backfill_jobs
                WHERE job_id = %s
                """,
                (job_id,),
            )
            return cur.fetchone()

    def set_backfill_status(
        self, job_id: int, status: str, last_error: Optional[str] = None
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE metadata.backfill_jobs
                SET status = %s,
                    last_error = %s,
                    updated_at = now()
                WHERE job_id = %s
                """,
                (status, last_error, job_id),
            )

    def update_backfill_checkpoint(
        self,
        job_id: int,
        index_name: Optional[str],
        last_ts: Optional[datetime],
        last_sort_json: Optional[List[Any]],
        last_id: Optional[str],
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE metadata.backfill_jobs
                SET last_index_name = %s,
                    last_ts = %s,
                    last_sort_json = %s,
                    last_id = %s,
                    updated_at = now()
                WHERE job_id = %s
                """,
                (
                    index_name,
                    last_ts,
                    psycopg2.extras.Json(last_sort_json) if last_sort_json else None,
                    last_id,
                    job_id,
                ),
            )

    def upsert_worker_heartbeat(
        self, worker_id: str, worker_type: str, status: str, details: Optional[Dict[str, Any]] = None
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO metadata.worker_heartbeats (
                  worker_id, worker_type, last_seen, status, details
                ) VALUES (%s, %s, now(), %s, %s)
                ON CONFLICT (worker_id) DO UPDATE SET
                  last_seen = now(),
                  status = EXCLUDED.status,
                  details = EXCLUDED.details
                """,
                (
                    worker_id,
                    worker_type,
                    status,
                    psycopg2.extras.Json(details or {}),
                ),
            )

    def fetch_ingestion_state(self, source_id: int, index_name: str) -> Optional[Dict]:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT last_ts,
                       last_sort_json,
                       last_id,
                       status,
                       last_error
                FROM metadata.ingestion_state
                WHERE source_id = %s
                  AND index_name = %s
                """,
                (source_id, index_name),
            )
            return cur.fetchone()

    def upsert_ingestion_state(
        self,
        source_id: int,
        index_name: str,
        last_ts: datetime,
        last_sort_json: List[Any],
        last_id: Optional[str],
        status: str,
        last_error: Optional[str] = None,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO metadata.ingestion_state (
                  source_id,
                  index_name,
                  last_ts,
                  last_sort_json,
                  last_id,
                  status,
                  last_error,
                  updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (source_id, index_name) DO UPDATE SET
                  last_ts = EXCLUDED.last_ts,
                  last_sort_json = EXCLUDED.last_sort_json,
                  last_id = EXCLUDED.last_id,
                  status = EXCLUDED.status,
                  last_error = EXCLUDED.last_error,
                  updated_at = now()
                """,
                (
                    source_id,
                    index_name,
                    last_ts,
                    psycopg2.extras.Json(last_sort_json),
                    last_id,
                    status,
                    last_error,
                ),
            )

    def set_ingestion_status(
        self,
        source_id: int,
        index_name: str,
        status: str,
        last_error: Optional[str] = None,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE metadata.ingestion_state
                SET status = %s,
                    last_error = %s,
                    updated_at = now()
                WHERE source_id = %s
                  AND index_name = %s
                """,
                (status, last_error, source_id, index_name),
            )


class ClickHouseWriter:
    def __init__(self, base_url: str, timeout: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def execute_sql(self, sql: str) -> None:
        response = self.session.post(
            f"{self.base_url}/",
            params={"query": sql},
            timeout=self.timeout,
        )
        response.raise_for_status()

    def table_exists(self, database: str, table: str) -> bool:
        query = (
            "SELECT count() FROM system.tables "
            f"WHERE database = '{database}' AND name = '{table}' "
            "FORMAT TabSeparated"
        )
        response = self.session.post(
            f"{self.base_url}/",
            params={"query": query},
            timeout=self.timeout,
        )
        response.raise_for_status()
        try:
            return int(response.text.strip() or "0") > 0
        except ValueError:
            return False

    def ensure_default_bronze_columns(self) -> None:
        for table in ["suricata_events_raw", "wazuh_events_raw", "zeek_events_raw"]:
            if not self.table_exists("bronze", table):
                logging.info("Skipping bronze.%s (table not found)", table)
                continue
            self.execute_sql(
                f"ALTER TABLE bronze.{table} "
                "ADD COLUMN IF NOT EXISTS raw String, "
                "ADD COLUMN IF NOT EXISTS extras Map(String, String) DEFAULT map()"
            )

    def ensure_project_storage(self, project_id: str) -> None:
        require_identifier(project_id)
        bronze_db = f"{project_id}_bronze"
        gold_db = f"{project_id}_gold"
        self.execute_sql(f"CREATE DATABASE IF NOT EXISTS {quote_identifier(bronze_db)}")
        self.execute_sql(f"CREATE DATABASE IF NOT EXISTS {quote_identifier(gold_db)}")

        table = f"{quote_identifier(bronze_db)}.{quote_identifier('os_events_raw')}"
        self.execute_sql(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
              event_id String,
              event_ts DateTime64(3),
              index_name String,
              source_id String,
              raw String,
              ingested_at DateTime64(3),
              extras Map(String, String) DEFAULT map()
            )
            ENGINE = MergeTree
            PARTITION BY toDate(event_ts)
            ORDER BY (source_id, toDate(event_ts), event_ts, event_id)
            """
        )

    def insert_rows(self, database: str, table: str, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        sql = f"INSERT INTO {quote_identifier(database)}.{quote_identifier(table)} FORMAT JSONEachRow"
        payload = "\n".join(json.dumps(row, separators=(",", ":")) for row in rows)
        response = self.session.post(
            f"{self.base_url}/",
            params={"query": sql},
            data=payload.encode("utf-8"),
            timeout=self.timeout,
        )
        response.raise_for_status()


class OpenSearchClient:
    def __init__(
        self,
        base_url: str,
        auth_type: Optional[str],
        username: Optional[str],
        secret: Optional[str],
        timeout: int,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.verify_ssl = config.OPENSEARCH_VERIFY_SSL

        auth_type = (auth_type or "").strip().lower()
        if auth_type == "basic" and username and secret:
            self.session.auth = (username, secret)
        elif auth_type == "api_key" and secret:
            self.session.headers["Authorization"] = f"ApiKey {secret}"
        elif auth_type == "bearer" and secret:
            self.session.headers["Authorization"] = f"Bearer {secret}"

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        for attempt in range(config.MAX_RETRIES):
            try:
                response = self.session.request(
                    method,
                    url,
                    timeout=self.timeout,
                    verify=self.verify_ssl,
                    **kwargs,
                )
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                if attempt >= config.MAX_RETRIES - 1:
                    raise
                sleep_for = config.BACKOFF_BASE_SECONDS * (2**attempt)
                logging.warning("OpenSearch request failed (%s). Retrying in %.1fs", exc, sleep_for)
                time.sleep(sleep_for)
        raise RuntimeError("OpenSearch request retries exhausted")

    def list_indices(self, index_pattern: str) -> List[str]:
        try:
            response = self._request(
                "GET",
                f"/_cat/indices/{index_pattern}",
                params={"format": "json", "h": "index,status"},
            )
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                logging.warning("No indices found for pattern %s", index_pattern)
                return []
            raise
        indices = []
        for row in response.json():
            if row.get("status") == "close":
                continue
            index_name = row.get("index")
            if index_name:
                indices.append(index_name)
        return sorted(set(indices))

    def open_pit(self, index_name: str) -> str:
        response = self._request(
            "POST",
            f"/{index_name}/_pit",
            params={"keep_alive": "1m"},
        )
        pit_id = response.json().get("id")
        if not pit_id:
            raise RuntimeError("OpenSearch PIT id missing")
        return pit_id

    def close_pit(self, pit_id: str) -> None:
        try:
            self._request("DELETE", "/_pit", json={"id": pit_id})
        except requests.RequestException:
            logging.warning("Failed to close PIT %s", pit_id)

    def search(self, body: Dict[str, Any], index_name: Optional[str] = None) -> Dict[str, Any]:
        path = f"/{index_name}/_search" if index_name else "/_search"
        response = self._request("POST", path, json=body)
        return response.json()


def _secret_key() -> Optional[bytes]:
    if not config.SECRET_KEY:
        return None
    digest = hashlib.sha256(config.SECRET_KEY.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _coerce_bytes(value: Any) -> Optional[bytes]:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, str):
        return value.encode("utf-8")
    return None


def _decrypt_secret(secret_enc: Any) -> Optional[str]:
    blob = _coerce_bytes(secret_enc)
    if not blob:
        return None
    key = _secret_key()
    if not key:
        try:
            return blob.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        return Fernet(key).decrypt(blob).decode("utf-8")
    except InvalidToken:
        try:
            return blob.decode("utf-8")
        except UnicodeDecodeError:
            return None


def _load_secret(secret_ref: Optional[str], secret_enc: Any) -> Optional[str]:
    if secret_ref:
        try:
            with open(secret_ref, "r", encoding="utf-8") as handle:
                return handle.read().strip()
        except OSError as exc:
            logging.warning("Unable to read secret_ref %s: %s", secret_ref, exc)
    return _decrypt_secret(secret_enc)


def _apply_config_value(
    current: Any, value: Any, cast, minimum: Optional[float] = None
) -> Any:
    if value is None:
        return current
    try:
        next_value = cast(value)
    except (TypeError, ValueError):
        return current
    if minimum is not None and next_value < minimum:
        return current
    return next_value


def _coerce_bool(current: bool, value: Any) -> bool:
    if value is None:
        return current
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no"}
    return current


def _apply_puller_config(config_row: Optional[Dict[str, Any]]) -> None:
    if not config_row:
        return
    config.POLL_INTERVAL_SECONDS = _apply_config_value(
        config.POLL_INTERVAL_SECONDS,
        config_row.get("poll_interval_seconds"),
        int,
        minimum=1,
    )
    config.OVERLAP_MINUTES = _apply_config_value(
        config.OVERLAP_MINUTES,
        config_row.get("overlap_minutes"),
        int,
        minimum=0,
    )
    config.BATCH_SIZE = _apply_config_value(
        config.BATCH_SIZE,
        config_row.get("batch_size"),
        int,
        minimum=1,
    )
    config.MAX_RETRIES = _apply_config_value(
        config.MAX_RETRIES,
        config_row.get("max_retries"),
        int,
        minimum=0,
    )
    config.BACKOFF_BASE_SECONDS = _apply_config_value(
        config.BACKOFF_BASE_SECONDS,
        config_row.get("backoff_base_seconds"),
        float,
        minimum=0,
    )
    config.RATE_LIMIT_SECONDS = _apply_config_value(
        config.RATE_LIMIT_SECONDS,
        config_row.get("rate_limit_seconds"),
        float,
        minimum=0,
    )
    config.OPENSEARCH_TIMEOUT_SECONDS = _apply_config_value(
        config.OPENSEARCH_TIMEOUT_SECONDS,
        config_row.get("opensearch_timeout_seconds"),
        int,
        minimum=1,
    )
    config.CLICKHOUSE_TIMEOUT_SECONDS = _apply_config_value(
        config.CLICKHOUSE_TIMEOUT_SECONDS,
        config_row.get("clickhouse_timeout_seconds"),
        int,
        minimum=1,
    )
    config.OPENSEARCH_VERIFY_SSL = _coerce_bool(
        config.OPENSEARCH_VERIFY_SSL, config_row.get("opensearch_verify_ssl")
    )


def _config_snapshot() -> Dict[str, Any]:
    return {
        "poll_interval": config.POLL_INTERVAL_SECONDS,
        "overlap_minutes": config.OVERLAP_MINUTES,
        "batch_size": config.BATCH_SIZE,
        "max_retries": config.MAX_RETRIES,
        "backoff_base_seconds": config.BACKOFF_BASE_SECONDS,
        "rate_limit_seconds": config.RATE_LIMIT_SECONDS,
        "opensearch_timeout_seconds": config.OPENSEARCH_TIMEOUT_SECONDS,
        "clickhouse_timeout_seconds": config.CLICKHOUSE_TIMEOUT_SECONDS,
        "opensearch_verify_ssl": config.OPENSEARCH_VERIFY_SSL,
    }


def _build_query(
    time_field: str,
    start_ts: Optional[datetime],
    end_ts: Optional[datetime],
    query_filter_json: Any,
) -> Dict[str, Any]:
    filters: List[Dict[str, Any]] = []
    if start_ts or end_ts:
        range_body: Dict[str, Any] = {}
        if start_ts:
            range_body["gte"] = format_timestamp(start_ts)
        if end_ts:
            range_body["lte"] = format_timestamp(end_ts)
        filters.append({"range": {time_field: range_body}})

    filter_json = safe_json_load(query_filter_json)
    if filter_json:
        filters.append(filter_json)

    if filters:
        return {"bool": {"filter": filters}}
    return {"match_all": {}}


def _extract_event_ts(hit: Dict[str, Any], time_field: str) -> Optional[datetime]:
    source = hit.get("_source") or {}
    value = source.get(time_field)
    ts = parse_timestamp(value)
    if ts:
        return ts
    sort_values = hit.get("sort")
    if sort_values:
        return parse_timestamp(sort_values[0])
    return None


def _build_rows(
    hits: List[Dict[str, Any]],
    time_field: str,
    source_id: int,
) -> List[Dict[str, Any]]:
    ingested_at = format_timestamp_ch(datetime.now(timezone.utc))
    rows: List[Dict[str, Any]] = []
    for hit in hits:
        source = hit.get("_source") or {}
        event_ts = _extract_event_ts(hit, time_field)
        if not event_ts:
            logging.warning("Skipping hit without parsable %s timestamp", time_field)
            continue
        event_id = hit.get("_id") or source.get("event_id") or ""
        rows.append(
            {
                "event_id": str(event_id),
                "event_ts": format_timestamp_ch(event_ts),
                "index_name": hit.get("_index") or "",
                "source_id": str(source_id),
                "raw": json.dumps(source, separators=(",", ":")),
                "ingested_at": ingested_at,
                "extras": {"_index": hit.get("_index") or ""},
            }
        )
    return rows


def _sleep_rate_limit(throttle_seconds: Optional[float] = None) -> None:
    wait_for = throttle_seconds if throttle_seconds and throttle_seconds > 0 else config.RATE_LIMIT_SECONDS
    if wait_for > 0:
        time.sleep(wait_for)


def _retry_clickhouse(
    writer: ClickHouseWriter, database: str, table: str, rows: List[Dict[str, Any]]
) -> None:
    for attempt in range(config.MAX_RETRIES):
        try:
            writer.insert_rows(database, table, rows)
            return
        except requests.RequestException as exc:
            if attempt >= config.MAX_RETRIES - 1:
                raise
            sleep_for = config.BACKOFF_BASE_SECONDS * (2**attempt)
            logging.warning("ClickHouse insert failed (%s). Retrying in %.1fs", exc, sleep_for)
            time.sleep(sleep_for)


def _process_hits(
    writer: ClickHouseWriter,
    database: str,
    hits: List[Dict[str, Any]],
    time_field: str,
    source_id: int,
) -> Tuple[Optional[datetime], Optional[List[Any]], Optional[str], int]:
    if not hits:
        return None, None, None, 0
    rows = _build_rows(hits, time_field, source_id)
    if rows:
        _retry_clickhouse(writer, database, "os_events_raw", rows)
    last_hit = hits[-1]
    last_ts = _extract_event_ts(last_hit, time_field)
    last_sort = last_hit.get("sort")
    last_id = last_hit.get("_id")
    return last_ts, last_sort, last_id, len(rows)


def _process_index(
    store: PgStore,
    writer: ClickHouseWriter,
    os_client: OpenSearchClient,
    source: Dict[str, Any],
    index_name: str,
    start_ts: Optional[datetime],
    end_ts: Optional[datetime],
    search_after: Optional[List[Any]],
    is_backfill: bool,
    job_id: Optional[int],
    cancel_check=None,
    throttle_seconds: Optional[float] = None,
) -> int:
    time_field = source["time_field"]
    pit_id: Optional[str] = None
    use_pit = True
    try:
        pit_id = os_client.open_pit(index_name)
    except requests.RequestException as exc:
        use_pit = False
        logging.warning("PIT not available for %s (%s). Falling back to regular search.", index_name, exc)
    except Exception as exc:
        use_pit = False
        logging.warning("Failed to open PIT for %s (%s). Falling back to regular search.", index_name, exc)
    total = 0
    try:
        while True:
            body: Dict[str, Any] = {
                "size": config.BATCH_SIZE,
                "sort": [{time_field: "asc"}, {"_id": "asc"}],
                "track_total_hits": False,
                "query": _build_query(time_field, start_ts, end_ts, source.get("query_filter_json")),
            }
            if use_pit and pit_id:
                body["pit"] = {"id": pit_id, "keep_alive": "1m"}
            if search_after:
                body["search_after"] = search_after

            if cancel_check and not cancel_check():
                logging.info("Backfill cancelled while processing %s", index_name)
                break

            response = os_client.search(body, None if use_pit else index_name)
            hits = response.get("hits", {}).get("hits", [])
            if not hits:
                break

            last_ts, last_sort, last_id, written = _process_hits(
                writer,
                f"{source['project_id']}_bronze",
                hits,
                time_field,
                source["source_id"],
            )
            total += written

            if last_sort:
                search_after = last_sort

            if is_backfill and job_id:
                store.update_backfill_checkpoint(job_id, index_name, last_ts, last_sort, last_id)
            elif last_ts and last_sort:
                store.upsert_ingestion_state(
                    source["source_id"],
                    index_name,
                    last_ts,
                    last_sort,
                    last_id,
                    status="running",
                )

            _sleep_rate_limit(throttle_seconds)
    finally:
        if pit_id:
            os_client.close_pit(pit_id)
    return total


def _process_backfill(
    store: PgStore,
    writer: ClickHouseWriter,
    os_client: OpenSearchClient,
    source: Dict[str, Any],
    job: Dict[str, Any],
) -> None:
    job_id = job["job_id"]
    if job["status"] == "pending":
        store.set_backfill_status(job_id, "running")

    indices = os_client.list_indices(source["index_pattern"])
    if not indices:
        store.set_backfill_status(job_id, "completed")
        store.update_backfill_checkpoint(job_id, None, None, None, None)
        return

    resume_index = job.get("last_index_name")
    if resume_index and resume_index not in indices:
        resume_index = None

    def _is_active() -> bool:
        latest = store.fetch_backfill_job_by_id(job_id)
        return latest is not None and latest.get("status") in {"pending", "running"}

    for idx, index_name in enumerate(indices):
        if not _is_active():
            latest = store.fetch_backfill_job_by_id(job_id)
            status = latest.get("status") if latest else "unknown"
            logging.info("Backfill job %s stopped with status %s", job_id, status)
            return
        if resume_index and index_name < resume_index:
            continue

        resume_sort = job.get("last_sort_json") if index_name == resume_index else None
        resume_ts = job.get("last_ts") if index_name == resume_index else job["start_ts"]

        _process_index(
            store,
            writer,
            os_client,
            source,
            index_name,
            resume_ts,
            job["end_ts"],
            resume_sort,
            is_backfill=True,
            job_id=job_id,
            cancel_check=_is_active,
            throttle_seconds=job.get("throttle_seconds"),
        )

        if not _is_active():
            logging.info("Backfill job %s stopped during index %s", job_id, index_name)
            return

        next_index = indices[idx + 1] if idx + 1 < len(indices) else None
        store.update_backfill_checkpoint(job_id, next_index, None, None, None)
        resume_index = next_index

    if _is_active():
        store.set_backfill_status(job_id, "completed")


def _process_incremental(
    store: PgStore,
    writer: ClickHouseWriter,
    os_client: OpenSearchClient,
    source: Dict[str, Any],
) -> None:
    indices = os_client.list_indices(source["index_pattern"])
    if not indices:
        return

    now = datetime.now(timezone.utc)
    overlap = timedelta(minutes=config.OVERLAP_MINUTES)

    for index_name in indices:
        state = store.fetch_ingestion_state(source["source_id"], index_name)
        last_ts = state["last_ts"] if state else None
        start_ts = (last_ts - overlap) if last_ts else now - overlap
        end_ts = now
        use_search_after = last_ts is not None and overlap.total_seconds() <= 0
        search_after = state["last_sort_json"] if (state and use_search_after) else None

        try:
            _process_index(
                store,
                writer,
                os_client,
                source,
                index_name,
                start_ts,
                end_ts,
                search_after,
                is_backfill=False,
                job_id=None,
            )
            store.set_ingestion_status(source["source_id"], index_name, "idle")
        except Exception as exc:
            logging.exception("Incremental ingest failed for %s (%s)", index_name, exc)
            store.set_ingestion_status(source["source_id"], index_name, "error", str(exc))


def _ensure_project_storage(writer: ClickHouseWriter, project_id: str) -> None:
    try:
        writer.ensure_project_storage(project_id)
    except Exception as exc:
        logging.error("Failed to ensure storage for %s: %s", project_id, exc)
        raise


def _build_os_client(source: Dict[str, Any]) -> OpenSearchClient:
    secret = _load_secret(source.get("secret_ref"), source.get("secret_enc"))
    return OpenSearchClient(
        base_url=source["base_url"],
        auth_type=source.get("auth_type"),
        username=source.get("username"),
        secret=secret,
        timeout=config.OPENSEARCH_TIMEOUT_SECONDS,
    )


def run_once() -> None:
    store = PgStore(config.POSTGRES_DSN)
    try:
        try:
            config_row = store.fetch_puller_config()
            _apply_puller_config(config_row)
        except Exception as exc:
            logging.warning("Unable to load puller config from metadata: %s", exc)

        writer = ClickHouseWriter(config.CLICKHOUSE_HTTP_URL, config.CLICKHOUSE_TIMEOUT_SECONDS)

        try:
            store.upsert_worker_heartbeat(
                config.WORKER_ID,
                "opensearch_puller",
                "running",
                _config_snapshot(),
            )
        except Exception as exc:
            logging.warning("Unable to update worker heartbeat: %s", exc)
        sources = store.fetch_sources()
        if not sources:
            logging.info("No enabled OpenSearch sources found")
            return

        writer.ensure_default_bronze_columns()

        for source in sources:
            _ensure_project_storage(writer, source["project_id"])
            os_client = _build_os_client(source)
            job = store.fetch_backfill_job(source["source_id"])
            if job:
                logging.info("Processing backfill job %s for source %s", job["job_id"], source["source_id"])
                try:
                    _process_backfill(store, writer, os_client, source, job)
                except Exception as exc:
                    logging.exception("Backfill job failed: %s", exc)
                    store.set_backfill_status(job["job_id"], "failed", str(exc))
                continue

            _process_incremental(store, writer, os_client, source)
        try:
            store.upsert_worker_heartbeat(
                config.WORKER_ID,
                "opensearch_puller",
                "idle",
                _config_snapshot(),
            )
        except Exception as exc:
            logging.warning("Unable to update worker heartbeat: %s", exc)
    finally:
        store.close()


def run_loop() -> int:
    logging.basicConfig(level=config.LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
    logging.info("OpenSearch puller starting")
    while True:
        try:
            run_once()
        except Exception as exc:
            logging.exception("Puller loop failed: %s", exc)
        time.sleep(config.POLL_INTERVAL_SECONDS)
