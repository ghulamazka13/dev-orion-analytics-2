INSERT INTO {{ params.target_table }} (
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
WITH
  parseDateTime64BestEffort('{{ start_ts }}') AS start_ts,
  parseDateTime64BestEffort('{{ end_ts }}') AS end_ts,
  'Asia/Jakarta' AS tz
SELECT
  s.date_key,
  s.date,
  s.year,
  s.quarter,
  s.month,
  s.day,
  s.week_of_year,
  s.day_of_week,
  now64(3, tz) AS updated_at
FROM (
  SELECT DISTINCT
    toYYYYMMDD(event_date) AS date_key,
    event_date AS date,
    toYear(event_date) AS year,
    toQuarter(event_date) AS quarter,
    toMonth(event_date) AS month,
    toDayOfMonth(event_date) AS day,
    toISOWeek(event_date) AS week_of_year,
    toDayOfWeek(event_date) AS day_of_week
  FROM (
    SELECT toDate(toTimeZone(event_ts, tz)) AS event_date
    FROM bronze.wazuh_events_raw
    WHERE event_ts >= start_ts AND event_ts < end_ts
    UNION ALL
    SELECT toDate(toTimeZone(event_ts, tz)) AS event_date
    FROM bronze.suricata_events_raw
    WHERE event_ts >= start_ts AND event_ts < end_ts
    UNION ALL
    SELECT toDate(toTimeZone(event_ts, tz)) AS event_date
    FROM bronze.zeek_events_raw
    WHERE event_ts >= start_ts AND event_ts < end_ts
  )
) s
LEFT JOIN {{ params.target_table }} d
  ON d.date_key = s.date_key
WHERE d.date_key IS NULL;
