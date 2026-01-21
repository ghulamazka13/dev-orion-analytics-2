#!/bin/bash
set -euo pipefail

broker_list="${KAFKA_BROKER_LIST:-10.110.12.20:9092}"
topic_list="${KAFKA_TOPIC_LIST:-malcolm-logs}"

if [ -n "${KAFKA_GROUP_NAME:-}" ]; then
  group_name="$KAFKA_GROUP_NAME"
else
  suffix="${KAFKA_GROUP_SUFFIX:-}"
  if [ -z "$suffix" ]; then
    suffix="${HOSTNAME:-local}"
  fi
  group_name="security_events_ch_${suffix}"
fi

client_args=()
if [ -n "${CLICKHOUSE_USER:-}" ]; then
  client_args+=(--user "$CLICKHOUSE_USER")
fi
if [ -n "${CLICKHOUSE_PASSWORD:-}" ]; then
  client_args+=(--password "$CLICKHOUSE_PASSWORD")
fi

sed -e "s|{{KAFKA_BROKER_LIST}}|$broker_list|g" \
    -e "s|{{KAFKA_TOPIC_LIST}}|$topic_list|g" \
    -e "s|{{KAFKA_GROUP_NAME}}|$group_name|g" \
    /docker-entrypoint-initdb.d/02_kafka_ingest.sql.tmpl \
  | clickhouse-client "${client_args[@]}" --multiquery
