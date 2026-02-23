from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import tempfile
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import requests
from cryptography.fernet import Fernet, InvalidToken

from datapipeline_manager import config, db, seaweed


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


def _ensure_automation_table() -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata.file_export_automations (
          automation_id BIGSERIAL PRIMARY KEY,
          automation_name TEXT NOT NULL UNIQUE,
          source_id BIGINT NOT NULL,
          source_name TEXT NOT NULL,
          indices_json JSONB NOT NULL,
          file_format TEXT NOT NULL,
          bucket_name TEXT NOT NULL,
          folder_prefix TEXT,
          interval_minutes INTEGER NOT NULL,
          lookback_minutes INTEGER NOT NULL,
          enabled BOOLEAN NOT NULL DEFAULT TRUE,
          requested_by TEXT,
          next_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          last_run_started_at TIMESTAMPTZ,
          last_run_finished_at TIMESTAMPTZ,
          last_status TEXT NOT NULL DEFAULT 'never',
          last_error TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT file_export_automations_source_fk
            FOREIGN KEY (source_id)
            REFERENCES metadata.opensearch_sources (source_id)
            ON UPDATE CASCADE
            ON DELETE CASCADE,
          CONSTRAINT file_export_automations_interval_ck
            CHECK (interval_minutes > 0),
          CONSTRAINT file_export_automations_lookback_ck
            CHECK (lookback_minutes > 0)
        );
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_file_export_automations_due
          ON metadata.file_export_automations (enabled, next_run_at);
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


def _normalize_indices(value: Any) -> List[str]:
    parsed = value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
    if not isinstance(parsed, list):
        return []
    normalized: List[str] = []
    for item in parsed:
        token = str(item).strip()
        if token and token not in normalized:
            normalized.append(token)
    return normalized


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


def _secret_key() -> Optional[bytes]:
    key_material = os.getenv("ITSEC_SECRET_KEY") or config.UI_PASSWORD
    if not key_material:
        return None
    digest = hashlib.sha256(key_material.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


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
    return _decrypt_secret(source.get("secret_enc"))


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

    csv_path = str(Path(workdir) / f"{base_name}.csv")
    zip_path = str(Path(workdir) / f"{base_name}.zip")
    df.to_csv(csv_path, index=False)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(csv_path, arcname=Path(csv_path).name)
    return zip_path


def _fetch_source(source_id: int) -> Optional[Dict[str, Any]]:
    return db.fetch_one(
        """
        SELECT source_id, project_id, name, base_url, auth_type, username, secret_ref, secret_enc,
               index_pattern, time_field, query_filter_json, enabled
        FROM metadata.opensearch_sources
        WHERE source_id = %s
          AND enabled = TRUE
        LIMIT 1
        """,
        (source_id,),
    )


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


def _set_automation_result(automation_id: int, status: str, last_error: Optional[str] = None) -> None:
    db.execute(
        """
        UPDATE metadata.file_export_automations
        SET last_run_finished_at = now(),
            last_status = %s,
            last_error = %s,
            updated_at = now()
        WHERE automation_id = %s
        """,
        (status, (last_error or "")[:1500] if last_error else None, automation_id),
    )


def _claim_due_automation() -> Optional[Dict[str, Any]]:
    return db.fetch_one(
        """
        WITH candidate AS (
          SELECT automation_id
          FROM metadata.file_export_automations
          WHERE enabled = TRUE
            AND next_run_at <= now()
          ORDER BY next_run_at ASC
          LIMIT 1
          FOR UPDATE SKIP LOCKED
        )
        UPDATE metadata.file_export_automations a
        SET last_run_started_at = now(),
            last_status = 'running',
            last_error = NULL,
            next_run_at = now() + make_interval(mins => a.interval_minutes),
            updated_at = now()
        FROM candidate c
        WHERE a.automation_id = c.automation_id
        RETURNING a.automation_id, a.automation_name, a.source_id, a.source_name,
                  a.indices_json, a.file_format, a.bucket_name, a.folder_prefix,
                  a.lookback_minutes, a.requested_by, a.interval_minutes
        """
    )


def _process_automation(automation: Dict[str, Any]) -> None:
    automation_id = int(automation["automation_id"])
    source_id = int(automation["source_id"])
    source = _fetch_source(source_id)
    if not source:
        raise RuntimeError(f"Source {source_id} is missing or disabled.")

    bucket_name = str(automation.get("bucket_name") or "").strip()
    if not bucket_name:
        raise RuntimeError("Automation has no bucket_name configured.")

    client = seaweed.s3_client()
    if not seaweed.bucket_exists(client, bucket_name):
        raise RuntimeError(f"Configured bucket '{bucket_name}' doesn't exist.")

    folder_prefix = seaweed.normalize_prefix(automation.get("folder_prefix") or "")
    indices = _normalize_indices(automation.get("indices_json"))
    if not indices:
        raise RuntimeError("Automation has no indices configured.")

    lookback_minutes = max(1, int(automation.get("lookback_minutes") or 1))
    end_ts = datetime.now(timezone.utc)
    start_ts = end_ts - timedelta(minutes=lookback_minutes)
    requested_by = (
        str(automation.get("requested_by") or "").strip()
        or f"automation:{automation.get('automation_name') or automation_id}"
    )

    secret = _resolve_secret(source)
    auth_type = (source.get("auth_type") or "none").strip().lower()
    if auth_type != "none" and not secret:
        raise RuntimeError("Source credential is missing.")

    session = _build_session(source.get("auth_type"), source.get("username"), secret)
    total_ok = 0
    total_failed = 0
    errors: List[str] = []
    try:
        query = _build_query(
            source["time_field"],
            start_ts,
            end_ts,
            source.get("query_filter_json"),
        )
        for index_name in indices:
            job_id = _insert_job(
                source,
                index_name,
                start_ts,
                end_ts,
                str(automation.get("file_format") or "csv"),
                bucket_name,
                folder_prefix,
                requested_by,
            )
            _set_job_running(job_id)
            try:
                rows: List[Dict[str, Any]] = []
                for hits in _iter_hits(
                    session,
                    source["base_url"],
                    index_name,
                    query,
                    batch_size=config.FILE_EXPORT_BATCH_SIZE,
                ):
                    rows.extend(_rows_from_hits(hits))

                with tempfile.TemporaryDirectory(prefix="os_export_auto_") as tmpdir:
                    file_path = _rows_to_file(
                        rows,
                        str(automation.get("file_format") or "csv"),
                        index_name,
                        start_ts,
                        end_ts,
                        tmpdir,
                    )
                    file_size = seaweed.file_size_bytes(file_path)
                    object_key = folder_prefix + Path(file_path).name
                    seaweed.upload_file(client, file_path, bucket_name, object_key)
                    _set_job_completed(job_id, object_key, len(rows), file_size)
                total_ok += 1
            except Exception as exc:
                _set_job_failed(job_id, str(exc))
                total_failed += 1
                errors.append(f"{index_name}: {exc}")
    finally:
        session.close()

    if total_failed == 0:
        _set_automation_result(automation_id, "success")
        return
    if total_ok == 0:
        _set_automation_result(automation_id, "failed", "; ".join(errors))
        return
    _set_automation_result(
        automation_id,
        "partial",
        f"Success={total_ok}, Failed={total_failed}. " + "; ".join(errors[:3]),
    )


def run_once() -> int:
    processed = 0
    while True:
        automation = _claim_due_automation()
        if not automation:
            break
        processed += 1
        automation_id = int(automation["automation_id"])
        automation_name = str(automation.get("automation_name") or automation_id)
        logging.info("Running file export automation id=%s name=%s", automation_id, automation_name)
        try:
            _process_automation(automation)
        except Exception as exc:
            logging.exception("Automation failed id=%s name=%s: %s", automation_id, automation_name, exc)
            _set_automation_result(automation_id, "failed", str(exc))
    return processed


def run_loop() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    _ensure_export_table()
    _ensure_automation_table()
    poll_seconds = max(5, int(config.FILE_EXPORT_AUTOMATION_POLL_SECONDS))
    logging.info(
        "File export automation worker started, poll_seconds=%s, default_bucket=%s",
        poll_seconds,
        config.SEAWEED_S3_BUCKET,
    )
    while True:
        try:
            processed = run_once()
            if processed:
                logging.info("Processed %s automation task(s)", processed)
        except Exception as exc:
            logging.exception("File export automation loop failed: %s", exc)
        time.sleep(poll_seconds)


if __name__ == "__main__":
    raise SystemExit(run_loop())
