ALTER TABLE {{ params.target_table }}
UPDATE
  effective_to = (
    SELECT min(toTimeZone(b.event_ts, 'Asia/Jakarta'))
    FROM bronze.wazuh_events_raw b
    WHERE b.event_ts >= parseDateTime64BestEffort('{{ start_ts }}')
      AND b.event_ts < parseDateTime64BestEffort('{{ end_ts }}')
      AND coalesce(nullIf(b.host_name, ''), toString(b.host_ip)) = host_name
      AND ifNull(b.host_ip, toIPv6('::')) != ifNull(host_ip, toIPv6('::'))
  ),
  is_current = 0
WHERE is_current = 1
  AND host_name IS NOT NULL
  AND EXISTS (
    SELECT 1
    FROM bronze.wazuh_events_raw b
    WHERE b.event_ts >= parseDateTime64BestEffort('{{ start_ts }}')
      AND b.event_ts < parseDateTime64BestEffort('{{ end_ts }}')
      AND coalesce(nullIf(b.host_name, ''), toString(b.host_ip)) = host_name
      AND ifNull(b.host_ip, toIPv6('::')) != ifNull(host_ip, toIPv6('::'))
  );

INSERT INTO {{ params.target_table }} (
  host_key,
  host_name,
  host_ip,
  effective_from,
  effective_to,
  is_current
)
WITH
  parseDateTime64BestEffort('{{ start_ts }}') AS start_ts,
  parseDateTime64BestEffort('{{ end_ts }}') AS end_ts
SELECT
  cityHash64(host_name, toString(change_ts)) AS host_key,
  host_name,
  host_ip,
  change_ts AS effective_from,
  NULL AS effective_to,
  1 AS is_current
FROM (
  SELECT
    coalesce(nullIf(b.host_name, ''), toString(b.host_ip)) AS host_name,
    argMin(b.host_ip, b.event_ts) AS host_ip,
    min(toTimeZone(b.event_ts, 'Asia/Jakarta')) AS change_ts
  FROM bronze.wazuh_events_raw b
  LEFT JOIN {{ params.target_table }} d
    ON d.host_name = coalesce(nullIf(b.host_name, ''), toString(b.host_ip))
    AND d.is_current = 1
  WHERE b.event_ts >= start_ts AND b.event_ts < end_ts
    AND coalesce(nullIf(b.host_name, ''), toString(b.host_ip)) IS NOT NULL
    AND (
      d.host_name IS NULL
      OR ifNull(b.host_ip, toIPv6('::')) != ifNull(d.host_ip, toIPv6('::'))
    )
  GROUP BY host_name
) changes;
