#!/usr/bin/env bash
set -euo pipefail

docker compose up -d

echo "Waiting for services..."
sleep 30

echo "Bronze row count (ClickHouse):"
docker compose exec -T clickhouse clickhouse-client \
  --user etl_runner --password etl_runner \
  --query "SELECT count() FROM bronze.suricata_events_raw;"
docker compose exec -T clickhouse clickhouse-client \
  --user etl_runner --password etl_runner \
  --query "SELECT count() FROM bronze.wazuh_events_raw;"
docker compose exec -T clickhouse clickhouse-client \
  --user etl_runner --password etl_runner \
  --query "SELECT count() FROM bronze.zeek_events_raw;"

echo "Triggering Airflow gold_star_schema DAG..."
docker compose exec -T airflow-webserver airflow dags trigger gold_star_schema

echo "Open Airflow: http://localhost:18088"
echo "Open Superset: http://localhost:18089"
