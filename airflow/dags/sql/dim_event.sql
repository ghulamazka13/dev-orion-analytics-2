INSERT INTO {{ params.target_table }} (
  event_key,
  event_dataset,
  event_kind,
  event_module,
  event_provider,
  updated_at
)
WITH
  parseDateTime64BestEffort('{{ start_ts }}') AS start_ts,
  parseDateTime64BestEffort('{{ end_ts }}') AS end_ts
SELECT
  s.event_key,
  s.event_dataset,
  s.event_kind,
  s.event_module,
  s.event_provider,
  now64(3, 'Asia/Jakarta') AS updated_at
FROM (
  SELECT DISTINCT
    cityHash64(
      ifNull(event_dataset, ''),
      ifNull(event_kind, ''),
      ifNull(event_module, ''),
      ifNull(event_provider, '')
    ) AS event_key,
    event_dataset,
    event_kind,
    event_module,
    event_provider
  FROM (
    SELECT event_dataset, event_kind, event_module, event_provider
    FROM bronze.wazuh_events_raw
    WHERE event_ts >= start_ts AND event_ts < end_ts
    UNION ALL
    SELECT event_dataset, event_kind, event_module, event_provider
    FROM bronze.zeek_events_raw
    WHERE event_ts >= start_ts AND event_ts < end_ts
  )
) s
LEFT JOIN {{ params.target_table }} d
  ON d.event_key = s.event_key
WHERE d.event_key IS NULL;
