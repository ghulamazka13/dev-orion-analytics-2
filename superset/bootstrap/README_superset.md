# Superset bootstrap

1) Log in at http://localhost:18089 with admin/admin
2) Settings -> Database -> + Database
3) SQLAlchemy URI:
   clickhouse+connect://superset:superset@clickhouse:8123/default
4) Test and Save
5) Add datasets from the gold schema only (facts + dims)

Suggested datasets:
- gold.fact_suricata_events
- gold.fact_wazuh_events
- gold.fact_zeek_events
- gold.dim_signature
- gold.dim_protocol
