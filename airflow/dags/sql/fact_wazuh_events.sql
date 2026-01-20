INSERT INTO {{ params.target_table }} (
  event_id,
  event_ts,
  event_ingested_ts,
  event_start_ts,
  event_end_ts,
  date_key,
  time_key,
  agent_key,
  host_key,
  rule_key,
  event_key,
  lag_seconds,
  duration_seconds,
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
  a.agent_key,
  h.host_key,
  r.rule_key,
  e.event_key,
  if(
    src.event_ingested_ts_local IS NULL,
    NULL,
    dateDiff('second', src.event_ts_local, src.event_ingested_ts_local)
  ) AS lag_seconds,
  if(
    src.event_start_ts_local IS NULL OR src.event_end_ts_local IS NULL,
    NULL,
    dateDiff('second', src.event_start_ts_local, src.event_end_ts_local)
  ) AS duration_seconds,
  src.message,
  now64(3, 'Asia/Jakarta') AS updated_at
FROM (
  SELECT
    b.*,
    toTimeZone(b.event_ts, tz) AS event_ts_local,
    toTimeZone(b.event_ingested_ts, tz) AS event_ingested_ts_local,
    toTimeZone(b.event_start_ts, tz) AS event_start_ts_local,
    toTimeZone(b.event_end_ts, tz) AS event_end_ts_local
  FROM bronze.wazuh_events_raw b
  WHERE b.event_ts >= start_ts AND b.event_ts < end_ts
) src
ASOF LEFT JOIN gold.dim_agent a
  ON a.agent_name = coalesce(nullIf(src.agent_name, ''), toString(src.agent_ip))
  AND src.event_ts_local >= a.effective_from
ASOF LEFT JOIN gold.dim_host h
  ON h.host_name = coalesce(nullIf(src.host_name, ''), toString(src.host_ip))
  AND src.event_ts_local >= h.effective_from
ASOF LEFT JOIN gold.dim_rule r
  ON r.rule_id = nullIf(src.rule_id, '')
  AND src.event_ts_local >= r.effective_from
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
