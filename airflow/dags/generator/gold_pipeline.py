import logging
import os
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

import clickhouse_connect
import pendulum
import yaml
from sqlalchemy import create_engine, text
from airflow import DAG
from airflow.models.param import Param
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator
from jinja2 import Template


def _normalize_ts(value: Any) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return str(value)


def _get_window(
    context: Dict[str, Any],
    default_window_minutes: int,
) -> Tuple[str, str]:
    params = context.get("params") or {}
    dag_run = context.get("dag_run")
    conf = dag_run.conf if dag_run and dag_run.conf else {}
    start_ts = _normalize_ts(conf.get("start_ts") or params.get("start_ts"))
    end_ts = _normalize_ts(conf.get("end_ts") or params.get("end_ts"))
    if start_ts and end_ts:
        return start_ts, end_ts

    try:
        window_minutes = int(
            conf.get("window_minutes")
            or params.get("window_minutes")
            or default_window_minutes
        )
    except (TypeError, ValueError):
        window_minutes = default_window_minutes
    end = pendulum.now("UTC")
    start = end.subtract(minutes=window_minutes)
    return start.to_iso8601_string(), end.to_iso8601_string()


def _load_sql(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _render_sql(sql_text: str, context: Dict[str, Any]) -> str:
    return Template(sql_text).render(**context)


def _split_statements(sql_text: str) -> List[str]:
    statements = [stmt.strip() for stmt in sql_text.split(";") if stmt.strip()]
    return statements


def _normalize_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(value)]


def _resolve_sql_path(base_dir: str, sql_path: str) -> str:
    if os.path.isabs(sql_path):
        return sql_path
    return os.path.join(base_dir, sql_path)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_identifier(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if _IDENTIFIER_RE.fullmatch(value):
        return value
    return None


def _split_table_identifier(table_name: Optional[str], default_db: str) -> Tuple[Optional[str], Optional[str]]:
    if not table_name:
        return None, None
    table_name = table_name.strip()
    if not table_name:
        return None, None
    if "." in table_name:
        db, table = table_name.split(".", 1)
    else:
        db, table = default_db, table_name
    return _safe_identifier(db), _safe_identifier(table)


def _escape_literal(value: str) -> str:
    return value.replace("'", "''")


def _first_value(result: Any) -> Optional[Any]:
    if result is None:
        return None
    if hasattr(result, "first_row"):
        row = result.first_row
        if row:
            return row[0]
    for attr in ("result_rows", "result_set", "rows"):
        rows = getattr(result, attr, None)
        if rows:
            return rows[0][0]
    return None


def _get_table_rows(client: Any, table_name: Optional[str], default_db: str) -> Optional[int]:
    db, table = _split_table_identifier(table_name, default_db)
    if not db or not table:
        return None
    query = (
        "SELECT sum(rows) AS rows FROM system.parts "
        f"WHERE database = '{db}' AND table = '{table}' AND active"
    )
    result = client.query(query)
    value = _first_value(result)
    if value is None:
        return 0
    return int(value)


def _get_window_rows(
    client: Any,
    table_name: Optional[str],
    start_ts: str,
    end_ts: str,
    default_db: str,
) -> Optional[int]:
    db, table = _split_table_identifier(table_name, default_db)
    if not db or not table:
        return None
    start_literal = _escape_literal(start_ts)
    end_literal = _escape_literal(end_ts)
    query = (
        f"SELECT count() AS rows FROM {db}.{table} "
        f"WHERE event_ts >= parseDateTime64BestEffort('{start_literal}') "
        f"AND event_ts < parseDateTime64BestEffort('{end_literal}')"
    )
    result = client.query(query)
    value = _first_value(result)
    if value is None:
        return 0
    return int(value)


def _statement_preview(statement: str, max_len: int = 160) -> str:
    compact = " ".join(statement.split())
    if len(compact) <= max_len:
        return compact
    return f"{compact[:max_len]}..."


def run_pipeline(pipeline: Dict[str, Any], default_window_minutes: int, **context) -> None:
    pipeline_id = pipeline.get("pipeline_id")
    requested = _normalize_ts((context.get("params") or {}).get("pipeline_id"))
    if requested and requested != pipeline_id:
        logging.info("Skipping pipeline %s due to pipeline_id filter %s", pipeline_id, requested)
        return

    start_ts, end_ts = _get_window(context, pipeline.get("window_minutes", default_window_minutes))
    sql_path = pipeline["sql_path"]
    params = pipeline.get("params") or {}
    target_table = params.get("target_table") or pipeline.get("target_table")
    source_tables = _normalize_list(params.get("source_tables") or params.get("source_table"))

    render_context = {
        "start_ts": start_ts,
        "end_ts": end_ts,
        "window_minutes": pipeline.get("window_minutes", default_window_minutes),
        "params": params,
        "pipeline_id": pipeline_id,
    }

    sql_text = _load_sql(sql_path)
    sql_text = _render_sql(sql_text, render_context)
    statements = _split_statements(sql_text)
    if not statements:
        logging.warning("Pipeline %s has no statements after rendering", pipeline_id)
        return

    logging.info(
        "Running pipeline %s statements=%s window=%s -> %s sql=%s target_table=%s params=%s",
        pipeline_id,
        len(statements),
        start_ts,
        end_ts,
        sql_path,
        target_table or "-",
        sorted(params.keys()),
    )

    database = os.environ.get("CLICKHOUSE_DATABASE", "default")
    client = clickhouse_connect.get_client(
        host=os.environ.get("CLICKHOUSE_HOST", "clickhouse"),
        port=int(os.environ.get("CLICKHOUSE_PORT", "8123")),
        username=os.environ.get("CLICKHOUSE_USER", "etl_runner"),
        password=os.environ.get("CLICKHOUSE_PASSWORD", "etl_runner"),
        database=database,
    )
    try:
        try:
            client.command("SET join_use_nulls = 1")
        except Exception as exc:
            logging.warning("Pipeline %s failed to set join_use_nulls: %s", pipeline_id, exc)
        before_rows = None
        if target_table:
            try:
                before_rows = _get_table_rows(client, target_table, database)
                logging.info("Pipeline %s target_table=%s rows_before=%s", pipeline_id, target_table, before_rows)
            except Exception as exc:
                logging.warning("Pipeline %s failed to read target_table row count: %s", pipeline_id, exc)
        if source_tables:
            for source_table in source_tables:
                try:
                    window_rows = _get_window_rows(client, source_table, start_ts, end_ts, database)
                    logging.info(
                        "Pipeline %s source_table=%s window_rows=%s",
                        pipeline_id,
                        source_table,
                        window_rows,
                    )
                except Exception as exc:
                    logging.warning(
                        "Pipeline %s failed to read source_table window rows for %s: %s",
                        pipeline_id,
                        source_table,
                        exc,
                    )

        pipeline_start = time.monotonic()
        for index, statement in enumerate(statements, start=1):
            step_label = f"{index}/{len(statements)}"
            logging.info("Pipeline %s step %s %s", pipeline_id, step_label, _statement_preview(statement))
            step_start = time.monotonic()
            client.command(statement)
            step_elapsed = time.monotonic() - step_start
            logging.info("Pipeline %s step %s finished in %.2fs", pipeline_id, step_label, step_elapsed)
        pipeline_elapsed = time.monotonic() - pipeline_start

        if target_table:
            try:
                after_rows = _get_table_rows(client, target_table, database)
                if before_rows is not None and after_rows is not None:
                    delta = after_rows - before_rows
                    logging.info(
                        "Pipeline %s target_table=%s rows_after=%s delta=%s total=%.2fs",
                        pipeline_id,
                        target_table,
                        after_rows,
                        delta,
                        pipeline_elapsed,
                    )
                else:
                    logging.info(
                        "Pipeline %s target_table=%s rows_after=%s total=%.2fs",
                        pipeline_id,
                        target_table,
                        after_rows,
                        pipeline_elapsed,
                    )
            except Exception as exc:
                logging.warning("Pipeline %s failed to read target_table row count: %s", pipeline_id, exc)
        else:
            logging.info("Pipeline %s finished total=%.2fs", pipeline_id, pipeline_elapsed)
    finally:
        client.close()


class GoldPipelineGenerator:
    def __init__(self, config_path: Optional[str] = None):
        self._config_path = config_path or os.environ.get(
            "GOLD_PIPELINES_PATH",
            os.path.join(os.path.dirname(__file__), "..", "gold_pipelines.yml"),
        )

    def _get_metadata_uri(self) -> Optional[str]:
        return os.environ.get("METADATA_DATABASE_URI") or os.environ.get(
            "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"
        )

    def _load_configs_from_file(self) -> List[Dict[str, Any]]:
        config_path = os.path.abspath(self._config_path)
        if not os.path.exists(config_path):
            logging.warning("Gold pipeline config not found at %s", config_path)
            return []
        with open(config_path, "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        dag_cfg = payload.get("dag") or {}
        pipelines = payload.get("pipelines") or []
        if not isinstance(pipelines, list):
            logging.warning("Gold pipeline config missing pipelines list")
            pipelines = []
        dag_cfg = {
            "dag_id": dag_cfg.get("dag_id", "gold_star_schema"),
            "schedule_cron": dag_cfg.get("schedule_cron", "*/5 * * * *"),
            "timezone": dag_cfg.get("timezone", "Asia/Jakarta"),
            "owner": dag_cfg.get("owner", "data-eng"),
            "tags": dag_cfg.get("tags") or ["gold", "clickhouse"],
            "max_active_tasks": int(dag_cfg.get("max_active_tasks") or 8),
            "default_window_minutes": int(dag_cfg.get("default_window_minutes") or 10),
            "enabled": dag_cfg.get("enabled", True),
            "pipelines": pipelines,
            "base_dir": os.path.dirname(config_path),
        }
        return [dag_cfg]

    def load_configs_from_postgres(self) -> List[Dict[str, Any]]:
        metadata_uri = self._get_metadata_uri()
        if not metadata_uri:
            logging.warning("Metadata database URI not configured")
            return []

        dag_sql = text(
            """
            SELECT
              dag_name,
              schedule_cron,
              timezone,
              owner,
              tags,
              max_active_tasks,
              default_window_minutes,
              enabled
            FROM metadata.gold_dags
            """
        )
        pipeline_sql = text(
            """
            SELECT
              d.dag_name,
              p.pipeline_name,
              p.enabled,
              p.sql_path,
              p.window_minutes,
              p.depends_on,
              p.target_table,
              p.params,
              p.pipeline_order
            FROM metadata.gold_pipelines p
            JOIN metadata.gold_dags d
              ON d.id = p.dag_id
            ORDER BY d.id, p.pipeline_order, p.pipeline_name
            """
        )

        engine = create_engine(metadata_uri)
        try:
            with engine.begin() as conn:
                dag_rows = conn.execute(dag_sql).mappings().all()
                pipeline_rows = conn.execute(pipeline_sql).mappings().all()
        except Exception as exc:
            logging.warning("Failed to load gold metadata from Postgres: %s", exc)
            return []
        finally:
            engine.dispose()

        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        dag_map: Dict[str, Dict[str, Any]] = {}

        for row in dag_rows:
            dag_name = row.get("dag_name")
            if not dag_name:
                continue
            tags = _normalize_list(row.get("tags"))
            dag_map[dag_name] = {
                "dag_id": dag_name,
                "schedule_cron": row.get("schedule_cron") or "*/5 * * * *",
                "timezone": row.get("timezone") or "Asia/Jakarta",
                "owner": row.get("owner") or "data-eng",
                "tags": tags or ["gold", "clickhouse"],
                "max_active_tasks": int(row.get("max_active_tasks") or 8),
                "default_window_minutes": int(row.get("default_window_minutes") or 10),
                "enabled": row.get("enabled", True),
                "pipelines": [],
                "base_dir": base_dir,
            }

        for row in pipeline_rows:
            dag_name = row.get("dag_name")
            if not dag_name or dag_name not in dag_map:
                continue
            pipeline_name = row.get("pipeline_name")
            if not pipeline_name:
                continue
            params = row.get("params") or {}
            if not isinstance(params, dict):
                params = {}
            target_table = row.get("target_table")
            if target_table:
                params = dict(params)
                params.setdefault("target_table", target_table)

            pipeline: Dict[str, Any] = {
                "pipeline_id": pipeline_name,
                "enabled": row.get("enabled", True),
                "sql_path": row.get("sql_path"),
                "depends_on": _normalize_list(row.get("depends_on")),
                "params": params,
                "pipeline_order": row.get("pipeline_order", 0),
            }
            window_minutes = row.get("window_minutes")
            if window_minutes is not None:
                pipeline["window_minutes"] = int(window_minutes)
            dag_map[dag_name]["pipelines"].append(pipeline)

        for dag_cfg in dag_map.values():
            dag_cfg["pipelines"].sort(
                key=lambda item: (item.get("pipeline_order", 0), item.get("pipeline_id", ""))
            )

        return list(dag_map.values())

    def load_configs(self) -> List[Dict[str, Any]]:
        source = os.environ.get("GOLD_PIPELINES_SOURCE", "postgres").lower()
        if source == "file":
            return self._load_configs_from_file()

        configs = self.load_configs_from_postgres()
        if configs:
            return configs
        return self._load_configs_from_file()

    def generate_dag(self, dag_cfg: Dict[str, Any]) -> DAG:
        dag_id = dag_cfg["dag_id"]
        schedule_cron = dag_cfg.get("schedule_cron") or "*/5 * * * *"
        timezone = dag_cfg.get("timezone") or "Asia/Jakarta"
        try:
            tz = pendulum.timezone(timezone)
        except Exception:
            logging.warning("Invalid timezone %s; falling back to UTC", timezone)
            tz = pendulum.UTC
        owner = dag_cfg.get("owner") or "data-eng"
        tags = dag_cfg.get("tags") or []
        max_active_tasks = int(dag_cfg.get("max_active_tasks") or 8)
        default_window_minutes = int(dag_cfg.get("default_window_minutes") or 10)
        base_dir = dag_cfg.get("base_dir") or os.path.dirname(__file__)
        pipelines = [
            pipeline
            for pipeline in (dag_cfg.get("pipelines") or [])
            if pipeline.get("enabled", True)
        ]

        default_args = {
            "owner": owner,
            "retries": 1,
        }

        with DAG(
            dag_id=dag_id,
            default_args=default_args,
            start_date=pendulum.now(tz).subtract(days=1),
            schedule_interval=schedule_cron,
            catchup=False,
            max_active_runs=1,
            max_active_tasks=max_active_tasks,
            tags=tags,
            params={
                "pipeline_id": Param("", type="string"),
                "start_ts": Param("", type="string"),
                "end_ts": Param("", type="string"),
                "window_minutes": Param(default_window_minutes, type="integer"),
            },
        ) as dag:
            start = EmptyOperator(task_id="start")
            end = EmptyOperator(task_id="end")

            task_map: Dict[str, PythonOperator] = {}
            for pipeline in pipelines:
                pipeline = dict(pipeline)
                pipeline_id = pipeline.get("pipeline_id")
                if not pipeline_id:
                    continue
                sql_path = pipeline.get("sql_path")
                if not sql_path:
                    logging.warning("Missing sql_path for pipeline %s", pipeline_id)
                    continue
                pipeline["sql_path"] = _resolve_sql_path(base_dir, sql_path)
                task_map[pipeline_id] = PythonOperator(
                    task_id=pipeline_id,
                    python_callable=run_pipeline,
                    op_kwargs={
                        "pipeline": pipeline,
                        "default_window_minutes": default_window_minutes,
                    },
                )

            for pipeline in pipelines:
                pipeline_id = pipeline.get("pipeline_id")
                if not pipeline_id:
                    continue
                task = task_map.get(pipeline_id)
                if not task:
                    continue
                depends_on = pipeline.get("depends_on") or []
                if depends_on:
                    for dep in depends_on:
                        upstream = task_map.get(dep)
                        if upstream:
                            upstream >> task
                        else:
                            logging.warning("Missing dependency %s for pipeline %s", dep, pipeline_id)
                else:
                    start >> task
                task >> end

        return dag
