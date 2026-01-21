CREATE TABLE IF NOT EXISTS monitoring.pipeline_runs (
  run_id text PRIMARY KEY,
  pipeline_id text NOT NULL,
  run_ts timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL,
  notes text,
  started_at timestamptz DEFAULT now(),
  ended_at timestamptz
);

CREATE TABLE IF NOT EXISTS monitoring.lag_metrics (
  id bigserial PRIMARY KEY,
  pipeline_id text NOT NULL,
  observed_at timestamptz NOT NULL DEFAULT now(),
  max_event_ts timestamptz,
  lag_seconds double precision
);

CREATE TABLE IF NOT EXISTS monitoring.volume_metrics (
  id bigserial PRIMARY KEY,
  pipeline_id text NOT NULL,
  observed_at timestamptz NOT NULL DEFAULT now(),
  window_minutes int NOT NULL,
  event_count bigint,
  baseline_count bigint,
  status text
);

CREATE TABLE IF NOT EXISTS monitoring.schema_drift (
  id bigserial PRIMARY KEY,
  pipeline_id text NOT NULL,
  observed_at timestamptz NOT NULL DEFAULT now(),
  column_name text NOT NULL,
  expected_type text,
  actual_type text,
  status text
);

CREATE TABLE IF NOT EXISTS monitoring.alerts (
  id bigserial PRIMARY KEY,
  pipeline_id text NOT NULL,
  alert_ts timestamptz NOT NULL DEFAULT now(),
  alert_type text NOT NULL,
  severity text NOT NULL,
  message text
);

CREATE TABLE IF NOT EXISTS gold.dq_results (
  run_id uuid PRIMARY KEY,
  pipeline_id text NOT NULL,
  run_ts timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL,
  results_json jsonb
);

CREATE TABLE IF NOT EXISTS gold.snapshot_runs (
  run_id uuid PRIMARY KEY,
  run_ts timestamptz NOT NULL,
  pipeline_id text NOT NULL,
  status text NOT NULL,
  notes text
);
