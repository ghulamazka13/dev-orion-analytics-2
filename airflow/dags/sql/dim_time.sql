INSERT INTO {{ params.target_table }} (
  time_key,
  hour,
  minute,
  second,
  updated_at
)
WITH
  parseDateTime64BestEffort('{{ start_ts }}') AS start_ts,
  parseDateTime64BestEffort('{{ end_ts }}') AS end_ts,
  'Asia/Jakarta' AS tz
SELECT
  s.time_key,
  s.hour,
  s.minute,
  s.second,
  now64(3, tz) AS updated_at
FROM (
  SELECT DISTINCT
    toUInt32(
      toHour(event_ts_local) * 10000
      + toMinute(event_ts_local) * 100
      + toSecond(event_ts_local)
    ) AS time_key,
    toHour(event_ts_local) AS hour,
    toMinute(event_ts_local) AS minute,
    toSecond(event_ts_local) AS second
  FROM (
    SELECT toTimeZone(event_ts, tz) AS event_ts_local
    FROM bronze.wazuh_events_raw
    WHERE event_ts >= start_ts AND event_ts < end_ts
    UNION ALL
    SELECT toTimeZone(event_ts, tz) AS event_ts_local
    FROM bronze.suricata_events_raw
    WHERE event_ts >= start_ts AND event_ts < end_ts
    UNION ALL
    SELECT toTimeZone(event_ts, tz) AS event_ts_local
    FROM bronze.zeek_events_raw
    WHERE event_ts >= start_ts AND event_ts < end_ts
  )
) s
LEFT JOIN {{ params.target_table }} d
  ON d.time_key = s.time_key
WHERE d.time_key IS NULL;
