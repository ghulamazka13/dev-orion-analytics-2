INSERT INTO {{ params.target_table }} (
  protocol_key,
  protocol,
  updated_at
)
WITH
  parseDateTime64BestEffort('{{ start_ts }}') AS start_ts,
  parseDateTime64BestEffort('{{ end_ts }}') AS end_ts
SELECT
  s.protocol_key,
  s.protocol,
  now64(3, 'Asia/Jakarta') AS updated_at
FROM (
  SELECT DISTINCT
    cityHash64(ifNull(protocol, '')) AS protocol_key,
    protocol
  FROM (
    SELECT protocol
    FROM bronze.suricata_events_raw
    WHERE event_ts >= start_ts AND event_ts < end_ts
    UNION ALL
    SELECT protocol
    FROM bronze.zeek_events_raw
    WHERE event_ts >= start_ts AND event_ts < end_ts
  )
  WHERE protocol IS NOT NULL AND protocol != ''
) s
LEFT JOIN {{ params.target_table }} d
  ON d.protocol_key = s.protocol_key
WHERE d.protocol_key IS NULL;
