ALTER TABLE {{ params.target_table }}
UPDATE
  effective_to = (
    SELECT min(toTimeZone(b.event_ts, 'Asia/Jakarta'))
    FROM bronze.wazuh_events_raw b
    WHERE b.event_ts >= parseDateTime64BestEffort('{{ start_ts }}')
      AND b.event_ts < parseDateTime64BestEffort('{{ end_ts }}')
      AND coalesce(nullIf(b.agent_name, ''), toString(b.agent_ip)) = agent_name
      AND ifNull(b.agent_ip, toIPv6('::')) != ifNull(agent_ip, toIPv6('::'))
  ),
  is_current = 0
WHERE is_current = 1
  AND agent_name IS NOT NULL
  AND EXISTS (
    SELECT 1
    FROM bronze.wazuh_events_raw b
    WHERE b.event_ts >= parseDateTime64BestEffort('{{ start_ts }}')
      AND b.event_ts < parseDateTime64BestEffort('{{ end_ts }}')
      AND coalesce(nullIf(b.agent_name, ''), toString(b.agent_ip)) = agent_name
      AND ifNull(b.agent_ip, toIPv6('::')) != ifNull(agent_ip, toIPv6('::'))
  );

INSERT INTO {{ params.target_table }} (
  agent_key,
  agent_name,
  agent_ip,
  effective_from,
  effective_to,
  is_current
)
WITH
  parseDateTime64BestEffort('{{ start_ts }}') AS start_ts,
  parseDateTime64BestEffort('{{ end_ts }}') AS end_ts
SELECT
  cityHash64(agent_name, toString(change_ts)) AS agent_key,
  agent_name,
  agent_ip,
  change_ts AS effective_from,
  NULL AS effective_to,
  1 AS is_current
FROM (
  SELECT
    coalesce(nullIf(b.agent_name, ''), toString(b.agent_ip)) AS agent_name,
    argMin(b.agent_ip, b.event_ts) AS agent_ip,
    min(toTimeZone(b.event_ts, 'Asia/Jakarta')) AS change_ts
  FROM bronze.wazuh_events_raw b
  LEFT JOIN {{ params.target_table }} d
    ON d.agent_name = coalesce(nullIf(b.agent_name, ''), toString(b.agent_ip))
    AND d.is_current = 1
  WHERE b.event_ts >= start_ts AND b.event_ts < end_ts
    AND coalesce(nullIf(b.agent_name, ''), toString(b.agent_ip)) IS NOT NULL
    AND (
      d.agent_name IS NULL
      OR ifNull(b.agent_ip, toIPv6('::')) != ifNull(d.agent_ip, toIPv6('::'))
    )
  GROUP BY agent_name
) changes;
