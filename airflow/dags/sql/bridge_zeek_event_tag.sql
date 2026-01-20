INSERT INTO {{ params.target_table }} (
  event_id,
  event_ts,
  tag_key,
  updated_at
)
WITH
  parseDateTime64BestEffort('{{ start_ts }}') AS start_ts,
  parseDateTime64BestEffort('{{ end_ts }}') AS end_ts,
  'Asia/Jakarta' AS tz
SELECT
  b.event_id,
  b.event_ts_local AS event_ts,
  t.tag_key,
  now64(3, 'Asia/Jakarta') AS updated_at
FROM (
  SELECT
    event_id,
    toTimeZone(event_ts, tz) AS event_ts_local,
    arrayJoin(tags) AS tag_value
  FROM bronze.zeek_events_raw
  WHERE event_ts >= start_ts AND event_ts < end_ts
) b
LEFT JOIN gold.dim_tag t
  ON t.tag_value = b.tag_value
LEFT JOIN {{ params.target_table }} existing
  ON existing.event_id = b.event_id
  AND existing.event_ts = b.event_ts_local
  AND existing.tag_key = t.tag_key
WHERE b.tag_value != ''
  AND t.tag_key IS NOT NULL
  AND existing.event_id IS NULL;
