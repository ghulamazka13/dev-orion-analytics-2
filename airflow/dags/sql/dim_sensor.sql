INSERT INTO {{ params.target_table }} (
  sensor_key,
  sensor_type,
  sensor_name,
  updated_at
)
WITH
  parseDateTime64BestEffort('{{ start_ts }}') AS start_ts,
  parseDateTime64BestEffort('{{ end_ts }}') AS end_ts
SELECT
  s.sensor_key,
  s.sensor_type,
  s.sensor_name,
  now64(3, 'Asia/Jakarta') AS updated_at
FROM (
  SELECT DISTINCT
    cityHash64(ifNull(sensor_type, ''), ifNull(sensor_name, '')) AS sensor_key,
    sensor_type,
    sensor_name
  FROM (
    SELECT sensor_type, sensor_name
    FROM bronze.suricata_events_raw
    WHERE event_ts >= start_ts AND event_ts < end_ts
    UNION ALL
    SELECT 'zeek' AS sensor_type, sensor_name
    FROM bronze.zeek_events_raw
    WHERE event_ts >= start_ts AND event_ts < end_ts
  )
  WHERE (sensor_name IS NOT NULL AND sensor_name != '')
     OR (sensor_type IS NOT NULL AND sensor_type != '')
) s
LEFT JOIN {{ params.target_table }} d
  ON d.sensor_key = s.sensor_key
WHERE d.sensor_key IS NULL;
