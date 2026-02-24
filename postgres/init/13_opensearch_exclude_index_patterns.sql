ALTER TABLE IF EXISTS metadata.opensearch_sources
  ADD COLUMN IF NOT EXISTS exclude_index_patterns TEXT;
