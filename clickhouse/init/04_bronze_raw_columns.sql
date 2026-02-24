ALTER TABLE bronze.suricata_events_raw
  ADD COLUMN IF NOT EXISTS raw String,
  ADD COLUMN IF NOT EXISTS extras Map(String, String) DEFAULT map();

ALTER TABLE bronze.wazuh_events_raw
  ADD COLUMN IF NOT EXISTS raw String,
  ADD COLUMN IF NOT EXISTS extras Map(String, String) DEFAULT map();

ALTER TABLE bronze.zeek_events_raw
  ADD COLUMN IF NOT EXISTS raw String,
  ADD COLUMN IF NOT EXISTS extras Map(String, String) DEFAULT map(),
  ADD COLUMN IF NOT EXISTS dns_qclass_name Nullable(String),
  ADD COLUMN IF NOT EXISTS dns_qtype_name Nullable(String),
  ADD COLUMN IF NOT EXISTS dns_answers Array(String) DEFAULT [],
  ADD COLUMN IF NOT EXISTS dns_ttls Array(Int64) DEFAULT [],
  ADD COLUMN IF NOT EXISTS dns_rejected Nullable(UInt8),
  ADD COLUMN IF NOT EXISTS dns_auth Nullable(UInt8);
