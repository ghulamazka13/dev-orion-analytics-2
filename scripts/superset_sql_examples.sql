SELECT
  toStartOfFiveMinute(event_ts) AS window_start,
  severity,
  count() AS alert_count
FROM gold.fact_suricata_events
GROUP BY window_start, severity
ORDER BY window_start DESC
LIMIT 50;

SELECT
  toDate(event_ts) AS event_date,
  d.signature AS signature,
  count() AS alert_count
FROM gold.fact_suricata_events f
LEFT JOIN gold.dim_signature d
  ON f.signature_key = d.signature_key
GROUP BY event_date, signature
ORDER BY event_date DESC, alert_count DESC
LIMIT 20;

SELECT
  toDate(event_ts) AS event_date,
  p.protocol AS protocol,
  count() / sum(count()) OVER (PARTITION BY event_date) AS pct_of_total
FROM gold.fact_suricata_events f
LEFT JOIN gold.dim_protocol p
  ON f.protocol_key = p.protocol_key
GROUP BY event_date, protocol
ORDER BY event_date DESC, pct_of_total DESC;
