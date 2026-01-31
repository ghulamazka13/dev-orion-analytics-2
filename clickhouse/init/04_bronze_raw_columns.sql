ALTER TABLE bronze.suricata_events_raw
  ADD COLUMN IF NOT EXISTS raw String,
  ADD COLUMN IF NOT EXISTS extras Map(String, String) DEFAULT map();

ALTER TABLE bronze.wazuh_events_raw
  ADD COLUMN IF NOT EXISTS raw String,
  ADD COLUMN IF NOT EXISTS extras Map(String, String) DEFAULT map();

ALTER TABLE bronze.zeek_events_raw
  ADD COLUMN IF NOT EXISTS raw String,
  ADD COLUMN IF NOT EXISTS extras Map(String, String) DEFAULT map();
