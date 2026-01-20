SELECT count() FROM bronze.suricata_events_raw;
SELECT count() FROM bronze.wazuh_events_raw;
SELECT count() FROM bronze.zeek_events_raw;

SELECT count() FROM gold.fact_suricata_events;
SELECT count() FROM gold.fact_wazuh_events;
SELECT count() FROM gold.fact_zeek_events;

SELECT severity, count() AS event_count
FROM gold.fact_suricata_events
GROUP BY severity
ORDER BY event_count DESC
LIMIT 10;

SELECT toDate(event_ts) AS event_date, count() AS event_count
FROM gold.fact_wazuh_events
GROUP BY event_date
ORDER BY event_date DESC
LIMIT 7;

SELECT
  d.signature AS signature,
  count() AS event_count
FROM gold.fact_suricata_events f
LEFT JOIN gold.dim_signature d
  ON f.signature_key = d.signature_key
GROUP BY d.signature
ORDER BY event_count DESC
LIMIT 10;
