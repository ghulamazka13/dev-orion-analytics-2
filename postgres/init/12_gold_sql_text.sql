CREATE SCHEMA IF NOT EXISTS metadata;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'metadata'
      AND table_name = 'gold_pipelines'
  ) THEN
    ALTER TABLE metadata.gold_pipelines
      ADD COLUMN IF NOT EXISTS sql_text TEXT;

    ALTER TABLE metadata.gold_pipelines
      ALTER COLUMN sql_path DROP NOT NULL;

    ALTER TABLE metadata.gold_pipelines
      DROP CONSTRAINT IF EXISTS gold_pipelines_sql_source_ck;

    ALTER TABLE metadata.gold_pipelines
      ADD CONSTRAINT gold_pipelines_sql_source_ck
      CHECK (
        NULLIF(btrim(sql_path), '') IS NOT NULL
        OR NULLIF(btrim(sql_text), '') IS NOT NULL
      );
  END IF;
END $$;
