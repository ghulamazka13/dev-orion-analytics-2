-- Switch gold timestamps to Asia/Jakarta (UTC+7).

ALTER TABLE gold.dim_date
  MODIFY COLUMN updated_at DateTime64(3, 'Asia/Jakarta');

ALTER TABLE gold.dim_time
  MODIFY COLUMN updated_at DateTime64(3, 'Asia/Jakarta');

ALTER TABLE gold.dim_host
  MODIFY COLUMN effective_from DateTime64(3, 'Asia/Jakarta'),
  MODIFY COLUMN effective_to Nullable(DateTime64(3, 'Asia/Jakarta'));

ALTER TABLE gold.dim_tag
  MODIFY COLUMN updated_at DateTime64(3, 'Asia/Jakarta');

ALTER TABLE gold.dim_agent
  MODIFY COLUMN effective_from DateTime64(3, 'Asia/Jakarta'),
  MODIFY COLUMN effective_to Nullable(DateTime64(3, 'Asia/Jakarta'));

ALTER TABLE gold.dim_rule
  MODIFY COLUMN effective_from DateTime64(3, 'Asia/Jakarta'),
  MODIFY COLUMN effective_to Nullable(DateTime64(3, 'Asia/Jakarta'));

ALTER TABLE gold.dim_event
  MODIFY COLUMN updated_at DateTime64(3, 'Asia/Jakarta');

ALTER TABLE gold.dim_sensor
  MODIFY COLUMN updated_at DateTime64(3, 'Asia/Jakarta');

ALTER TABLE gold.dim_signature
  MODIFY COLUMN updated_at DateTime64(3, 'Asia/Jakarta');

ALTER TABLE gold.dim_protocol
  MODIFY COLUMN updated_at DateTime64(3, 'Asia/Jakarta');

ALTER TABLE gold.fact_wazuh_events
  MODIFY COLUMN event_ts DateTime64(3, 'Asia/Jakarta'),
  MODIFY COLUMN event_ingested_ts Nullable(DateTime64(3, 'Asia/Jakarta')),
  MODIFY COLUMN event_start_ts Nullable(DateTime64(3, 'Asia/Jakarta')),
  MODIFY COLUMN event_end_ts Nullable(DateTime64(3, 'Asia/Jakarta')),
  MODIFY COLUMN updated_at DateTime64(3, 'Asia/Jakarta');

ALTER TABLE gold.fact_suricata_events
  MODIFY COLUMN event_ts DateTime64(3, 'Asia/Jakarta'),
  MODIFY COLUMN updated_at DateTime64(3, 'Asia/Jakarta');

ALTER TABLE gold.fact_zeek_events
  MODIFY COLUMN event_ts DateTime64(3, 'Asia/Jakarta'),
  MODIFY COLUMN event_ingested_ts Nullable(DateTime64(3, 'Asia/Jakarta')),
  MODIFY COLUMN event_start_ts Nullable(DateTime64(3, 'Asia/Jakarta')),
  MODIFY COLUMN event_end_ts Nullable(DateTime64(3, 'Asia/Jakarta')),
  MODIFY COLUMN updated_at DateTime64(3, 'Asia/Jakarta');

ALTER TABLE gold.bridge_wazuh_event_tag
  MODIFY COLUMN event_ts DateTime64(3, 'Asia/Jakarta'),
  MODIFY COLUMN updated_at DateTime64(3, 'Asia/Jakarta');

ALTER TABLE gold.bridge_suricata_event_tag
  MODIFY COLUMN event_ts DateTime64(3, 'Asia/Jakarta'),
  MODIFY COLUMN updated_at DateTime64(3, 'Asia/Jakarta');

ALTER TABLE gold.bridge_zeek_event_tag
  MODIFY COLUMN event_ts DateTime64(3, 'Asia/Jakarta'),
  MODIFY COLUMN updated_at DateTime64(3, 'Asia/Jakarta');
