# Malcolm Insight: Near Real-Time Security Analytics POC

This repo is an end-to-end near real-time security analytics POC for Wazuh, Suricata, and Zeek logs. Kafka events are ingested into ClickHouse (bronze), Airflow runs SQL transforms into a gold star schema, and Superset or CHouse UI provides analytics.

## Stack
- ClickHouse 24.3 (bronze + gold)
- Airflow 2.9.2 (LocalExecutor) for gold pipelines
- Postgres 16.3 (metadata store for dynamic DAGs)
- Superset 4.0.1 for BI
- CHouse UI for ClickHouse admin with RBAC
- OpenSearch Puller (metadata-driven ingestion)
- ITSEC Datapipeline Manager (Streamlit) for onboarding + field registry + monitoring
- Schema Migrator (ClickHouse DDL from metadata)
- External Kafka broker (not included in this compose)

## Dataflow
- Kafka topic -> ClickHouse Kafka engine -> bronze.* raw tables
- Airflow executes SQL templates in `airflow/dags/sql` based on Postgres metadata
- Gold star schema (dims, facts, bridges) in `gold.*`
- Superset and CHouse UI query gold

See `FACT_DIM_ARCHITECTURE.md` for the star schema design.

## Quickstart

1) Start the stack

```bash
docker compose up -d
```

2) Wait for services2

```bash
docker compose ps
```

3) Open UIs
- Airflow: http://localhost:18088 (admin/admin)
- Superset: http://localhost:18089 (admin/admin)
- CHouse UI: http://localhost:18087 (admin@localhost / admin123!)
- ITSEC Datapipeline Manager: http://localhost:18090
- ClickHouse HTTP: http://localhost:18123
- ClickHouse TCP: localhost:19000
- Postgres: localhost:15432 (airflow/airflow, db `airflow`)

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
- ClickHouse etl_runner: etl_runner/etl_runner
- ClickHouse superset: superset/superset
- Airflow: admin/admin
- Superset: admin/admin
- CHouse UI: admin@localhost / admin123!

Roles/users are defined in `clickhouse/init/00_databases.sql`.

## ClickHouse ingestion (Kafka engine)
- Kafka table: `bronze.security_events_kafka`
- Materialized views: `bronze.suricata_events_mv`, `bronze.wazuh_events_mv`, `bronze.zeek_events_mv`
- Default broker: `10.110.12.20:9092`
- Default topic: `malcolm-logs`
- Consumer group defaults to `security_events_ch_<suffix>` where `<suffix>` is:
  - `KAFKA_GROUP_SUFFIX` if set
  - otherwise `HOSTNAME` (from the container)
  - otherwise `local`

Override with environment variables before `docker compose up`:
- `KAFKA_BROKER_LIST`
- `KAFKA_TOPIC_LIST`
- `KAFKA_GROUP_NAME` (full override)
- `KAFKA_GROUP_SUFFIX` (suffix-only override)

Note: Kafka/Redpanda is not part of this compose stack.

## Airflow gold pipeline
- DAG: `gold_star_schema` (generated at runtime)
- Metadata source-of-truth: Postgres tables `metadata.gold_dags` + `metadata.gold_pipelines`
- Metadata updater DAG: `metadata_updater` (exports a YAML snapshot to `airflow/dags/gold_pipelines.yml`)
- SQL templates: `airflow/dags/sql/*.sql` (one pipeline per file)
- Default window: 10 minutes (override with `dag_run.conf` `start_ts`/`end_ts` or `window_minutes`)
- Bronze and gold timestamps are stored in `Asia/Jakarta` (UTC+7)

Config switches:
- `GOLD_PIPELINES_SOURCE=postgres` (default) or `file`
- `GOLD_PIPELINES_PATH` to override the YAML path
- `GOLD_METADATA_DAG_NAME` or `GOLD_METADATA_DAG_ID` to select a single DAG when running `metadata_updater`

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

## ITSEC Datapipeline Manager (multi-project control plane)
New OpenSearch sources are driven by Postgres metadata in `postgres/init/11_control_plane.sql`.
If the Postgres volume already exists, apply it manually:

```bash
docker compose exec -T postgres psql -U airflow -d airflow -f /docker-entrypoint-initdb.d/11_control_plane.sql
```

If the control-plane tables already exist, apply the new columns as needed:

```sql
ALTER TABLE metadata.backfill_jobs ADD COLUMN IF NOT EXISTS throttle_seconds INTEGER;
CREATE TABLE IF NOT EXISTS metadata.worker_heartbeats (
  worker_id TEXT PRIMARY KEY,
  worker_type TEXT NOT NULL,
  last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  status TEXT NOT NULL DEFAULT 'ok',
  details JSONB NOT NULL DEFAULT '{}'::jsonb
);
```

### 1) Create a project
Projects map to ClickHouse databases `<project_id>_bronze` and `<project_id>_gold`.
Use ITSEC Datapipeline Manager (http://localhost:18090) or SQL:

```sql
INSERT INTO metadata.projects (project_id, name, timezone, retention_days)
VALUES ('acme', 'ACME Corp', 'UTC', 90)
ON CONFLICT (project_id) DO NOTHING;
```

### 2) Add an OpenSearch source
Secrets are stored via `secret_ref` (file path mounted into containers).
Example:

```sql
INSERT INTO metadata.opensearch_sources (
  project_id, name, base_url, auth_type, username,
  secret_ref, index_pattern, time_field, query_filter_json
) VALUES (
  'acme', 'acme-os', 'https://opensearch.acme.local:9200',
  'api_key', NULL, '/run/secrets/acme_os_key',
  'logs-*', '@timestamp', '{}'::jsonb
);
```

Mount secrets into the containers (example host folder):
`./secrets:/run/secrets:ro`

### 3) Run the schema migrator
This creates per-project databases and the `os_events_raw` table, and applies field registry changes:

```bash
docker compose run --rm schema-migrator
```

### 4) Trigger a backfill
Create a backfill job (or use ITSEC Datapipeline Manager):

```sql
INSERT INTO metadata.backfill_jobs (source_id, start_ts, end_ts, requested_by)
VALUES (1, '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z', 'admin');
```

### 5) Add custom fields via Field Registry
Fields are added idempotently using `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.
Example:

```sql
INSERT INTO metadata.field_registry (
  project_id, dataset, layer, table_name, column_name, column_type,
  expression_sql, mode
) VALUES (
  'acme', 'generic', 'bronze', 'os_events_raw', 'user_name', 'Nullable(String)',
  'JSONExtractString(raw, ''user.name'')', 'ALIAS'
);
```

Then run:

```bash
docker compose run --rm schema-migrator
```

### OpenSearch puller config
Environment variables:
- `POSTGRES_DSN`
- `CLICKHOUSE_HTTP_URL`
- `BATCH_SIZE`
- `OVERLAP_MINUTES`
- `POLL_INTERVAL_SECONDS`
- `LOG_LEVEL`
- `OPENSEARCH_VERIFY_SSL`
- `MAX_RETRIES`, `BACKOFF_BASE_SECONDS`, `RATE_LIMIT_SECONDS` (optional)
- `WORKER_ID` (optional heartbeat identifier)

Puller config can also be managed in the Datapipeline Manager UI (Puller page). When present,
values in `metadata.opensearch_puller_config` override the env defaults each polling loop.

If you already initialized Postgres before this table existed, run once:

```sql
CREATE TABLE IF NOT EXISTS metadata.opensearch_puller_config (
  config_id SMALLINT PRIMARY KEY DEFAULT 1,
  poll_interval_seconds INTEGER NOT NULL DEFAULT 30,
  overlap_minutes INTEGER NOT NULL DEFAULT 10,
  batch_size INTEGER NOT NULL DEFAULT 500,
  max_retries INTEGER NOT NULL DEFAULT 3,
  backoff_base_seconds DOUBLE PRECISION NOT NULL DEFAULT 1,
  rate_limit_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
  opensearch_timeout_seconds INTEGER NOT NULL DEFAULT 30,
  clickhouse_timeout_seconds INTEGER NOT NULL DEFAULT 30,
  opensearch_verify_ssl BOOLEAN NOT NULL DEFAULT TRUE,
  updated_by TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO metadata.opensearch_puller_config (config_id)
VALUES (1)
ON CONFLICT (config_id) DO NOTHING;
```

## ITSEC Datapipeline Manager usage
Access the UI at http://localhost:18090.

Default credentials:
- username: `admin`
- password: `admin123!`

Docker service: `itsec-datapipeline-manager`

Upgrade tip: if you previously ran the old Source Manager container, use:
`docker compose up -d --build --remove-orphans`

User flow (typical):
1) Projects: create a project (`project_id` becomes `<project_id>_bronze` and `<project_id>_gold`).
2) Puller: add OpenSearch sources, adjust polling config, and monitor ingestion health.
   (You can also use the Sources page for full source editing.)
3) Field Registry: add derived fields (ALIAS or MATERIALIZED) and click "Apply Schema Changes".
4) Backfill: queue historical loads if needed.
5) Monitoring: verify ingestion status, lag, and errors (Puller/Monitoring pages).

Notes:
- Schema changes and metadata updates are idempotent and require no service restarts.
- Backfill throttling can be set per job in the UI (`throttle_seconds`).

## Superset
Log in at http://localhost:18089 with admin/admin.

Use the ClickHouse connector:

```
clickhouse+connect://superset:superset@clickhouse:8123/default
```

Add datasets from the gold schema (facts + dims). For step-by-step setup see `superset/bootstrap/README_superset.md`.

## Examples and smoke test
- ClickHouse query samples: `scripts/clickhouse_examples.sql`
- Superset query samples: `scripts/superset_sql_examples.sql`
- Smoke test (Linux/WSL): `scripts/smoke_test.sh`

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
- If Kafka ingestion is empty, verify the broker `10.110.12.20:9092` is reachable from the ClickHouse container and the topic has data.
- If gold DAGs do not appear, check the metadata tables in Postgres and run `metadata_updater`.
- If the gold DAG fails, check Airflow logs and ClickHouse permissions for `etl_runner`.
