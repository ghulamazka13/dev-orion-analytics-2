ALTER TABLE {{ params.target_table }}
UPDATE
  effective_to = (
    SELECT min(toTimeZone(b.event_ts, 'Asia/Jakarta'))
    FROM bronze.wazuh_events_raw b
    WHERE b.event_ts >= parseDateTime64BestEffort('{{ start_ts }}')
      AND b.event_ts < parseDateTime64BestEffort('{{ end_ts }}')
      AND nullIf(b.rule_id, '') = rule_id
      AND (
        ifNull(b.rule_level, -1) != ifNull(rule_level, -1)
        OR ifNull(b.rule_name, '') != ifNull(rule_name, '')
        OR ifNull(b.rule_ruleset, '') != ifNull(rule_ruleset, '')
      )
  ),
  is_current = 0
WHERE is_current = 1
  AND rule_id IS NOT NULL
  AND EXISTS (
    SELECT 1
    FROM bronze.wazuh_events_raw b
    WHERE b.event_ts >= parseDateTime64BestEffort('{{ start_ts }}')
      AND b.event_ts < parseDateTime64BestEffort('{{ end_ts }}')
      AND nullIf(b.rule_id, '') = rule_id
      AND (
        ifNull(b.rule_level, -1) != ifNull(rule_level, -1)
        OR ifNull(b.rule_name, '') != ifNull(rule_name, '')
        OR ifNull(b.rule_ruleset, '') != ifNull(rule_ruleset, '')
      )
  );

INSERT INTO {{ params.target_table }} (
  rule_key,
  rule_id,
  rule_level,
  rule_name,
  rule_ruleset,
  effective_from,
  effective_to,
  is_current
)
WITH
  parseDateTime64BestEffort('{{ start_ts }}') AS start_ts,
  parseDateTime64BestEffort('{{ end_ts }}') AS end_ts
SELECT
  cityHash64(rule_id, toString(change_ts)) AS rule_key,
  rule_id,
  rule_level,
  rule_name,
  rule_ruleset,
  change_ts AS effective_from,
  NULL AS effective_to,
  1 AS is_current
FROM (
  SELECT
    nullIf(b.rule_id, '') AS rule_id,
    argMin(b.rule_level, b.event_ts) AS rule_level,
    argMin(b.rule_name, b.event_ts) AS rule_name,
    argMin(b.rule_ruleset, b.event_ts) AS rule_ruleset,
    min(toTimeZone(b.event_ts, 'Asia/Jakarta')) AS change_ts
  FROM bronze.wazuh_events_raw b
  LEFT JOIN {{ params.target_table }} d
    ON d.rule_id = nullIf(b.rule_id, '')
    AND d.is_current = 1
  WHERE b.event_ts >= start_ts AND b.event_ts < end_ts
    AND nullIf(b.rule_id, '') IS NOT NULL
    AND (
      d.rule_id IS NULL
      OR ifNull(b.rule_level, -1) != ifNull(d.rule_level, -1)
      OR ifNull(b.rule_name, '') != ifNull(d.rule_name, '')
      OR ifNull(b.rule_ruleset, '') != ifNull(d.rule_ruleset, '')
    )
  GROUP BY rule_id
) changes;
