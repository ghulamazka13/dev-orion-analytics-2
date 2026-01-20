CREATE TABLE IF NOT EXISTS bronze.security_events_kafka (
  raw String
)
ENGINE = Kafka
SETTINGS
  kafka_broker_list = '10.110.12.20:9092',
  kafka_topic_list = 'malcolm-logs',
  kafka_group_name = 'security_events_ch',
  kafka_format = 'JSONAsString',
  kafka_num_consumers = 1,
  kafka_skip_broken_messages = 1000;

CREATE MATERIALIZED VIEW IF NOT EXISTS bronze.suricata_events_mv
TO bronze.suricata_events_raw
AS
SELECT
  JSON_VALUE(raw, '$.event.hash') AS event_id,
  toTimeZone(
    coalesce(
      parseDateTime64BestEffortOrNull(nullIf(JSONExtractString(raw, '@timestamp'), '')),
      parseDateTime64BestEffortOrNull(JSON_VALUE(raw, '$.suricata.timestamp'))
    ),
    'Asia/Jakarta'
  ) AS event_ts,
  coalesce(
    JSON_VALUE(raw, '$.event.provider'),
    JSON_VALUE(raw, '$.event.module')
  ) AS sensor_type,
  coalesce(
    JSON_VALUE(raw, '$.agent.name'),
    JSON_VALUE(raw, '$.host.name'),
    JSONExtractString(raw, 'node')
  ) AS sensor_name,
  coalesce(
    JSON_VALUE(raw, '$.event.dataset'),
    JSON_VALUE(raw, '$.event.kind')
  ) AS event_type,
  coalesce(
    JSON_VALUE(raw, '$.suricata.alert.severity'),
    JSON_VALUE(raw, '$.event.severity')
  ) AS severity,
  toIPv6OrNull(JSON_VALUE(raw, '$.source.ip')) AS src_ip,
  toIPv6OrNull(JSON_VALUE(raw, '$.destination.ip')) AS dest_ip,
  toInt32OrNull(JSON_VALUE(raw, '$.source.port')) AS src_port,
  toInt32OrNull(JSON_VALUE(raw, '$.destination.port')) AS dest_port,
  coalesce(
    JSON_VALUE(raw, '$.network.application'),
    JSON_VALUE(raw, '$.network.transport[0]'),
    JSON_VALUE(raw, '$.network.protocol[0]'),
    JSON_VALUE(raw, '$.protocol[0]')
  ) AS protocol,
  coalesce(
    toInt64OrNull(JSON_VALUE(raw, '$.totDataBytes')),
    toInt64OrNull(JSON_VALUE(raw, '$.network.bytes')),
    toInt64OrNull(JSON_VALUE(raw, '$.client.bytes')),
    toInt64OrNull(JSON_VALUE(raw, '$.server.bytes'))
  ) AS bytes,
  coalesce(
    toInt64OrNull(JSON_VALUE(raw, '$.network.packets')),
    toInt64OrNull(JSON_VALUE(raw, '$.client.packets')),
    toInt64OrNull(JSON_VALUE(raw, '$.server.packets'))
  ) AS packets,
  JSON_VALUE(raw, '$.suricata.flow_id') AS flow_id,
  coalesce(
    JSON_VALUE(raw, '$.rule.name'),
    JSON_VALUE(raw, '$.suricata.alert.signature')
  ) AS signature,
  toInt32OrNull(JSON_VALUE(raw, '$.rule.id')) AS signature_id,
  JSON_VALUE(raw, '$.rule.category[0]') AS category,
  JSON_VALUE(raw, '$.suricata.alert.action') AS alert_action,
  JSON_VALUE(raw, '$.suricata.http.url') AS http_url,
  ifNull(
    JSONExtract(raw, 'tags', 'Array(String)'),
    ifNull(JSONExtract(JSONExtractRaw(raw, 'event'), 'severity_tags', 'Array(String)'), [])
  ) AS tags,
  coalesce(
    JSONExtractString(raw, 'message'),
    JSON_VALUE(raw, '$.event.original'),
    JSON_VALUE(raw, '$.rule.name')
  ) AS message,
  raw AS raw_data
FROM bronze.security_events_kafka
WHERE JSONHas(raw, 'suricata')
  AND JSON_VALUE(raw, '$.event.hash') != '';

CREATE MATERIALIZED VIEW IF NOT EXISTS bronze.wazuh_events_mv
TO bronze.wazuh_events_raw
AS
SELECT
  JSON_VALUE(raw, '$.event.hash') AS event_id,
  toTimeZone(
    coalesce(
      parseDateTime64BestEffortOrNull(nullIf(JSONExtractString(raw, '@timestamp'), '')),
      parseDateTime64BestEffortOrNull(nullIf(JSON_VALUE(raw, '$.event.ingested'), '')),
      fromUnixTimestamp64Milli(toInt64OrNull(JSON_VALUE(raw, '$.event.start'))),
      fromUnixTimestamp64Milli(toInt64OrNull(JSON_VALUE(raw, '$.event.end')))
    ),
    'Asia/Jakarta'
  ) AS event_ts,
  toTimeZone(
    parseDateTime64BestEffortOrNull(nullIf(JSON_VALUE(raw, '$.event.ingested'), '')),
    'Asia/Jakarta'
  ) AS event_ingested_ts,
  toTimeZone(
    fromUnixTimestamp64Milli(toInt64OrNull(JSON_VALUE(raw, '$.event.start'))),
    'Asia/Jakarta'
  ) AS event_start_ts,
  toTimeZone(
    fromUnixTimestamp64Milli(toInt64OrNull(JSON_VALUE(raw, '$.event.end'))),
    'Asia/Jakarta'
  ) AS event_end_ts,
  JSON_VALUE(raw, '$.event.dataset') AS event_dataset,
  JSON_VALUE(raw, '$.event.kind') AS event_kind,
  JSON_VALUE(raw, '$.event.module') AS event_module,
  JSON_VALUE(raw, '$.event.provider') AS event_provider,
  JSON_VALUE(raw, '$.agent.name') AS agent_name,
  toIPv6OrNull(JSON_VALUE(raw, '$.agent.ip')) AS agent_ip,
  JSON_VALUE(raw, '$.host.name') AS host_name,
  toIPv6OrNull(JSON_VALUE(raw, '$.host.ip')) AS host_ip,
  JSON_VALUE(raw, '$.rule.id') AS rule_id,
  toInt32OrNull(JSON_VALUE(raw, '$.rule.level')) AS rule_level,
  JSON_VALUE(raw, '$.rule.name') AS rule_name,
  JSONExtractRaw(JSONExtractRaw(raw, 'rule'), 'ruleset') AS rule_ruleset,
  ifNull(JSONExtract(raw, 'tags', 'Array(String)'), []) AS tags,
  coalesce(JSONExtractString(raw, 'message'), JSON_VALUE(raw, '$.rule.name')) AS message,
  raw AS raw_data
FROM bronze.security_events_kafka
WHERE JSON_VALUE(raw, '$.event.provider') = 'wazuh'
  AND JSON_VALUE(raw, '$.event.hash') != '';

CREATE MATERIALIZED VIEW IF NOT EXISTS bronze.zeek_events_mv
TO bronze.zeek_events_raw
AS
SELECT
  JSON_VALUE(raw, '$.event.hash') AS event_id,
  toTimeZone(
    coalesce(
      parseDateTime64BestEffortOrNull(nullIf(JSONExtractString(raw, '@timestamp'), '')),
      parseDateTime64BestEffortOrNull(nullIf(JSON_VALUE(raw, '$.zeek.ts'), '')),
      parseDateTime64BestEffortOrNull(nullIf(JSON_VALUE(raw, '$.event.ingested'), '')),
      fromUnixTimestamp64Milli(toInt64OrNull(JSON_VALUE(raw, '$.event.start')))
    ),
    'Asia/Jakarta'
  ) AS event_ts,
  toTimeZone(
    parseDateTime64BestEffortOrNull(nullIf(JSON_VALUE(raw, '$.event.ingested'), '')),
    'Asia/Jakarta'
  ) AS event_ingested_ts,
  toTimeZone(
    fromUnixTimestamp64Milli(toInt64OrNull(JSON_VALUE(raw, '$.event.start'))),
    'Asia/Jakarta'
  ) AS event_start_ts,
  toTimeZone(
    fromUnixTimestamp64Milli(toInt64OrNull(JSON_VALUE(raw, '$.event.end'))),
    'Asia/Jakarta'
  ) AS event_end_ts,
  JSON_VALUE(raw, '$.event.dataset') AS event_dataset,
  JSON_VALUE(raw, '$.event.kind') AS event_kind,
  JSON_VALUE(raw, '$.event.module') AS event_module,
  JSON_VALUE(raw, '$.event.provider') AS event_provider,
  coalesce(
    JSON_VALUE(raw, '$.zeek.uid'),
    JSON_VALUE(raw, '$.event.id[0]')
  ) AS zeek_uid,
  coalesce(
    JSON_VALUE(raw, '$.agent.name'),
    JSON_VALUE(raw, '$.host.name'),
    JSONExtractString(raw, 'node')
  ) AS sensor_name,
  toIPv6OrNull(JSON_VALUE(raw, '$.source.ip')) AS src_ip,
  toIPv6OrNull(JSON_VALUE(raw, '$.destination.ip')) AS dest_ip,
  toInt32OrNull(JSON_VALUE(raw, '$.source.port')) AS src_port,
  toInt32OrNull(JSON_VALUE(raw, '$.destination.port')) AS dest_port,
  coalesce(
    JSON_VALUE(raw, '$.network.application'),
    JSON_VALUE(raw, '$.network.transport[0]'),
    JSON_VALUE(raw, '$.network.protocol[0]'),
    JSON_VALUE(raw, '$.protocol[0]')
  ) AS protocol,
  JSON_VALUE(raw, '$.network.application') AS application,
  JSON_VALUE(raw, '$.network.type') AS network_type,
  JSON_VALUE(raw, '$.network.direction') AS direction,
  JSON_VALUE(raw, '$.network.community_id') AS community_id,
  coalesce(
    toInt64OrNull(JSON_VALUE(raw, '$.totDataBytes')),
    toInt64OrNull(JSON_VALUE(raw, '$.network.bytes')),
    toInt64OrNull(JSON_VALUE(raw, '$.source.bytes')),
    toInt64OrNull(JSON_VALUE(raw, '$.destination.bytes'))
  ) AS bytes,
  coalesce(
    toInt64OrNull(JSON_VALUE(raw, '$.network.packets')),
    toInt64OrNull(JSON_VALUE(raw, '$.source.packets')),
    toInt64OrNull(JSON_VALUE(raw, '$.destination.packets'))
  ) AS packets,
  coalesce(
    toInt64OrNull(JSON_VALUE(raw, '$.zeek.conn.orig_bytes')),
    toInt64OrNull(JSON_VALUE(raw, '$.zeek.conn.orig_ip_bytes'))
  ) AS orig_bytes,
  coalesce(
    toInt64OrNull(JSON_VALUE(raw, '$.zeek.conn.resp_bytes')),
    toInt64OrNull(JSON_VALUE(raw, '$.zeek.conn.resp_ip_bytes'))
  ) AS resp_bytes,
  toInt64OrNull(JSON_VALUE(raw, '$.zeek.conn.orig_pkts')) AS orig_pkts,
  toInt64OrNull(JSON_VALUE(raw, '$.zeek.conn.resp_pkts')) AS resp_pkts,
  JSON_VALUE(raw, '$.zeek.conn.conn_state') AS conn_state,
  JSON_VALUE(raw, '$.zeek.conn.conn_state_description') AS conn_state_description,
  toFloat64OrNull(JSON_VALUE(raw, '$.zeek.conn.duration')) AS duration,
  JSON_VALUE(raw, '$.zeek.conn.history') AS history,
  coalesce(
    JSON_VALUE(raw, '$.zeek.conn.vlan'),
    JSON_VALUE(raw, '$.network.vlan.id[0]')
  ) AS vlan_id,
  ifNull(
    JSONExtract(raw, 'tags', 'Array(String)'),
    ifNull(
      JSONExtract(JSONExtractRaw(raw, 'event'), 'category', 'Array(String)'),
      ifNull(JSONExtract(JSONExtractRaw(raw, 'event'), 'severity_tags', 'Array(String)'), [])
    )
  ) AS tags,
  coalesce(
    JSONExtractString(raw, 'message'),
    JSON_VALUE(raw, '$.event.original'),
    JSON_VALUE(raw, '$.zeek.conn.conn_state_description')
  ) AS message,
  raw AS raw_data
FROM bronze.security_events_kafka
WHERE JSONHas(raw, 'zeek')
  AND JSON_VALUE(raw, '$.event.hash') != '';
