CREATE TABLE IF NOT EXISTS gold.dim_date (
  date_key UInt32,
  date Date,
  year UInt16,
  quarter UInt8,
  month UInt8,
  day UInt8,
  week_of_year UInt8,
  day_of_week UInt8,
  updated_at DateTime64(3, 'Asia/Jakarta')
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY date_key;

CREATE TABLE IF NOT EXISTS gold.dim_time (
  time_key UInt32,
  hour UInt8,
  minute UInt8,
  second UInt8,
  updated_at DateTime64(3, 'Asia/Jakarta')
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY time_key;

CREATE TABLE IF NOT EXISTS gold.dim_host (
  host_key UInt64,
  host_name Nullable(String),
  host_ip Nullable(IPv6),
  effective_from DateTime64(3, 'Asia/Jakarta'),
  effective_to Nullable(DateTime64(3, 'Asia/Jakarta')),
  is_current UInt8
)
ENGINE = MergeTree
ORDER BY (ifNull(host_name, ''), effective_from);

CREATE TABLE IF NOT EXISTS gold.dim_tag (
  tag_key UInt64,
  tag_value String,
  updated_at DateTime64(3, 'Asia/Jakarta')
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY tag_key;

CREATE TABLE IF NOT EXISTS gold.dim_agent (
  agent_key UInt64,
  agent_name Nullable(String),
  agent_ip Nullable(IPv6),
  effective_from DateTime64(3, 'Asia/Jakarta'),
  effective_to Nullable(DateTime64(3, 'Asia/Jakarta')),
  is_current UInt8
)
ENGINE = MergeTree
ORDER BY (ifNull(agent_name, ''), effective_from);

CREATE TABLE IF NOT EXISTS gold.dim_rule (
  rule_key UInt64,
  rule_id Nullable(String),
  rule_level Nullable(Int32),
  rule_name Nullable(String),
  rule_ruleset Nullable(String),
  effective_from DateTime64(3, 'Asia/Jakarta'),
  effective_to Nullable(DateTime64(3, 'Asia/Jakarta')),
  is_current UInt8
)
ENGINE = MergeTree
ORDER BY (ifNull(rule_id, ''), effective_from);

CREATE TABLE IF NOT EXISTS gold.dim_event (
  event_key UInt64,
  event_dataset Nullable(String),
  event_kind Nullable(String),
  event_module Nullable(String),
  event_provider Nullable(String),
  updated_at DateTime64(3, 'Asia/Jakarta')
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY event_key;

CREATE TABLE IF NOT EXISTS gold.dim_sensor (
  sensor_key UInt64,
  sensor_type Nullable(String),
  sensor_name Nullable(String),
  updated_at DateTime64(3, 'Asia/Jakarta')
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY sensor_key;

CREATE TABLE IF NOT EXISTS gold.dim_signature (
  signature_key UInt64,
  signature_id Nullable(Int32),
  signature Nullable(String),
  category Nullable(String),
  alert_action Nullable(String),
  updated_at DateTime64(3, 'Asia/Jakarta')
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY signature_key;

CREATE TABLE IF NOT EXISTS gold.dim_protocol (
  protocol_key UInt64,
  protocol Nullable(String),
  updated_at DateTime64(3, 'Asia/Jakarta')
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY protocol_key;

CREATE TABLE IF NOT EXISTS gold.fact_wazuh_events (
  event_id String,
  event_ts DateTime64(3, 'Asia/Jakarta'),
  event_ingested_ts Nullable(DateTime64(3, 'Asia/Jakarta')),
  event_start_ts Nullable(DateTime64(3, 'Asia/Jakarta')),
  event_end_ts Nullable(DateTime64(3, 'Asia/Jakarta')),
  date_key UInt32,
  time_key UInt32,
  agent_key Nullable(UInt64),
  host_key Nullable(UInt64),
  rule_key Nullable(UInt64),
  event_key Nullable(UInt64),
  lag_seconds Nullable(Float64),
  duration_seconds Nullable(Float64),
  message Nullable(String),
  updated_at DateTime64(3, 'Asia/Jakarta')
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toDate(event_ts)
ORDER BY (event_id, event_ts);

CREATE TABLE IF NOT EXISTS gold.fact_suricata_events (
  event_id String,
  event_ts DateTime64(3, 'Asia/Jakarta'),
  date_key UInt32,
  time_key UInt32,
  sensor_key Nullable(UInt64),
  signature_key Nullable(UInt64),
  protocol_key Nullable(UInt64),
  event_type Nullable(String),
  severity Nullable(String),
  src_ip Nullable(IPv6),
  dest_ip Nullable(IPv6),
  src_port Nullable(Int32),
  dest_port Nullable(Int32),
  community_id Nullable(String),
  duration Nullable(Float64),
  dest_mac Nullable(String),
  src_mac Nullable(String),
  mac Nullable(String),
  latitude Nullable(Float64),
  longitude Nullable(Float64),
  country_name Nullable(String),
  bytes Nullable(Int64),
  packets Nullable(Int64),
  flow_id Nullable(String),
  http_url Nullable(String),
  message Nullable(String),
  updated_at DateTime64(3, 'Asia/Jakarta')
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toDate(event_ts)
ORDER BY (event_id, event_ts);

CREATE TABLE IF NOT EXISTS gold.fact_zeek_events (
  event_id String,
  event_ts DateTime64(3, 'Asia/Jakarta'),
  event_ingested_ts Nullable(DateTime64(3, 'Asia/Jakarta')),
  event_start_ts Nullable(DateTime64(3, 'Asia/Jakarta')),
  event_end_ts Nullable(DateTime64(3, 'Asia/Jakarta')),
  date_key UInt32,
  time_key UInt32,
  sensor_key Nullable(UInt64),
  protocol_key Nullable(UInt64),
  event_key Nullable(UInt64),
  zeek_uid Nullable(String),
  src_ip Nullable(IPv6),
  dest_ip Nullable(IPv6),
  src_port Nullable(Int32),
  dest_port Nullable(Int32),
  geo_latitude Nullable(Float64),
  geo_longitude Nullable(Float64),
  geo_country Nullable(String),
  geo_city_name Nullable(String),
  mac_address Nullable(String),
  application Nullable(String),
  network_type Nullable(String),
  direction Nullable(String),
  community_id Nullable(String),
  bytes Nullable(Int64),
  packets Nullable(Int64),
  orig_bytes Nullable(Int64),
  resp_bytes Nullable(Int64),
  orig_pkts Nullable(Int64),
  resp_pkts Nullable(Int64),
  conn_state Nullable(String),
  conn_state_description Nullable(String),
  duration_seconds Nullable(Float64),
  history Nullable(String),
  vlan_id Nullable(String),
  domain Nullable(String),
  message Nullable(String),
  updated_at DateTime64(3, 'Asia/Jakarta')
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toDate(event_ts)
ORDER BY (event_id, event_ts);

CREATE TABLE IF NOT EXISTS gold.bridge_wazuh_event_tag (
  event_id String,
  event_ts DateTime64(3, 'Asia/Jakarta'),
  tag_key UInt64,
  updated_at DateTime64(3, 'Asia/Jakarta')
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toDate(event_ts)
ORDER BY (event_id, event_ts, tag_key);

CREATE TABLE IF NOT EXISTS gold.bridge_suricata_event_tag (
  event_id String,
  event_ts DateTime64(3, 'Asia/Jakarta'),
  tag_key UInt64,
  updated_at DateTime64(3, 'Asia/Jakarta')
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toDate(event_ts)
ORDER BY (event_id, event_ts, tag_key);

CREATE TABLE IF NOT EXISTS gold.bridge_zeek_event_tag (
  event_id String,
  event_ts DateTime64(3, 'Asia/Jakarta'),
  tag_key UInt64,
  updated_at DateTime64(3, 'Asia/Jakarta')
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toDate(event_ts)
ORDER BY (event_id, event_ts, tag_key);
