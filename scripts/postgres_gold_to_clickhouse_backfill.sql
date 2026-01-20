-- One-time backfill: legacy Postgres gold -> ClickHouse gold.
-- Update host/port/user/password/schema for your environment.
-- Optional: TRUNCATE TABLE gold.<table> before running if reloading.

-- Dimensions
INSERT INTO gold.dim_date (
  date_key,
  date,
  year,
  quarter,
  month,
  day,
  week_of_year,
  day_of_week,
  updated_at
)
SELECT
  toUInt32(date_key) AS date_key,
  toDate(date) AS date,
  toUInt16(year) AS year,
  toUInt8(quarter) AS quarter,
  toUInt8(month) AS month,
  toUInt8(day) AS day,
  toUInt8(week_of_year) AS week_of_year,
  toUInt8(day_of_week) AS day_of_week,
  now64(3, 'UTC') AS updated_at
FROM postgresql(
  'host.docker.internal:15433',
  'analytics',
  'dim_date',
  'etl_runner',
  'etl_runner',
  'gold'
);

INSERT INTO gold.dim_time (
  time_key,
  hour,
  minute,
  second,
  updated_at
)
SELECT
  toUInt32(time_key) AS time_key,
  toUInt8(hour) AS hour,
  toUInt8(minute) AS minute,
  toUInt8(second) AS second,
  now64(3, 'UTC') AS updated_at
FROM postgresql(
  'host.docker.internal:15433',
  'analytics',
  'dim_time',
  'etl_runner',
  'etl_runner',
  'gold'
);

INSERT INTO gold.dim_event (
  event_key,
  event_dataset,
  event_kind,
  event_module,
  event_provider,
  updated_at
)
SELECT
  toUInt64(event_key) AS event_key,
  event_dataset,
  event_kind,
  event_module,
  event_provider,
  now64(3, 'UTC') AS updated_at
FROM postgresql(
  'host.docker.internal:15433',
  'analytics',
  'dim_event',
  'etl_runner',
  'etl_runner',
  'gold'
);

INSERT INTO gold.dim_sensor (
  sensor_key,
  sensor_type,
  sensor_name,
  updated_at
)
SELECT
  toUInt64(sensor_key) AS sensor_key,
  sensor_type,
  sensor_name,
  now64(3, 'UTC') AS updated_at
FROM postgresql(
  'host.docker.internal:15433',
  'analytics',
  'dim_sensor',
  'etl_runner',
  'etl_runner',
  'gold'
);

INSERT INTO gold.dim_signature (
  signature_key,
  signature_id,
  signature,
  category,
  alert_action,
  updated_at
)
SELECT
  toUInt64(signature_key) AS signature_key,
  CAST(signature_id AS Nullable(Int32)) AS signature_id,
  signature,
  category,
  alert_action,
  now64(3, 'UTC') AS updated_at
FROM postgresql(
  'host.docker.internal:15433',
  'analytics',
  'dim_signature',
  'etl_runner',
  'etl_runner',
  'gold'
);

INSERT INTO gold.dim_protocol (
  protocol_key,
  protocol,
  updated_at
)
SELECT
  toUInt64(protocol_key) AS protocol_key,
  protocol,
  now64(3, 'UTC') AS updated_at
FROM postgresql(
  'host.docker.internal:15433',
  'analytics',
  'dim_protocol',
  'etl_runner',
  'etl_runner',
  'gold'
);

INSERT INTO gold.dim_tag (
  tag_key,
  tag_value,
  updated_at
)
SELECT
  toUInt64(tag_key) AS tag_key,
  tag_value,
  now64(3, 'UTC') AS updated_at
FROM postgresql(
  'host.docker.internal:15433',
  'analytics',
  'dim_tag',
  'etl_runner',
  'etl_runner',
  'gold'
);

INSERT INTO gold.dim_agent (
  agent_key,
  agent_name,
  agent_ip,
  effective_from,
  effective_to,
  is_current
)
SELECT
  toUInt64(agent_key) AS agent_key,
  agent_name,
  toIPv6OrNull(toString(agent_ip)) AS agent_ip,
  parseDateTime64BestEffortOrNull(toString(effective_from)) AS effective_from,
  parseDateTime64BestEffortOrNull(toString(effective_to)) AS effective_to,
  toUInt8(is_current) AS is_current
FROM postgresql(
  'host.docker.internal:15433',
  'analytics',
  'dim_agent',
  'etl_runner',
  'etl_runner',
  'gold'
);

INSERT INTO gold.dim_host (
  host_key,
  host_name,
  host_ip,
  effective_from,
  effective_to,
  is_current
)
SELECT
  toUInt64(host_key) AS host_key,
  host_name,
  toIPv6OrNull(toString(host_ip)) AS host_ip,
  parseDateTime64BestEffortOrNull(toString(effective_from)) AS effective_from,
  parseDateTime64BestEffortOrNull(toString(effective_to)) AS effective_to,
  toUInt8(is_current) AS is_current
FROM postgresql(
  'host.docker.internal:15433',
  'analytics',
  'dim_host',
  'etl_runner',
  'etl_runner',
  'gold'
);

INSERT INTO gold.dim_rule (
  rule_key,
  rule_id,
  rule_level,
  rule_name,
  rule_ruleset,
  effective_from,
  effective_to,
  is_current
)
SELECT
  toUInt64(rule_key) AS rule_key,
  rule_id,
  CAST(rule_level AS Nullable(Int32)) AS rule_level,
  rule_name,
  toString(rule_ruleset) AS rule_ruleset,
  parseDateTime64BestEffortOrNull(toString(effective_from)) AS effective_from,
  parseDateTime64BestEffortOrNull(toString(effective_to)) AS effective_to,
  toUInt8(is_current) AS is_current
FROM postgresql(
  'host.docker.internal:15433',
  'analytics',
  'dim_rule',
  'etl_runner',
  'etl_runner',
  'gold'
);

-- Facts
INSERT INTO gold.fact_wazuh_events (
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
SELECT
  event_id,
  parseDateTime64BestEffortOrNull(toString(event_ts)) AS event_ts,
  parseDateTime64BestEffortOrNull(toString(event_ingested_ts)) AS event_ingested_ts,
  parseDateTime64BestEffortOrNull(toString(event_start_ts)) AS event_start_ts,
  parseDateTime64BestEffortOrNull(toString(event_end_ts)) AS event_end_ts,
  toUInt32(date_key) AS date_key,
  toUInt32(time_key) AS time_key,
  CAST(agent_key AS Nullable(UInt64)) AS agent_key,
  CAST(host_key AS Nullable(UInt64)) AS host_key,
  CAST(rule_key AS Nullable(UInt64)) AS rule_key,
  CAST(event_key AS Nullable(UInt64)) AS event_key,
  CAST(lag_seconds AS Nullable(Float64)) AS lag_seconds,
  CAST(duration_seconds AS Nullable(Float64)) AS duration_seconds,
  message,
  now64(3, 'UTC') AS updated_at
FROM postgresql(
  'host.docker.internal:15433',
  'analytics',
  'fact_wazuh_events',
  'etl_runner',
  'etl_runner',
  'gold'
);

INSERT INTO gold.fact_suricata_events (
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
  bytes,
  packets,
  flow_id,
  http_url,
  message,
  updated_at
)
SELECT
  event_id,
  parseDateTime64BestEffortOrNull(toString(event_ts)) AS event_ts,
  toUInt32(date_key) AS date_key,
  toUInt32(time_key) AS time_key,
  CAST(sensor_key AS Nullable(UInt64)) AS sensor_key,
  CAST(signature_key AS Nullable(UInt64)) AS signature_key,
  CAST(protocol_key AS Nullable(UInt64)) AS protocol_key,
  event_type,
  severity,
  toIPv6OrNull(toString(src_ip)) AS src_ip,
  toIPv6OrNull(toString(dest_ip)) AS dest_ip,
  CAST(src_port AS Nullable(Int32)) AS src_port,
  CAST(dest_port AS Nullable(Int32)) AS dest_port,
  CAST(bytes AS Nullable(Int64)) AS bytes,
  CAST(packets AS Nullable(Int64)) AS packets,
  flow_id,
  http_url,
  message,
  now64(3, 'UTC') AS updated_at
FROM postgresql(
  'host.docker.internal:15433',
  'analytics',
  'fact_suricata_events',
  'etl_runner',
  'etl_runner',
  'gold'
);

INSERT INTO gold.fact_zeek_events (
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
  message,
  updated_at
)
SELECT
  event_id,
  parseDateTime64BestEffortOrNull(toString(event_ts)) AS event_ts,
  parseDateTime64BestEffortOrNull(toString(event_ingested_ts)) AS event_ingested_ts,
  parseDateTime64BestEffortOrNull(toString(event_start_ts)) AS event_start_ts,
  parseDateTime64BestEffortOrNull(toString(event_end_ts)) AS event_end_ts,
  toUInt32(date_key) AS date_key,
  toUInt32(time_key) AS time_key,
  CAST(sensor_key AS Nullable(UInt64)) AS sensor_key,
  CAST(protocol_key AS Nullable(UInt64)) AS protocol_key,
  CAST(event_key AS Nullable(UInt64)) AS event_key,
  zeek_uid,
  toIPv6OrNull(toString(src_ip)) AS src_ip,
  toIPv6OrNull(toString(dest_ip)) AS dest_ip,
  CAST(src_port AS Nullable(Int32)) AS src_port,
  CAST(dest_port AS Nullable(Int32)) AS dest_port,
  application,
  network_type,
  direction,
  community_id,
  CAST(bytes AS Nullable(Int64)) AS bytes,
  CAST(packets AS Nullable(Int64)) AS packets,
  CAST(orig_bytes AS Nullable(Int64)) AS orig_bytes,
  CAST(resp_bytes AS Nullable(Int64)) AS resp_bytes,
  CAST(orig_pkts AS Nullable(Int64)) AS orig_pkts,
  CAST(resp_pkts AS Nullable(Int64)) AS resp_pkts,
  conn_state,
  conn_state_description,
  CAST(duration_seconds AS Nullable(Float64)) AS duration_seconds,
  history,
  vlan_id,
  message,
  now64(3, 'UTC') AS updated_at
FROM postgresql(
  'host.docker.internal:15433',
  'analytics',
  'fact_zeek_events',
  'etl_runner',
  'etl_runner',
  'gold'
);

-- Bridges
INSERT INTO gold.bridge_wazuh_event_tag (
  event_id,
  event_ts,
  tag_key,
  updated_at
)
SELECT
  event_id,
  parseDateTime64BestEffortOrNull(toString(event_ts)) AS event_ts,
  toUInt64(tag_key) AS tag_key,
  now64(3, 'UTC') AS updated_at
FROM postgresql(
  'host.docker.internal:15433',
  'analytics',
  'bridge_wazuh_event_tag',
  'etl_runner',
  'etl_runner',
  'gold'
);

INSERT INTO gold.bridge_suricata_event_tag (
  event_id,
  event_ts,
  tag_key,
  updated_at
)
SELECT
  event_id,
  parseDateTime64BestEffortOrNull(toString(event_ts)) AS event_ts,
  toUInt64(tag_key) AS tag_key,
  now64(3, 'UTC') AS updated_at
FROM postgresql(
  'host.docker.internal:15433',
  'analytics',
  'bridge_suricata_event_tag',
  'etl_runner',
  'etl_runner',
  'gold'
);

INSERT INTO gold.bridge_zeek_event_tag (
  event_id,
  event_ts,
  tag_key,
  updated_at
)
SELECT
  event_id,
  parseDateTime64BestEffortOrNull(toString(event_ts)) AS event_ts,
  toUInt64(tag_key) AS tag_key,
  now64(3, 'UTC') AS updated_at
FROM postgresql(
  'host.docker.internal:15433',
  'analytics',
  'bridge_zeek_event_tag',
  'etl_runner',
  'etl_runner',
  'gold'
);
