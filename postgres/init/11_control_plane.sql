CREATE SCHEMA IF NOT EXISTS metadata;

CREATE TABLE IF NOT EXISTS metadata.ui_users (
  user_id BIGSERIAL PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'viewer',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS metadata.projects (
  project_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  timezone TEXT NOT NULL DEFAULT 'UTC',
  retention_days INTEGER
);

CREATE TABLE IF NOT EXISTS metadata.opensearch_sources (
  source_id BIGSERIAL PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  base_url TEXT NOT NULL,
  auth_type TEXT,
  username TEXT,
  secret_ref TEXT,
  secret_enc BYTEA,
  index_pattern TEXT NOT NULL,
  time_field TEXT NOT NULL,
  query_filter_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (project_id, name),
  CONSTRAINT opensearch_sources_project_fk
    FOREIGN KEY (project_id)
    REFERENCES metadata.projects (project_id)
    ON UPDATE CASCADE
    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS metadata.ingestion_state (
  source_id BIGINT NOT NULL,
  index_name TEXT NOT NULL,
  last_ts TIMESTAMPTZ,
  last_sort_json JSONB,
  last_id TEXT,
  status TEXT NOT NULL DEFAULT 'idle',
  last_error TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (source_id, index_name),
  CONSTRAINT ingestion_state_source_fk
    FOREIGN KEY (source_id)
    REFERENCES metadata.opensearch_sources (source_id)
    ON UPDATE CASCADE
    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS metadata.backfill_jobs (
  job_id BIGSERIAL PRIMARY KEY,
  source_id BIGINT NOT NULL,
  start_ts TIMESTAMPTZ NOT NULL,
  end_ts TIMESTAMPTZ NOT NULL,
  throttle_seconds INTEGER,
  status TEXT NOT NULL DEFAULT 'pending',
  requested_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_error TEXT,
  last_index_name TEXT,
  last_ts TIMESTAMPTZ,
  last_sort_json JSONB,
  last_id TEXT,
  CONSTRAINT backfill_jobs_source_fk
    FOREIGN KEY (source_id)
    REFERENCES metadata.opensearch_sources (source_id)
    ON UPDATE CASCADE
    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS metadata.worker_heartbeats (
  worker_id TEXT PRIMARY KEY,
  worker_type TEXT NOT NULL,
  last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  status TEXT NOT NULL DEFAULT 'ok',
  details JSONB NOT NULL DEFAULT '{}'::jsonb
);

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

CREATE TABLE IF NOT EXISTS metadata.field_registry (
  field_id BIGSERIAL PRIMARY KEY,
  project_id TEXT,
  dataset TEXT NOT NULL,
  layer TEXT NOT NULL,
  table_name TEXT NOT NULL,
  column_name TEXT NOT NULL,
  column_type TEXT NOT NULL,
  expression_sql TEXT,
  mode TEXT NOT NULL DEFAULT 'ALIAS',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (project_id, table_name, column_name),
  CONSTRAINT field_registry_project_fk
    FOREIGN KEY (project_id)
    REFERENCES metadata.projects (project_id)
    ON UPDATE CASCADE
    ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS metadata.bronze_event_tables (
  table_id BIGSERIAL PRIMARY KEY,
  project_id TEXT,
  dataset TEXT NOT NULL,
  table_name TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (project_id, table_name),
  CONSTRAINT bronze_event_tables_project_fk
    FOREIGN KEY (project_id)
    REFERENCES metadata.projects (project_id)
    ON UPDATE CASCADE
    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS metadata.bronze_event_fields (
  field_id BIGSERIAL PRIMARY KEY,
  table_id BIGINT NOT NULL,
  column_name TEXT NOT NULL,
  column_type TEXT NOT NULL,
  json_path TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  ordinal INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (table_id, column_name),
  CONSTRAINT bronze_event_fields_table_fk
    FOREIGN KEY (table_id)
    REFERENCES metadata.bronze_event_tables (table_id)
    ON UPDATE CASCADE
    ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ui_users_role
  ON metadata.ui_users (role);

CREATE INDEX IF NOT EXISTS idx_ui_users_enabled
  ON metadata.ui_users (enabled);

CREATE INDEX IF NOT EXISTS idx_projects_enabled
  ON metadata.projects (enabled);

CREATE INDEX IF NOT EXISTS idx_opensearch_sources_project
  ON metadata.opensearch_sources (project_id);

CREATE INDEX IF NOT EXISTS idx_opensearch_sources_enabled
  ON metadata.opensearch_sources (enabled);

CREATE INDEX IF NOT EXISTS idx_ingestion_state_status
  ON metadata.ingestion_state (status);

CREATE INDEX IF NOT EXISTS idx_backfill_jobs_status
  ON metadata.backfill_jobs (status);

CREATE INDEX IF NOT EXISTS idx_worker_heartbeats_seen
  ON metadata.worker_heartbeats (last_seen);

CREATE INDEX IF NOT EXISTS idx_field_registry_enabled
  ON metadata.field_registry (enabled);

CREATE INDEX IF NOT EXISTS idx_bronze_event_tables_project
  ON metadata.bronze_event_tables (project_id);

CREATE INDEX IF NOT EXISTS idx_bronze_event_tables_enabled
  ON metadata.bronze_event_tables (enabled);

CREATE INDEX IF NOT EXISTS idx_bronze_event_fields_table
  ON metadata.bronze_event_fields (table_id);

CREATE INDEX IF NOT EXISTS idx_bronze_event_fields_enabled
  ON metadata.bronze_event_fields (enabled);
