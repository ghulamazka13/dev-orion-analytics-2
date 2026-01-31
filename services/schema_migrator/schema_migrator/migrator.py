import logging
from typing import Dict, List

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

    project_ids = [row["project_id"] for row in projects]
    logging.info("Found %d enabled projects", len(project_ids))

    logging.info("Connecting to ClickHouse")
    ch = ClickHouseClient(config.CLICKHOUSE_HTTP_URL)

    logging.info("Ensuring default bronze columns")
    _ensure_default_bronze_columns(ch)

    for project_id in project_ids:
        logging.info("Ensuring project storage for %s", project_id)
        _ensure_project_storage(ch, project_id)

    logging.info("Applying field registry (%d entries)", len(field_rows))
    results = _apply_field_registry(ch, field_rows, project_ids, collect_results=collect_results)

    logging.info("Schema migration complete")
    return results if collect_results else None
