INSERT INTO {{ params.target_table }} (
  event_id,
  event_ts,
  date_key,
  time_key,
  sensor_key,
  signature_key,
  protocol_key,
  event_type,
  severity,
  src_ip,
  dest_ip,
  src_port,
  dest_port,
  community_id,
  duration,
  dest_mac,
  src_mac,
  mac,
  latitude,
  longitude,
  country_name,
  bytes,
  packets,
  flow_id,
  http_url,
  message,
  updated_at
)
WITH
  parseDateTime64BestEffort('{{ start_ts }}') AS start_ts,
  parseDateTime64BestEffort('{{ end_ts }}') AS end_ts,
  'Asia/Jakarta' AS tz
SELECT
  src.event_id,
  src.event_ts_local AS event_ts,
  toYYYYMMDD(src.event_ts_local) AS date_key,
  toUInt32(
    toHour(src.event_ts_local) * 10000
    + toMinute(src.event_ts_local) * 100
    + toSecond(src.event_ts_local)
  ) AS time_key,
  s.sensor_key,
  sig.signature_key,
  p.protocol_key,
  src.event_type,
  src.severity,
  src.src_ip,
  src.dest_ip,
  src.src_port,
  src.dest_port,
  src.community_id,
  src.duration,
  src.dest_mac,
  src.src_mac,
  src.mac,
  src.latitude,
  src.longitude,
  src.country_name,
  src.bytes,
  src.packets,
  src.flow_id,
  src.http_url,
  src.message,
  now64(3, 'Asia/Jakarta') AS updated_at
FROM (
  SELECT
    b.*,
    toTimeZone(b.event_ts, tz) AS event_ts_local
  FROM bronze.suricata_events_raw b
  WHERE b.event_ts >= start_ts AND b.event_ts < end_ts
) src
LEFT JOIN gold.dim_sensor s
  ON s.sensor_key = cityHash64(ifNull(src.sensor_type, ''), ifNull(src.sensor_name, ''))
LEFT JOIN gold.dim_signature sig
  ON sig.signature_key = cityHash64(
    ifNull(src.signature_id, -1),
    ifNull(src.signature, ''),
    ifNull(src.category, ''),
    ifNull(src.alert_action, '')
  )
LEFT JOIN gold.dim_protocol p
  ON p.protocol_key = cityHash64(ifNull(src.protocol, ''))
LEFT JOIN {{ params.target_table }} existing
  ON existing.event_id = src.event_id
  AND existing.event_ts = src.event_ts_local
WHERE existing.event_id IS NULL;
