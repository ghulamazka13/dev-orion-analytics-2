CREATE SCHEMA IF NOT EXISTS metadata;

CREATE TABLE IF NOT EXISTS metadata.gold_dags (
  id BIGSERIAL PRIMARY KEY,
  dag_name TEXT NOT NULL UNIQUE,
  schedule_cron TEXT NOT NULL,
  timezone TEXT NOT NULL,
  owner TEXT NOT NULL,
  tags TEXT[] NOT NULL DEFAULT '{}',
  max_active_tasks INTEGER NOT NULL DEFAULT 8,
  default_window_minutes INTEGER NOT NULL DEFAULT 10,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS metadata.gold_pipelines (
  id BIGSERIAL PRIMARY KEY,
  dag_id BIGINT NOT NULL,
  pipeline_name TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  sql_path TEXT NOT NULL,
  window_minutes INTEGER,
  depends_on TEXT[],
  target_table TEXT NOT NULL,
  params JSONB NOT NULL DEFAULT '{}'::jsonb,
  pipeline_order INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (dag_id, pipeline_name),
  CONSTRAINT gold_pipelines_dag_fk
    FOREIGN KEY (dag_id)
    REFERENCES metadata.gold_dags (id)
    ON UPDATE CASCADE
    ON DELETE CASCADE
);

INSERT INTO metadata.gold_dags (
  dag_name,
  schedule_cron,
  timezone,
  owner,
  tags,
  max_active_tasks,
  default_window_minutes,
  enabled
)
VALUES (
  'gold_star_schema',
  '*/5 * * * *',
  'Asia/Jakarta',
  'data-eng',
  ARRAY['gold', 'clickhouse', 'star-schema'],
  8,
  10,
  TRUE
)
ON CONFLICT (dag_name) DO NOTHING;

WITH dag AS (
  SELECT id
  FROM metadata.gold_dags
  WHERE dag_name = 'gold_star_schema'
), rows AS (
  SELECT *
  FROM (VALUES
    ('dim_date', TRUE, 'sql/dim_date.sql', 10, NULL::text[], 'gold.dim_date', 1),
    ('dim_time', TRUE, 'sql/dim_time.sql', 10, NULL::text[], 'gold.dim_time', 2),
    ('dim_event', TRUE, 'sql/dim_event.sql', 10, NULL::text[], 'gold.dim_event', 3),
    ('dim_sensor', TRUE, 'sql/dim_sensor.sql', 10, NULL::text[], 'gold.dim_sensor', 4),
    ('dim_protocol', TRUE, 'sql/dim_protocol.sql', 10, NULL::text[], 'gold.dim_protocol', 5),
    ('dim_signature', TRUE, 'sql/dim_signature.sql', 10, NULL::text[], 'gold.dim_signature', 6),
    ('dim_tag', TRUE, 'sql/dim_tag.sql', 10, NULL::text[], 'gold.dim_tag', 7),
    ('dim_agent_scd2', TRUE, 'sql/dim_agent_scd2.sql', 10, NULL::text[], 'gold.dim_agent', 8),
    ('dim_host_scd2', TRUE, 'sql/dim_host_scd2.sql', 10, NULL::text[], 'gold.dim_host', 9),
    ('dim_rule_scd2', TRUE, 'sql/dim_rule_scd2.sql', 10, NULL::text[], 'gold.dim_rule', 10),
    ('fact_wazuh_events', TRUE, 'sql/fact_wazuh_events.sql', 10, ARRAY['dim_date', 'dim_time', 'dim_agent_scd2', 'dim_host_scd2', 'dim_rule_scd2', 'dim_event']::text[], 'gold.fact_wazuh_events', 11),
    ('fact_suricata_events', TRUE, 'sql/fact_suricata_events.sql', 10, ARRAY['dim_date', 'dim_time', 'dim_sensor', 'dim_signature', 'dim_protocol']::text[], 'gold.fact_suricata_events', 12),
    ('fact_zeek_events', TRUE, 'sql/fact_zeek_events.sql', 10, ARRAY['dim_date', 'dim_time', 'dim_sensor', 'dim_protocol', 'dim_event']::text[], 'gold.fact_zeek_events', 13),
    ('bridge_wazuh_event_tag', TRUE, 'sql/bridge_wazuh_event_tag.sql', 10, ARRAY['dim_tag', 'fact_wazuh_events']::text[], 'gold.bridge_wazuh_event_tag', 14),
    ('bridge_suricata_event_tag', TRUE, 'sql/bridge_suricata_event_tag.sql', 10, ARRAY['dim_tag', 'fact_suricata_events']::text[], 'gold.bridge_suricata_event_tag', 15),
    ('bridge_zeek_event_tag', TRUE, 'sql/bridge_zeek_event_tag.sql', 10, ARRAY['dim_tag', 'fact_zeek_events']::text[], 'gold.bridge_zeek_event_tag', 16)
  ) AS v(pipeline_name, enabled, sql_path, window_minutes, depends_on, target_table, pipeline_order)
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
  v.pipeline_name,
  v.enabled,
  v.sql_path,
  v.window_minutes,
  v.depends_on,
  v.target_table,
  v.pipeline_order
FROM dag
CROSS JOIN rows v
ON CONFLICT (dag_id, pipeline_name) DO NOTHING;
