-- Switch bronze timestamps to Asia/Jakarta (UTC+7).

ALTER TABLE bronze.suricata_events_raw
  MODIFY COLUMN event_ts DateTime64(3, 'Asia/Jakarta');

ALTER TABLE bronze.wazuh_events_raw
  MODIFY COLUMN event_ts DateTime64(3, 'Asia/Jakarta'),
  MODIFY COLUMN event_ingested_ts Nullable(DateTime64(3, 'Asia/Jakarta')),
  MODIFY COLUMN event_start_ts Nullable(DateTime64(3, 'Asia/Jakarta')),
  MODIFY COLUMN event_end_ts Nullable(DateTime64(3, 'Asia/Jakarta'));

ALTER TABLE bronze.zeek_events_raw
  MODIFY COLUMN event_ts DateTime64(3, 'Asia/Jakarta'),
  MODIFY COLUMN event_ingested_ts Nullable(DateTime64(3, 'Asia/Jakarta')),
  MODIFY COLUMN event_start_ts Nullable(DateTime64(3, 'Asia/Jakarta')),
  MODIFY COLUMN event_end_ts Nullable(DateTime64(3, 'Asia/Jakarta'));
