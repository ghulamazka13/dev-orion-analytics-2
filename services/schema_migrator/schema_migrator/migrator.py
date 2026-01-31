import logging
import re
from typing import Dict, List, Optional

import psycopg2.extras

from . import config
from .db import ClickHouseClient, connect_postgres
from .utils import quote_identifier, require_identifier


def _fetch_projects(conn) -> List[Dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT project_id, timezone, enabled
            FROM metadata.projects
            WHERE enabled = TRUE
            ORDER BY project_id
            """
        )
        return list(cur.fetchall())


def _fetch_field_registry(conn) -> List[Dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT field_id,
                   project_id,
                   dataset,
                   layer,
                   table_name,
                   column_name,
                   column_type,
                   expression_sql,
                   mode
            FROM metadata.field_registry
            WHERE enabled = TRUE
            ORDER BY field_id
            """
        )
        return list(cur.fetchall())


def _fetch_bronze_event_tables(conn) -> List[Dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT table_id,
                   project_id,
                   dataset,
                   table_name,
                   enabled
            FROM metadata.bronze_event_tables
            WHERE enabled = TRUE
            ORDER BY table_id
            """
        )
        return list(cur.fetchall())


def _fetch_bronze_event_fields(conn) -> List[Dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT field_id,
                   table_id,
                   column_name,
                   column_type,
                   json_path,
                   enabled,
                   ordinal
            FROM metadata.bronze_event_fields
            WHERE enabled = TRUE
            ORDER BY table_id, ordinal, column_name
            """
        )
        return list(cur.fetchall())


_SIMPLE_PATH_RE = re.compile(r"^[A-Za-z0-9_]+(?:\\.[A-Za-z0-9_]+|\\[[0-9]+\\])*$")


def _split_paths(value: Optional[str]) -> List[str]:
    if not value:
        return []
    parts: List[str] = []
    for line in str(value).splitlines():
        for chunk in line.split(","):
            item = chunk.strip()
            if item:
                parts.append(item)
    return parts


def _normalize_json_path(path: str) -> str:
    if path.startswith("$"):
        return path
    if path.startswith("@"):
        return f'$."{path}"'
    if _SIMPLE_PATH_RE.match(path):
        return f"$.{path}"
    return f"$.{path}"


def _unwrap_nullable(column_type: str) -> str:
    column_type = (column_type or "").strip()
    if column_type.startswith("Nullable(") and column_type.endswith(")"):
        return column_type[len("Nullable("):-1].strip()
    return column_type


def _build_json_extract_path(path: str) -> List[str]:
    if path.startswith("$"):
        path = path[1:]
    path = path.strip(".")
    if not path:
        return []
    return [part for part in path.split(".") if part]


def _array_extract_expr(path: str, column_type: str) -> str:
    parts = _build_json_extract_path(path)
    if not parts:
        return f"CAST([] AS {column_type})"
    if len(parts) == 1:
        return f"JSONExtract(raw, '{parts[0]}', '{column_type}')"
    expr = f"JSONExtractRaw(raw, '{parts[0]}')"
    for part in parts[1:-1]:
        expr = f"JSONExtractRaw({expr}, '{part}')"
    return f"JSONExtract({expr}, '{parts[-1]}', '{column_type}')"


def _coerce_expression(expr: str, base_type: str) -> str:
    if not base_type:
        return expr
    if base_type.startswith("DateTime64") or base_type.startswith("DateTime"):
        return f"parseDateTime64BestEffortOrNull({expr})"
    if base_type.startswith("IPv6"):
        return f"toIPv6OrNull({expr})"
    if base_type.startswith("UInt"):
        bits = base_type[4:]
        func = f"toUInt{bits}OrNull" if bits.isdigit() else "toUInt64OrNull"
        return f"{func}({expr})"
    if base_type.startswith("Int"):
        bits = base_type[3:]
        func = f"toInt{bits}OrNull" if bits.isdigit() else "toInt64OrNull"
        return f"{func}({expr})"
    if base_type.startswith("Float"):
        return f"toFloat64OrNull({expr})"
    return f"nullIf({expr}, '')"


def _build_value_expr(path: str, column_type: str) -> str:
    base_type = _unwrap_nullable(column_type)
    if path.startswith("epoch_ms:"):
        path = path[len("epoch_ms:"):].strip()
        json_path = _normalize_json_path(path)
        return f"fromUnixTimestamp64Milli(toInt64OrNull(JSON_VALUE(raw, '{json_path}')))"
    json_path = _normalize_json_path(path)
    return _coerce_expression(f"JSON_VALUE(raw, '{json_path}')", base_type)


def _build_column_expr(column_type: str, json_path: str) -> str:
    paths = _split_paths(json_path)
    if not paths:
        return f"CAST(NULL AS {column_type})"
    base_type = _unwrap_nullable(column_type)
    if base_type.startswith("Array("):
        exprs = []
        for path in paths:
            if path.startswith("__"):
                source_col = path[2:]
                require_identifier(source_col)
                exprs.append(source_col)
            else:
                exprs.append(_array_extract_expr(path, base_type))
        combined = exprs[0]
        for expr in exprs[1:]:
            combined = f"ifNull({combined}, {expr})"
        return f"ifNull({combined}, [])"
    exprs = []
    for path in paths:
        if path.startswith("__"):
            source_col = path[2:]
            require_identifier(source_col)
            exprs.append(source_col)
        else:
            exprs.append(_build_value_expr(path, column_type))
    if len(exprs) == 1:
        return exprs[0]
    return f"coalesce({', '.join(exprs)})"


def _escape_literal(value: str) -> str:
    return value.replace("'", "''")


def _dataset_filter(dataset: str) -> str:
    key = (dataset or "").strip().lower()
    if key == "suricata":
        return (
            "JSONHas(raw, 'suricata') "
            "OR JSON_VALUE(raw, '$.event.module') = 'suricata' "
            "OR JSON_VALUE(raw, '$.event.provider') = 'suricata'"
        )
    if key == "wazuh":
        return (
            "JSON_VALUE(raw, '$.event.provider') = 'wazuh' "
            "OR JSONHas(raw, 'wazuh')"
        )
    if key == "zeek":
        return (
            "JSONHas(raw, 'zeek') "
            "OR JSON_VALUE(raw, '$.event.module') = 'zeek' "
            "OR JSON_VALUE(raw, '$.event.provider') = 'zeek'"
        )
    if key:
        safe = _escape_literal(key)
        return (
            f"JSON_VALUE(raw, '$.event.dataset') = '{safe}' "
            f"OR JSON_VALUE(raw, '$.event.module') = '{safe}' "
            f"OR JSON_VALUE(raw, '$.event.provider') = '{safe}'"
        )
    return "1 = 1"


def _apply_bronze_event_tables(
    ch: ClickHouseClient,
    table_rows: List[Dict],
    field_rows: List[Dict],
    project_ids: List[str],
    collect_results: bool = False,
) -> List[Dict]:
    results: List[Dict] = []
    fields_by_table: Dict[int, List[Dict]] = {}
    for row in field_rows:
        fields_by_table.setdefault(row["table_id"], []).append(row)

    for table in table_rows:
        table_id = table["table_id"]
        table_name = table["table_name"]
        dataset = table.get("dataset") or ""
        rows = fields_by_table.get(table_id, [])
        if not rows:
            if collect_results:
                results.append(
                    {
                        "table_id": table_id,
                        "table": table_name,
                        "status": "skipped",
                        "error": "no columns configured",
                    }
                )
            continue

        target_projects = _resolve_target_projects(table, project_ids)
        for project_id in target_projects:
            bronze_db = f"{project_id}_bronze"
            try:
                require_identifier(table_name)
                qualified_table = f"{quote_identifier(bronze_db)}.{quote_identifier(table_name)}"
                columns_sorted = sorted(
                    rows,
                    key=lambda item: (item.get("ordinal", 0), item.get("column_name") or ""),
                )
                col_defs = [
                    f"{quote_identifier(col['column_name'])} {col['column_type']}"
                    for col in columns_sorted
                ]
                has_event_ts = any(col["column_name"] == "event_ts" for col in columns_sorted)
                has_event_id = any(col["column_name"] == "event_id" for col in columns_sorted)
                if not has_event_ts:
                    raise ValueError("event_ts column is required for bronze tables")

                ch.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {qualified_table} (
                      {', '.join(col_defs)}
                    )
                    ENGINE = MergeTree
                    PARTITION BY toDate(event_ts)
                    ORDER BY ({'event_ts, event_id' if has_event_id else 'event_ts'})
                    """
                )

                for col in columns_sorted:
                    ch.execute(
                        f"ALTER TABLE {qualified_table} "
                        f"ADD COLUMN IF NOT EXISTS {quote_identifier(col['column_name'])} {col['column_type']}"
                    )

                select_exprs = [
                    f"{_build_column_expr(col['column_type'], col['json_path'])} "
                    f"AS {quote_identifier(col['column_name'])}"
                    for col in columns_sorted
                ]
                source_table = f"{quote_identifier(bronze_db)}.{quote_identifier('os_events_raw')}"
                mv_name = f"{table_name}_mv"
                mv_table = f"{quote_identifier(bronze_db)}.{quote_identifier(mv_name)}"
                ch.execute(f"DROP TABLE IF EXISTS {mv_table}")
                ch.execute(
                    f"""
                    CREATE MATERIALIZED VIEW {mv_table}
                    TO {qualified_table}
                    AS
                    SELECT
                      {', '.join(select_exprs)}
                    FROM {source_table}
                    WHERE {_dataset_filter(dataset)}
                    """
                )

                if collect_results:
                    results.append(
                        {
                            "table_id": table_id,
                            "table": f"{bronze_db}.{table_name}",
                            "status": "applied",
                        }
                    )
            except Exception as exc:
                if collect_results:
                    results.append(
                        {
                            "table_id": table_id,
                            "table": f"{bronze_db}.{table_name}",
                            "status": "error",
                            "error": str(exc),
                        }
                    )
                else:
                    raise
    return results


def _ensure_default_bronze_columns(ch: ClickHouseClient) -> None:
    tables = [
        "suricata_events_raw",
        "wazuh_events_raw",
        "zeek_events_raw",
    ]
    for table in tables:
        if not ch.table_exists("bronze", table):
            logging.info("Skipping bronze.%s (table not found)", table)
            continue
        ch.execute(
            f"ALTER TABLE bronze.{table} "
            "ADD COLUMN IF NOT EXISTS raw String, "
            "ADD COLUMN IF NOT EXISTS extras Map(String, String) DEFAULT map()"
        )


def _ensure_project_storage(ch: ClickHouseClient, project_id: str) -> None:
    require_identifier(project_id)
    bronze_db = f"{project_id}_bronze"
    gold_db = f"{project_id}_gold"

    ch.execute(f"CREATE DATABASE IF NOT EXISTS {quote_identifier(bronze_db)}")
    ch.execute(f"CREATE DATABASE IF NOT EXISTS {quote_identifier(gold_db)}")

    os_table = f"{quote_identifier(bronze_db)}.{quote_identifier('os_events_raw')}"
    ch.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {os_table} (
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


def _resolve_target_projects(
    row: Dict, project_ids: List[str]
) -> List[str]:
    project_id = row.get("project_id")
    if project_id:
        if project_id not in project_ids:
            logging.warning("Skipping field %s: project %s not enabled", row["field_id"], project_id)
            return []
        return [project_id]
    return list(project_ids)


def _resolve_target_table(
    db_name: str, table_name: str
) -> str:
    if "." in table_name:
        db_part, table_part = table_name.split(".", 1)
        return f"{quote_identifier(db_part)}.{quote_identifier(table_part)}"
    return f"{quote_identifier(db_name)}.{quote_identifier(table_name)}"


def _apply_field_registry(
    ch: ClickHouseClient,
    rows: List[Dict],
    project_ids: List[str],
    collect_results: bool = False,
) -> List[Dict]:
    results: List[Dict] = []
    for row in rows:
        layer = (row.get("layer") or "").strip().lower()
        mode = (row.get("mode") or "ALIAS").strip().upper()
        expression_sql = row.get("expression_sql")

        if layer == "bronze":
            db_suffix = "_bronze"
        elif layer in {"gold_fact", "gold_dim", "gold"}:
            db_suffix = "_gold"
        else:
            logging.warning("Skipping field %s: unknown layer %s", row["field_id"], layer)
            if collect_results:
                results.append(
                    {
                        "field_id": row["field_id"],
                        "status": "skipped",
                        "error": f"unknown layer {layer}",
                    }
                )
            continue

        for project_id in _resolve_target_projects(row, project_ids):
            target_db = f"{project_id}{db_suffix}"
            try:
                require_identifier(project_id)
                if "." in row["table_name"]:
                    db_part, table_part = row["table_name"].split(".", 1)
                    require_identifier(db_part)
                    require_identifier(table_part)
                else:
                    require_identifier(row["table_name"])
                require_identifier(row["column_name"])
            except ValueError as exc:
                logging.warning("Skipping field %s: %s", row["field_id"], exc)
                if collect_results:
                    results.append(
                        {
                            "field_id": row["field_id"],
                            "status": "skipped",
                            "error": str(exc),
                        }
                    )
                continue

            table = _resolve_target_table(target_db, row["table_name"])
            column = quote_identifier(row["column_name"])
            column_type = row["column_type"]

            if expression_sql:
                if mode not in {"ALIAS", "MATERIALIZED"}:
                    mode = "ALIAS"
                statement = (
                    f"ALTER TABLE {table} "
                    f"ADD COLUMN IF NOT EXISTS {column} {column_type} {mode} {expression_sql}"
                )
            else:
                statement = (
                    f"ALTER TABLE {table} "
                    f"ADD COLUMN IF NOT EXISTS {column} {column_type}"
                )

            logging.info("Applying field %s on %s", row["field_id"], table)
            try:
                ch.execute(statement)
                if collect_results:
                    results.append(
                        {
                            "field_id": row["field_id"],
                            "table": table,
                            "column": row["column_name"],
                            "status": "applied",
                        }
                    )
            except Exception as exc:
                if collect_results:
                    results.append(
                        {
                            "field_id": row["field_id"],
                            "table": table,
                            "column": row["column_name"],
                            "status": "error",
                            "error": str(exc),
                        }
                    )
                else:
                    raise
    return results


def apply_schema(collect_results: bool = False):
    logging.basicConfig(level=config.LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")

    logging.info("Connecting to Postgres")
    with connect_postgres(config.POSTGRES_DSN) as conn:
        conn.autocommit = True
        projects = _fetch_projects(conn)
        field_rows = _fetch_field_registry(conn)
        try:
            bronze_tables = _fetch_bronze_event_tables(conn)
            bronze_fields = _fetch_bronze_event_fields(conn)
        except Exception as exc:
            logging.warning("Bronze parsing tables not available: %s", exc)
            bronze_tables = []
            bronze_fields = []

    project_ids = [row["project_id"] for row in projects]
    logging.info("Found %d enabled projects", len(project_ids))

    logging.info("Connecting to ClickHouse")
    ch = ClickHouseClient(config.CLICKHOUSE_HTTP_URL)

    logging.info("Ensuring default bronze columns")
    _ensure_default_bronze_columns(ch)

    for project_id in project_ids:
        logging.info("Ensuring project storage for %s", project_id)
        _ensure_project_storage(ch, project_id)

    logging.info("Applying bronze event tables (%d entries)", len(bronze_tables))
    bronze_results = _apply_bronze_event_tables(
        ch,
        bronze_tables,
        bronze_fields,
        project_ids,
        collect_results=collect_results,
    )

    logging.info("Applying field registry (%d entries)", len(field_rows))
    field_results = _apply_field_registry(ch, field_rows, project_ids, collect_results=collect_results)

    logging.info("Schema migration complete")
    if not collect_results:
        return None
    return (bronze_results or []) + (field_results or [])
