#!/bin/bash
set -euo pipefail

enable_raw_table_ingest="${ENABLE_RAW_TABLE_INGEST:-true}"
if [ "$enable_raw_table_ingest" != "true" ]; then
  echo "Skipping raw-table bronze parser bootstrap (ENABLE_RAW_TABLE_INGEST=$enable_raw_table_ingest)"
  exit 0
fi

raw_source_tables="${RAW_SOURCE_TABLES:-${RAW_SOURCE_TABLE:-bronze.arkime_sessions3_26}}"
raw_source_tables="${raw_source_tables//$'\r'/}"

client_args=()
if [ -n "${CLICKHOUSE_USER:-}" ]; then
  client_args+=(--user "$CLICKHOUSE_USER")
fi
if [ -n "${CLICKHOUSE_PASSWORD:-}" ]; then
  client_args+=(--password "$CLICKHOUSE_PASSWORD")
fi

IFS=',' read -r -a source_list <<< "$raw_source_tables"
normalized_sources=()
for item in "${source_list[@]}"; do
  source="$(echo "$item" | xargs)"
  if [ -z "$source" ]; then
    continue
  fi
  if [[ ! "$source" =~ ^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "Invalid source table in RAW_SOURCE_TABLES: $source"
    exit 1
  fi
  normalized_sources+=("$source")
done

if [ "${#normalized_sources[@]}" -eq 0 ]; then
  echo "No valid source table provided in RAW_SOURCE_TABLES/RAW_SOURCE_TABLE"
  exit 1
fi

existing_sources=()
for source in "${normalized_sources[@]}"; do
  source_db="${source%%.*}"
  source_table="${source##*.}"
  exists="$(clickhouse-client "${client_args[@]}" --query "SELECT count() FROM system.tables WHERE database='${source_db}' AND name='${source_table}' FORMAT TabSeparated" || echo "0")"
  if [ "${exists}" = "0" ]; then
    echo "Skipping missing source table ${source}"
    continue
  fi
  existing_sources+=("$source")
done

if [ "${#existing_sources[@]}" -eq 0 ]; then
  echo "Skipping raw-table bronze parser bootstrap (none of source tables exist)"
  exit 0
fi

if [ "${#existing_sources[@]}" -eq 1 ]; then
  raw_source_from="${existing_sources[0]}"
else
  union_sql=""
  for source in "${existing_sources[@]}"; do
    if [ -n "$union_sql" ]; then
      union_sql="${union_sql} UNION ALL "
    fi
    union_sql="${union_sql}SELECT event_id, event_ts, raw, ingested_at FROM ${source}"
  done
  raw_source_from="(${union_sql})"
fi

sed -e "s|{{RAW_SOURCE_FROM}}|$raw_source_from|g" \
    /docker-entrypoint-initdb.d/05_raw_table_ingest.sql.tmpl \
  | clickhouse-client "${client_args[@]}" --multiquery

echo "Applied raw-table bronze parser using source(s): ${existing_sources[*]}"
