# Superset bootstrap

1) Log in at http://localhost:8089 with admin/admin
2) Settings -> Database -> + Database
3) SQLAlchemy URI:
   postgresql://bi_reader:bi_reader@postgres:5432/analytics
4) Test and Save
5) Add datasets from the gold schema only

Optional example datasets:
- gold.alerts_5m
- gold.alerts_1h
- gold.alerts_daily
- gold.top_talkers_daily
- gold.top_signatures_daily
- gold.protocol_mix_daily
