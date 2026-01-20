# Near Real-Time Security Analytics POC

This repo is an end-to-end near real-time analytics POC using a Medallion architecture with ClickHouse storage and Airflow batch transforms.

Dataflow
- Redpanda (remote) -> ClickHouse Kafka Engine -> bronze.* (raw)
- Airflow runs ClickHouse SQL to build the gold star schema (dims/facts/bridges)
- Superset reads gold only

## Quickstart

1) Start the stack

```bash
docker compose up -d
```

2) Wait for services

```bash
docker compose ps
```

3) Open UIs
- Airflow: http://localhost:18088 (admin/admin)
- Superset: http://localhost:18089 (admin/admin)
- ClickHouse HTTP: http://localhost:18123
- CHouse UI: http://localhost:18087 (admin@localhost / admin123!)

In CHouse UI, add a ClickHouse connection:
- URL: http://clickhouse:8123
- User/password: admin/admin (or etl_runner/etl_runner)

4) Trigger the gold pipeline (optional)

```bash
docker compose exec -T airflow-webserver airflow dags trigger gold_star_schema
```

5) Check data in ClickHouse

```bash
docker compose exec -T clickhouse clickhouse-client \
  --user etl_runner --password etl_runner \
  --query "SELECT count() FROM bronze.suricata_events_raw;"
```

## Access control
ClickHouse RBAC is enabled on init.
- etl_runner: read/write bronze + gold
- superset: read-only on gold

Default credentials:
- ClickHouse admin: admin/admin
- etl_runner: etl_runner/etl_runner
- superset: superset/superset

Roles/users are defined in `clickhouse/init/00_databases.sql`.

## ClickHouse ingestion (Kafka Engine)
- Kafka table: `bronze.security_events_kafka`
- Materialized Views: `bronze.suricata_events_mv`, `bronze.wazuh_events_mv`, `bronze.zeek_events_mv`
- Broker: `10.110.12.20:9092`
- Topic: `malcolm-logs`

## Airflow gold pipeline
- DAG: `gold_star_schema`
- Metadata source-of-truth: Postgres tables `metadata.gold_dags` + `metadata.gold_pipelines`
- Metadata updater DAG: `metadata_updater` (exports a YAML snapshot to `airflow/dags/gold_pipelines.yml`)
- SQL templates: `airflow/dags/sql/*.sql` (one pipeline per file)
- Default window: 10 minutes (override with `dag_run.conf` `start_ts`/`end_ts` or `window_minutes`)
- Bronze and gold timestamps are stored in `Asia/Jakarta` (UTC+7).

To add a new gold pipeline (existing DAG):
1) Get the DAG numeric id:
   `SELECT id FROM metadata.gold_dags WHERE dag_name = 'gold_star_schema';`
2) Insert a row in `metadata.gold_pipelines` with `dag_id`, `pipeline_name`, `sql_path`, and `target_table`
3) Create the SQL template under `airflow/dags/sql/` using `{{ start_ts }}`, `{{ end_ts }}`, and `{{ params.* }}`
4) Trigger `metadata_updater` (optional) to regenerate the YAML snapshot

To add a new DAG + pipelines (new data source):
1) Insert a row in `metadata.gold_dags`:
```sql
INSERT INTO metadata.gold_dags (
  dag_name,
  schedule_cron,
  timezone,
  owner,
  tags,
  max_active_tasks,
  default_window_minutes,
  enabled
) VALUES (
  'gold_new_source',
  '*/5 * * * *',
  'Asia/Jakarta',
  'data-eng',
  ARRAY['gold', 'clickhouse'],
  8,
  10,
  TRUE
)
ON CONFLICT (dag_name) DO NOTHING;
```
2) Get the numeric id for the new DAG:
   `SELECT id FROM metadata.gold_dags WHERE dag_name = 'gold_new_source';`
3) Insert pipeline rows in `metadata.gold_pipelines` using that `dag_id` (set `depends_on` with pipeline_name values).
4) Add SQL templates under `airflow/dags/sql/`.
5) Wait for the DAG parser to refresh or trigger `metadata_updater` (optional).

Example backfill run:

```bash
docker compose exec -T airflow-webserver airflow dags trigger gold_star_schema \
  -c '{"start_ts":"2026-01-01T00:00:00Z","end_ts":"2026-01-02T00:00:00Z"}'
```

Run a single pipeline:

```bash
docker compose exec -T airflow-webserver airflow dags trigger gold_star_schema \
  -c '{"pipeline_id":"fact_wazuh_events","start_ts":"2026-01-01T00:00:00Z","end_ts":"2026-01-02T00:00:00Z"}'
```

## Metadata store (Postgres)
Metadata schema and seed data live in `postgres/init/10_metadata.sql`.
`metadata.gold_pipelines.dag_id` is a numeric FK to `metadata.gold_dags.id`.
If the Postgres volume already exists, apply the SQL manually:

```bash
docker compose exec -T postgres psql -U airflow -d airflow -f /docker-entrypoint-initdb.d/10_metadata.sql
```

Example insert for a new pipeline:

```sql
WITH dag AS (
  SELECT id
  FROM metadata.gold_dags
  WHERE dag_name = 'gold_star_schema'
)
INSERT INTO metadata.gold_pipelines (
  dag_id,
  pipeline_name,
  enabled,
  sql_path,
  window_minutes,
  depends_on,
  target_table,
  pipeline_order
)
SELECT
  dag.id,
  'fact_new_events',
  TRUE,
  'sql/fact_new_events.sql',
  10,
  ARRAY['dim_date', 'dim_time'],
  'gold.fact_new_events',
  20
FROM dag;
```

## Superset
Use the ClickHouse connector:

```
clickhouse+connect://superset:superset@clickhouse:8123/default
```

Add datasets from the gold schema (facts + dims).

## Optional one-time backfill (from Postgres)
If you have historical data in Postgres, run a one-time import into ClickHouse using the `postgresql` table function. A ready-to-run backfill script is provided in `scripts/postgres_to_clickhouse_backfill.sql`.

Example (legacy Postgres running on port 15433):

```bash
docker run -d --name dev-airflow-legacy-postgres -p 15433:5432 \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=analytics \
  -v dev-airflow-1_postgres_data:/var/lib/postgresql/data \
  pgduckdb/pgduckdb:16-v1.1.1

Get-Content scripts/postgres_to_clickhouse_backfill.sql | \
  docker compose exec -T clickhouse clickhouse-client \
    --user etl_runner --password etl_runner --multiquery
```

Update the host/port/user/password in the SQL file to match your production Postgres instance.

## One-time gold migration (from legacy Postgres)
If you already have gold tables in a legacy Postgres, use `scripts/postgres_gold_to_clickhouse_backfill.sql`.

Notes:
- Gold tables must exist in ClickHouse (run `clickhouse/init/03_gold_tables.sql` if needed).
- This migration preserves the legacy surrogate keys. If you plan to keep running the gold DAG, consider rebuilding gold from bronze instead so keys stay consistent.

Example:

```bash
Get-Content scripts/postgres_gold_to_clickhouse_backfill.sql | \
  docker compose exec -T clickhouse clickhouse-client \
    --user etl_runner --password etl_runner --multiquery
```

## Troubleshooting
- If Kafka ingestion is empty, verify the broker `10.110.12.20:9092` is reachable from the ClickHouse container.
- If gold DAG fails, check Airflow logs and ClickHouse permissions for `etl_runner`.
