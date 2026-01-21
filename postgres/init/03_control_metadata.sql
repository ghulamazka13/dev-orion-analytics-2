CREATE TABLE IF NOT EXISTS control.pipeline_definitions (
  pipeline_id text PRIMARY KEY,
  enabled boolean NOT NULL DEFAULT true,
  schedule_cron text NOT NULL,
  bronze_table text NOT NULL,
  silver_table text NOT NULL,
  gold_tables jsonb NOT NULL,
  silver_sql_path text NOT NULL,
  gold_sql_paths jsonb NOT NULL,
  dq_profile text,
  sla_minutes int,
  freshness_threshold_minutes int,
  owner text,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS control.dq_rules (
  pipeline_id text NOT NULL REFERENCES control.pipeline_definitions(pipeline_id),
  rule_name text NOT NULL,
  rule_type text NOT NULL,
  params jsonb,
  severity text,
  created_at timestamptz DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_dq_rules ON control.dq_rules(pipeline_id, rule_name);
