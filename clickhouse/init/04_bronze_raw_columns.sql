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
  ADD COLUMN IF NOT EXISTS dns_auth Nullable(UInt8),
  ADD COLUMN IF NOT EXISTS ssh_auth_success Nullable(UInt8),
  ADD COLUMN IF NOT EXISTS ssh_auth_attempts Nullable(Int32),
  ADD COLUMN IF NOT EXISTS http_method Nullable(String),
  ADD COLUMN IF NOT EXISTS http_uri Nullable(String),
  ADD COLUMN IF NOT EXISTS http_referrer Nullable(String),
  ADD COLUMN IF NOT EXISTS http_user_agent Nullable(String),
  ADD COLUMN IF NOT EXISTS http_request_body_len Nullable(Int64),
  ADD COLUMN IF NOT EXISTS http_response_body_len Nullable(Int64),
  ADD COLUMN IF NOT EXISTS http_status_code Nullable(Int32);
