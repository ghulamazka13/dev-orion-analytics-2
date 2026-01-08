SELECT window_start, severity, alert_count
FROM gold.alerts_5m
ORDER BY window_start DESC
LIMIT 50;

SELECT event_date, signature, alert_count
FROM gold.top_signatures_daily
ORDER BY event_date DESC, alert_count DESC
LIMIT 20;

SELECT event_date, protocol, pct_of_total
FROM gold.protocol_mix_daily
ORDER BY event_date DESC, pct_of_total DESC;
