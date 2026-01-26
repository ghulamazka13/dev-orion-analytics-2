INSERT INTO {{ params.target_table }} (
  event_id,
  event_ts,
  event_ingested_ts,
  event_start_ts,
  event_end_ts,
  date_key,
  time_key,
  sensor_key,
  protocol_key,
  event_key,
  zeek_uid,
  src_ip,
  dest_ip,
  src_port,
  dest_port,
  geo_latitude,
  geo_longitude,
  geo_country,
  geo_city_name,
  mac_address,
  application,
  network_type,
  direction,
  community_id,
  bytes,
  packets,
  orig_bytes,
  resp_bytes,
  orig_pkts,
  resp_pkts,
  conn_state,
  conn_state_description,
  duration_seconds,
  history,
  vlan_id,
  domain,
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
  src.event_ingested_ts_local AS event_ingested_ts,
  src.event_start_ts_local AS event_start_ts,
  src.event_end_ts_local AS event_end_ts,
  toYYYYMMDD(src.event_ts_local) AS date_key,
  toUInt32(
    toHour(src.event_ts_local) * 10000
    + toMinute(src.event_ts_local) * 100
    + toSecond(src.event_ts_local)
  ) AS time_key,
  s.sensor_key,
  p.protocol_key,
  e.event_key,
  src.zeek_uid,
  src.src_ip,
  src.dest_ip,
  src.src_port,
  src.dest_port,
  src.geo_latitude,
  src.geo_longitude,
  src.geo_country,
  src.geo_city_name,
  src.mac_address,
  src.application,
  src.network_type,
  src.direction,
  src.community_id,
  src.bytes,
  src.packets,
  src.orig_bytes,
  src.resp_bytes,
  src.orig_pkts,
  src.resp_pkts,
  src.conn_state,
  src.conn_state_description,
  src.duration AS duration_seconds,
  src.history,
  src.vlan_id,
  src.domain,
  src.message,
  now64(3, 'Asia/Jakarta') AS updated_at
FROM (
  SELECT
    b.*,
    toTimeZone(b.event_ts, tz) AS event_ts_local,
    toTimeZone(b.event_ingested_ts, tz) AS event_ingested_ts_local,
    toTimeZone(b.event_start_ts, tz) AS event_start_ts_local,
    toTimeZone(b.event_end_ts, tz) AS event_end_ts_local
  FROM bronze.zeek_events_raw b
  WHERE b.event_ts >= start_ts AND b.event_ts < end_ts
) src
LEFT JOIN gold.dim_sensor s
  ON s.sensor_key = cityHash64('zeek', ifNull(src.sensor_name, ''))
LEFT JOIN gold.dim_protocol p
  ON p.protocol_key = cityHash64(ifNull(src.protocol, ''))
LEFT JOIN gold.dim_event e
  ON e.event_key = cityHash64(
    ifNull(src.event_dataset, ''),
    ifNull(src.event_kind, ''),
    ifNull(src.event_module, ''),
    ifNull(src.event_provider, '')
  )
LEFT JOIN {{ params.target_table }} existing
  ON existing.event_id = src.event_id
  AND existing.event_ts = src.event_ts_local
WHERE existing.event_id IS NULL;
