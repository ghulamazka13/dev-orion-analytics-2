# Malcolm Insight: Near Real-Time Security Analytics POC

This repo is an end-to-end near real-time security analytics POC for Wazuh, Suricata, and Zeek logs. OpenSearch events are pulled into ClickHouse (bronze), Airflow runs SQL transforms into a gold star schema, and Superset or CHouse UI provides analytics.

## Stack
- ClickHouse 24.3 (bronze + gold)
- Airflow 2.9.2 (LocalExecutor) for gold pipelines
- Postgres 16.3 (metadata store for dynamic DAGs)
- Superset 4.0.1 for BI
- CHouse UI for ClickHouse admin with RBAC
- SeaweedFS (S3-compatible object storage)
- OpenSearch Puller (metadata-driven ingestion)
- ITSEC Datapipeline Manager (Streamlit) for onboarding + field registry + monitoring
- Schema Migrator (ClickHouse DDL from metadata)

## Dataflow
- OpenSearch index -> OpenSearch Puller -> `<clickhouse_namespace>_bronze.os_events_raw`
- Schema Migrator + Bronze Tables metadata -> project bronze parsed tables
- Airflow executes SQL from Postgres metadata (`metadata.gold_pipelines.sql_text`) with fallback to file path (`sql_path`)
- Gold star schema (dims, facts, bridges) in `gold.*`
- Superset and CHouse UI query gold

`os_events_raw` stores two raw payload variants:
- `raw`: `_source` payload (used by bronze parsing mappings)
- `raw_hit`: full OpenSearch hit (`_index`, `_id`, `_source`, etc.) for parity/debugging

See `FACT_DIM_ARCHITECTURE.md` for the star schema design.

## Quickstart

1) Start the stack

```bash
docker compose up -d
```

If dependencies changed in `requirements.txt`, rebuild images so Docker installs the new libs automatically:

```bash
docker compose up -d --build
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
- SeaweedFS S3 endpoint: http://localhost:18333
- SeaweedFS Filer UI/API: http://localhost:18888
- SeaweedFS Master UI/API: http://localhost:19333

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

## SeaweedFS (S3-compatible storage)
- Internal endpoint (for services in Docker network): `http://seaweedfs:8333`
- Host endpoint (for local clients): `http://localhost:18333`
- Current compose setup is for local development. Add authentication and TLS before exposing this service outside local/private networks.

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

## Ingestion mode
- Default mode is OpenSearch-only.
- Legacy Kafka bootstrap script is kept for compatibility but disabled by default.
- To force-enable legacy Kafka bootstrap, set:
  - `ENABLE_KAFKA_INGEST=true`

## Airflow gold pipeline
- DAG: `gold_star_schema` (generated at runtime)
- Metadata source-of-truth: Postgres tables `metadata.gold_dags` + `metadata.gold_pipelines`
- Metadata updater DAG: `metadata_updater` (exports a YAML snapshot to `airflow/dags/gold_pipelines.yml`)
- SQL source: prefer `metadata.gold_pipelines.sql_text`; fallback to `sql_path`
- Default window: 10 minutes (override with `dag_run.conf` `start_ts`/`end_ts` or `window_minutes`)
- Bronze and gold timestamps are stored in `Asia/Jakarta` (UTC+7)

Config switches:
- `GOLD_PIPELINES_SOURCE=postgres` (default) or `file`
- `GOLD_PIPELINES_PATH` to override the YAML path
- `GOLD_METADATA_DAG_NAME` or `GOLD_METADATA_DAG_ID` to select a single DAG when running `metadata_updater`

To add a new gold pipeline (existing DAG):
1) Get the DAG numeric id:
   `SELECT id FROM metadata.gold_dags WHERE dag_name = 'gold_star_schema';`
2) Insert a row in `metadata.gold_pipelines` with `dag_id`, `pipeline_name`, `target_table`, and one of:
   - `sql_text` (recommended), or
   - `sql_path` (legacy file-based mode)
3) SQL templates can use `{{ start_ts }}`, `{{ end_ts }}`, and `{{ params.* }}`
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
4) Add SQL in `sql_text` (recommended) or keep legacy `sql_path`.
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
`metadata.gold_pipelines` supports SQL-in-DB via column `sql_text`.

If the Postgres volume already exists, apply the SQL manually:

```bash
docker compose exec -T postgres psql -U airflow -d airflow -f /docker-entrypoint-initdb.d/10_metadata.sql
docker compose exec -T postgres psql -U airflow -d airflow -f /docker-entrypoint-initdb.d/12_gold_sql_text.sql
```

Migrate existing `airflow/dags/sql/*.sql` into Postgres metadata:

```bash
python3 -m pip install -r requirements.txt
```

Then run:

```bash
python3 scripts/sync_gold_sql_to_metadata.py --dsn "postgresql://airflow:airflow@localhost:15432/airflow"
```

Optional (if you want to remove file dependency completely):

```bash
python3 scripts/sync_gold_sql_to_metadata.py --dsn "postgresql://airflow:airflow@localhost:15432/airflow" --clear-sql-path
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
  sql_text,
  window_minutes,
  depends_on,
  target_table,
  pipeline_order
)
SELECT
  dag.id,
  'fact_new_events',
  TRUE,
  'INSERT INTO gold.fact_new_events SELECT ...',
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
ALTER TABLE metadata.projects ADD COLUMN IF NOT EXISTS clickhouse_namespace TEXT;
ALTER TABLE metadata.opensearch_sources ADD COLUMN IF NOT EXISTS target_dataset TEXT;
ALTER TABLE metadata.opensearch_sources ADD COLUMN IF NOT EXISTS target_table_name TEXT;
CREATE TABLE IF NOT EXISTS metadata.worker_heartbeats (
  worker_id TEXT PRIMARY KEY,
  worker_type TEXT NOT NULL,
  last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  status TEXT NOT NULL DEFAULT 'ok',
  details JSONB NOT NULL DEFAULT '{}'::jsonb
);
```

### 1) Create a project
Projects map to ClickHouse databases `<clickhouse_namespace>_bronze` and `<clickhouse_namespace>_gold`.
Use ITSEC Datapipeline Manager (http://localhost:18090) or SQL:

```sql
INSERT INTO metadata.projects (project_id, name, clickhouse_namespace, timezone, retention_days)
VALUES ('acme', 'ACME Corp', 'acme', 'UTC', 90)
ON CONFLICT (project_id) DO NOTHING;
```

If `clickhouse_namespace` is omitted in UI, the app uses `project_id` when it starts with a letter;
otherwise it falls back to `project_name` and adds `p_` when needed.

### 2) Add an OpenSearch source
Secrets are stored via `secret_ref` (file path mounted into containers).
`target_table_name` is required for puller processing. `target_dataset` is optional metadata (defaults to `default`).
`opensearch-puller` writes raw events directly into
`<clickhouse_namespace>_bronze.<target_table_name>` and auto-creates the table if missing.
Example (including routing target dataset/table):

```sql
INSERT INTO metadata.opensearch_sources (
  project_id, name, base_url, auth_type, username,
  secret_ref, index_pattern, time_field, target_dataset, target_table_name, query_filter_json
) VALUES (
  'acme', 'acme-os', 'https://opensearch.acme.local:9200',
  'api_key', NULL, '/run/secrets/acme_os_key',
  'logs-*', '@timestamp', 'bronze', 'arkime_sessions3_26', '{}'::jsonb
);
```

Mount secrets into the containers (example host folder):
`./secrets:/run/secrets:ro`

### 3) Run the schema migrator
This creates per-project databases and the `os_events_raw` table, and applies field registry changes:

```bash
docker compose run --rm schema-migrator
```

By default, metadata-driven Bronze Parsing is disabled in schema migrator
(`ENABLE_METADATA_BRONZE_PARSING=false`).

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

### 6) Static bronze parser from existing raw table (no Bronze Parsing UI)
If you already ingest raw OpenSearch rows into a ClickHouse table such as
`bronze.arkime_sessions3_26`, use the template-based parser:

- Template: `clickhouse/init/05_raw_table_ingest.sql.tmpl`
- MV runner: `clickhouse/init/05_raw_table_ingest.sh`
- Backfill runner: `clickhouse/init/05_raw_table_backfill.sh`

Environment defaults in `docker-compose.yml`:
- `ENABLE_RAW_TABLE_INGEST=true`
- `RAW_SOURCE_TABLES=bronze.arkime_sessions3_26`

You can set multiple raw source tables (comma-separated), for example:
- `RAW_SOURCE_TABLES=bronze.arkime_sessions3_26,bronze.arkime_sessions3_27`

Manual apply on a running stack:

```bash
docker compose exec -T clickhouse bash /docker-entrypoint-initdb.d/05_raw_table_ingest.sh
```

This creates materialized views that parse events from one or more raw source tables into:
- `bronze.suricata_events_raw`
- `bronze.wazuh_events_raw`
- `bronze.zeek_events_raw`

Important: materialized views process only new inserts. For historical rows, run parser backfill:

```bash
docker compose exec -T clickhouse bash /docker-entrypoint-initdb.d/05_raw_table_backfill.sh
```

Duplicate handling:
- The parser SQL skips rows whose `event.hash` already exists in target parsed tables (`bronze.suricata_events_raw`, `bronze.wazuh_events_raw`, `bronze.zeek_events_raw`).
- This applies to both MV ingestion and parser backfill generated from `05_raw_table_ingest.sql.tmpl`.

Optional (override source tables for one run):

```bash
docker compose exec -T -e RAW_SOURCE_TABLES=bronze.arkime_sessions3_26,bronze.arkime_sessions3_27 clickhouse \
  bash /docker-entrypoint-initdb.d/05_raw_table_backfill.sh
```

Backfill order (recommended):
1) Backfill OpenSearch data into raw table(s), e.g. `bronze.arkime_sessions3_26`.
2) Ensure parser materialized views are installed via `05_raw_table_ingest.sh`.
3) If raw historical data was loaded before the parser MVs existed, run:
   - `05_raw_table_backfill.sh` to fill parsed bronze tables from existing raw rows.
   - This is one-time per historical window/source.
   - It is append-only; rerun can create duplicates unless you clear target partitions/ranges first.
   Parsed tables:
   - `bronze.suricata_events_raw`
   - `bronze.wazuh_events_raw`
   - `bronze.zeek_events_raw`
4) Trigger Airflow gold DAG/backfill from parsed bronze to gold.

Note:
- If parser MVs are already installed before raw backfill starts, step (3) is usually not needed for new incoming data.

### 7) Stop / Resume pipeline
Use these commands to stop specific stages safely.

Stop OpenSearch ingest (raw load):

```bash
docker compose stop opensearch-puller
```

Stop bronze -> gold orchestration (Airflow):

```bash
docker compose exec -T airflow-webserver airflow dags pause gold_star_schema
docker compose exec -T airflow-webserver airflow dags pause metadata_updater
docker compose stop airflow-scheduler
```

Stop raw -> parsed bronze parser (materialized views):

```bash
docker compose exec -T clickhouse clickhouse-client --multiquery --query "
DROP TABLE IF EXISTS bronze.suricata_events_mv;
DROP TABLE IF EXISTS bronze.wazuh_events_mv;
DROP TABLE IF EXISTS bronze.zeek_events_mv;
"
```

Cancel pending/running backfill jobs:

```bash
docker compose exec -T postgres psql -U airflow -d airflow -c "
UPDATE metadata.backfill_jobs
SET status='cancelled', updated_at=now()
WHERE status IN ('pending','running');
"
```

Resume pipeline:

```bash
docker compose start opensearch-puller airflow-scheduler
docker compose exec -T airflow-webserver airflow dags unpause gold_star_schema
docker compose exec -T airflow-webserver airflow dags unpause metadata_updater
docker compose exec -T clickhouse bash /docker-entrypoint-initdb.d/05_raw_table_ingest.sh
```

### 8) Data retention (TTL) and removing retention
In this stack, retention is enforced in ClickHouse using table TTL.
`metadata.projects.retention_days` is metadata only unless you apply TTL explicitly.

Apply retention policy (example):

```bash
docker compose exec -T clickhouse clickhouse-client --multiquery --query "
ALTER TABLE bronze.arkime_sessions3_26 MODIFY TTL event_ts + INTERVAL 90 DAY DELETE;
ALTER TABLE bronze.suricata_events_raw MODIFY TTL event_ts + INTERVAL 90 DAY DELETE;
ALTER TABLE bronze.wazuh_events_raw MODIFY TTL event_ts + INTERVAL 90 DAY DELETE;
ALTER TABLE bronze.zeek_events_raw MODIFY TTL event_ts + INTERVAL 90 DAY DELETE;

ALTER TABLE gold.fact_wazuh_events MODIFY TTL event_ts + INTERVAL 365 DAY DELETE;
ALTER TABLE gold.fact_suricata_events MODIFY TTL event_ts + INTERVAL 365 DAY DELETE;
ALTER TABLE gold.fact_zeek_events MODIFY TTL event_ts + INTERVAL 365 DAY DELETE;

ALTER TABLE gold.bridge_wazuh_event_tag MODIFY TTL event_ts + INTERVAL 365 DAY DELETE;
ALTER TABLE gold.bridge_suricata_event_tag MODIFY TTL event_ts + INTERVAL 365 DAY DELETE;
ALTER TABLE gold.bridge_zeek_event_tag MODIFY TTL event_ts + INTERVAL 365 DAY DELETE;
"
```

Optional: force immediate TTL materialization on existing data (can be expensive):

```bash
docker compose exec -T clickhouse clickhouse-client --multiquery --query "
ALTER TABLE bronze.arkime_sessions3_26 MATERIALIZE TTL;
ALTER TABLE bronze.suricata_events_raw MATERIALIZE TTL;
ALTER TABLE bronze.wazuh_events_raw MATERIALIZE TTL;
ALTER TABLE bronze.zeek_events_raw MATERIALIZE TTL;
"
```

Record retention in metadata (for governance/UI):

```sql
UPDATE metadata.projects
SET retention_days = 90, updated_at = now()
WHERE project_id = 'acme';
```

Remove / take out retention policy:

```bash
docker compose exec -T clickhouse clickhouse-client --multiquery --query "
ALTER TABLE bronze.arkime_sessions3_26 REMOVE TTL;
ALTER TABLE bronze.suricata_events_raw REMOVE TTL;
ALTER TABLE bronze.wazuh_events_raw REMOVE TTL;
ALTER TABLE bronze.zeek_events_raw REMOVE TTL;

ALTER TABLE gold.fact_wazuh_events REMOVE TTL;
ALTER TABLE gold.fact_suricata_events REMOVE TTL;
ALTER TABLE gold.fact_zeek_events REMOVE TTL;

ALTER TABLE gold.bridge_wazuh_event_tag REMOVE TTL;
ALTER TABLE gold.bridge_suricata_event_tag REMOVE TTL;
ALTER TABLE gold.bridge_zeek_event_tag REMOVE TTL;
"
```

Important:
- Removing TTL stops future retention deletes.
- Data already deleted by previous TTL cannot be restored from ClickHouse alone.

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
1) Projects: create a project (ClickHouse uses `clickhouse_namespace` as `<clickhouse_namespace>_bronze` and `<clickhouse_namespace>_gold`).
2) Puller: add OpenSearch sources, adjust polling config, and monitor ingestion health.
   (You can also use the Sources page for full source editing.)
3) File Export:
   - Manual mode: select source + indices + format (`csv`, `parquet`, or `zip`) and export to SeaweedFS bucket/folder.
   - Automation mode: create/update trigger-based schedules (interval + lookback window + folder prefix) from the same page.
   - One index = one file.
4) Field Registry: add derived fields (ALIAS or MATERIALIZED) and click "Apply Schema Changes".
5) Backfill: queue historical loads if needed.
6) Gold Pipelines: manage DAG metadata + pipeline SQL (`sql_text`) directly from Postgres.
7) Monitoring: verify ingestion status, lag, and errors (Puller/Monitoring pages).

Notes:
- Schema changes and metadata updates are idempotent and require no service restarts.
- Backfill throttling can be set per job in the UI (`throttle_seconds`).
- File Export uses a fixed SeaweedFS bucket from `SEAWEED_S3_BUCKET`.
- File Export validates bucket existence first; folder prefix is optional and can be a new path.
- Automation jobs are executed by background service `itsec-file-export-worker`.
- `zip` export contains a CSV payload.

SeaweedFS env vars for `itsec-datapipeline-manager`:
- `SEAWEED_S3_ENDPOINT` (default: `http://seaweedfs:8333`)
- `SEAWEED_S3_REGION` (default: `us-east-1`)
- `SEAWEED_S3_ACCESS_KEY` / `SEAWEED_S3_SECRET_KEY` (optional)
- `SEAWEED_S3_BUCKET` (default: `itsec-test`)
- `SEAWEED_S3_VERIFY_SSL` (default: `false`)
- `ITSEC_FILE_EXPORT_BATCH_SIZE` (default: `1000`)
- `ITSEC_FILE_EXPORT_AUTOMATION_POLL_SECONDS` (default: `30`, worker poll interval)

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
- If OpenSearch ingestion is empty, verify source config in `metadata.opensearch_sources`, puller health, and connectivity from `opensearch-puller` to the OpenSearch cluster.
- If gold DAGs do not appear, check the metadata tables in Postgres and run `metadata_updater`.
- If the gold DAG fails, check Airflow logs and ClickHouse permissions for `etl_runner`.
