BEGIN;

CREATE SCHEMA IF NOT EXISTS metadata;

DROP TRIGGER IF EXISTS gold_pipelines_set_dag_id ON metadata.gold_pipelines;
DROP TRIGGER IF EXISTS gold_pipelines_set_dag_ref_id ON metadata.gold_pipelines;
DROP FUNCTION IF EXISTS metadata.sync_gold_pipeline_dag_ref();
DROP FUNCTION IF EXISTS metadata.set_gold_pipeline_dag_ref_id();

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'metadata'
      AND table_name = 'gold_dags'
      AND column_name = 'dag_id'
  ) AND NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'metadata'
      AND table_name = 'gold_dags'
      AND column_name = 'dag_name'
  ) THEN
    EXECUTE 'ALTER TABLE metadata.gold_dags RENAME COLUMN dag_id TO dag_name';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'metadata'
      AND table_name = 'gold_pipelines'
      AND column_name = 'pipeline_id'
  ) AND NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'metadata'
      AND table_name = 'gold_pipelines'
      AND column_name = 'pipeline_name'
  ) THEN
    EXECUTE 'ALTER TABLE metadata.gold_pipelines RENAME COLUMN pipeline_id TO pipeline_name';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'metadata'
      AND table_name = 'gold_pipelines'
      AND column_name = 'dag_ref_id'
  ) AND NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'metadata'
      AND table_name = 'gold_pipelines'
      AND column_name = 'dag_id'
  ) THEN
    EXECUTE 'ALTER TABLE metadata.gold_pipelines RENAME COLUMN dag_ref_id TO dag_id';
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'metadata'
      AND table_name = 'gold_pipelines'
      AND column_name = 'dag_name'
  ) AND EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'metadata'
      AND table_name = 'gold_pipelines'
      AND column_name = 'dag_id'
  ) THEN
    EXECUTE '
      UPDATE metadata.gold_pipelines p
      SET dag_id = d.id
      FROM metadata.gold_dags d
      WHERE p.dag_id IS NULL
        AND p.dag_name = d.dag_name
    ';
  END IF;
END $$;

ALTER TABLE metadata.gold_pipelines DROP CONSTRAINT IF EXISTS gold_pipelines_new_dag_fk;
ALTER TABLE metadata.gold_pipelines DROP CONSTRAINT IF EXISTS gold_pipelines_new_dag_pipeline_key;
ALTER TABLE metadata.gold_pipelines DROP CONSTRAINT IF EXISTS gold_pipelines_new_pk;
ALTER TABLE metadata.gold_dags DROP CONSTRAINT IF EXISTS gold_dags_new_dag_id_key;
ALTER TABLE metadata.gold_dags DROP CONSTRAINT IF EXISTS gold_dags_new_id_dag_id_key;
ALTER TABLE metadata.gold_dags DROP CONSTRAINT IF EXISTS gold_dags_new_pk;
ALTER TABLE metadata.gold_pipelines DROP CONSTRAINT IF EXISTS gold_pipelines_dag_fk;
ALTER TABLE metadata.gold_pipelines DROP CONSTRAINT IF EXISTS gold_pipelines_dag_pipeline_key;
ALTER TABLE metadata.gold_pipelines DROP CONSTRAINT IF EXISTS gold_pipelines_pk;
ALTER TABLE metadata.gold_dags DROP CONSTRAINT IF EXISTS gold_dags_dag_id_key;
ALTER TABLE metadata.gold_dags DROP CONSTRAINT IF EXISTS gold_dags_pk;
ALTER TABLE metadata.gold_dags DROP CONSTRAINT IF EXISTS gold_dags_dag_name_key;

ALTER TABLE metadata.gold_dags
  ADD COLUMN IF NOT EXISTS id BIGINT;
ALTER TABLE metadata.gold_pipelines
  ADD COLUMN IF NOT EXISTS id BIGINT;

WITH ordered AS (
  SELECT dag_name, row_number() OVER (ORDER BY dag_name) AS rn
  FROM metadata.gold_dags
)
UPDATE metadata.gold_dags d
SET id = o.rn
FROM ordered o
WHERE d.dag_name = o.dag_name
  AND d.id IS NULL;

WITH ordered AS (
  SELECT dag_id, pipeline_name, row_number() OVER (ORDER BY dag_id, pipeline_order, pipeline_name) AS rn
  FROM metadata.gold_pipelines
)
UPDATE metadata.gold_pipelines p
SET id = o.rn
FROM ordered o
WHERE p.dag_id = o.dag_id
  AND p.pipeline_name = o.pipeline_name
  AND p.id IS NULL;

DROP TABLE IF EXISTS metadata.gold_pipelines_new;
DROP TABLE IF EXISTS metadata.gold_dags_new;

CREATE TABLE metadata.gold_dags_new (
  id BIGINT NOT NULL,
  dag_name TEXT NOT NULL,
  schedule_cron TEXT NOT NULL,
  timezone TEXT NOT NULL,
  owner TEXT NOT NULL,
  tags TEXT[] NOT NULL DEFAULT '{}',
  max_active_tasks INTEGER NOT NULL DEFAULT 8,
  default_window_minutes INTEGER NOT NULL DEFAULT 10,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT gold_dags_pk PRIMARY KEY (id),
  CONSTRAINT gold_dags_dag_name_key UNIQUE (dag_name)
);

INSERT INTO metadata.gold_dags_new (
  id,
  dag_name,
  schedule_cron,
  timezone,
  owner,
  tags,
  max_active_tasks,
  default_window_minutes,
  enabled,
  updated_at
)
SELECT
  id,
  dag_name,
  schedule_cron,
  timezone,
  owner,
  tags,
  max_active_tasks,
  default_window_minutes,
  enabled,
  updated_at
FROM metadata.gold_dags;

CREATE TABLE metadata.gold_pipelines_new (
  id BIGINT NOT NULL,
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
  CONSTRAINT gold_pipelines_pk PRIMARY KEY (id),
  CONSTRAINT gold_pipelines_dag_pipeline_key UNIQUE (dag_id, pipeline_name),
  CONSTRAINT gold_pipelines_dag_fk
    FOREIGN KEY (dag_id)
    REFERENCES metadata.gold_dags_new (id)
    ON UPDATE CASCADE
    ON DELETE CASCADE
);

INSERT INTO metadata.gold_pipelines_new (
  id,
  dag_id,
  pipeline_name,
  enabled,
  sql_path,
  window_minutes,
  depends_on,
  target_table,
  params,
  pipeline_order,
  updated_at
)
SELECT
  id,
  dag_id,
  pipeline_name,
  enabled,
  sql_path,
  window_minutes,
  depends_on,
  target_table,
  params,
  pipeline_order,
  updated_at
FROM metadata.gold_pipelines;

DROP TABLE metadata.gold_pipelines;
DROP TABLE metadata.gold_dags;

ALTER TABLE metadata.gold_dags_new RENAME TO gold_dags;
ALTER TABLE metadata.gold_pipelines_new RENAME TO gold_pipelines;

CREATE SEQUENCE IF NOT EXISTS metadata.gold_dags_id_seq;
ALTER TABLE metadata.gold_dags
  ALTER COLUMN id SET DEFAULT nextval('metadata.gold_dags_id_seq');
SELECT setval('metadata.gold_dags_id_seq', (SELECT COALESCE(MAX(id), 0) FROM metadata.gold_dags));

CREATE SEQUENCE IF NOT EXISTS metadata.gold_pipelines_id_seq;
ALTER TABLE metadata.gold_pipelines
  ALTER COLUMN id SET DEFAULT nextval('metadata.gold_pipelines_id_seq');
SELECT setval('metadata.gold_pipelines_id_seq', (SELECT COALESCE(MAX(id), 0) FROM metadata.gold_pipelines));

COMMIT;
