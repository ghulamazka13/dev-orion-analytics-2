INSERT INTO {{ params.target_table }} (
  tag_key,
  tag_value,
  updated_at
)
WITH
  parseDateTime64BestEffort('{{ start_ts }}') AS start_ts,
  parseDateTime64BestEffort('{{ end_ts }}') AS end_ts
SELECT
  s.tag_key,
  s.tag_value,
  now64(3, 'Asia/Jakarta') AS updated_at
FROM (
  SELECT DISTINCT
    cityHash64(tag_value) AS tag_key,
    tag_value
  FROM (
    SELECT arrayJoin(tags) AS tag_value
    FROM bronze.wazuh_events_raw
    WHERE event_ts >= start_ts AND event_ts < end_ts
    UNION ALL
    SELECT arrayJoin(tags) AS tag_value
    FROM bronze.suricata_events_raw
    WHERE event_ts >= start_ts AND event_ts < end_ts
    UNION ALL
    SELECT arrayJoin(tags) AS tag_value
    FROM bronze.zeek_events_raw
    WHERE event_ts >= start_ts AND event_ts < end_ts
  )
  WHERE tag_value != ''
) s
LEFT JOIN {{ params.target_table }} d
  ON d.tag_key = s.tag_key
WHERE d.tag_key IS NULL;
