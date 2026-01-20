INSERT INTO {{ params.target_table }} (
  signature_key,
  signature_id,
  signature,
  category,
  alert_action,
  updated_at
)
WITH
  parseDateTime64BestEffort('{{ start_ts }}') AS start_ts,
  parseDateTime64BestEffort('{{ end_ts }}') AS end_ts
SELECT
  s.signature_key,
  s.signature_id,
  s.signature,
  s.category,
  s.alert_action,
  now64(3, 'Asia/Jakarta') AS updated_at
FROM (
  SELECT DISTINCT
    cityHash64(
      ifNull(signature_id, -1),
      ifNull(signature, ''),
      ifNull(category, ''),
      ifNull(alert_action, '')
    ) AS signature_key,
    signature_id,
    signature,
    category,
    alert_action
  FROM bronze.suricata_events_raw
  WHERE event_ts >= start_ts AND event_ts < end_ts
    AND (signature_id IS NOT NULL OR (signature IS NOT NULL AND signature != ''))
) s
LEFT JOIN {{ params.target_table }} d
  ON d.signature_key = s.signature_key
WHERE d.signature_key IS NULL;
