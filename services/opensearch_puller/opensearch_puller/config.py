import os


def _get_env(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


POSTGRES_DSN = _get_env(
    "POSTGRES_DSN",
    "postgresql://airflow:airflow@postgres:5432/airflow",
)
CLICKHOUSE_HTTP_URL = _get_env("CLICKHOUSE_HTTP_URL", "http://clickhouse:8123")
LOG_LEVEL = _get_env("LOG_LEVEL", "INFO").upper()
BATCH_SIZE = int(_get_env("BATCH_SIZE", "500"))
OVERLAP_MINUTES = int(_get_env("OVERLAP_MINUTES", "10"))
POLL_INTERVAL_SECONDS = int(_get_env("POLL_INTERVAL_SECONDS", "30"))
OPENSEARCH_VERIFY_SSL = _get_env("OPENSEARCH_VERIFY_SSL", "true").lower() not in {
    "0",
    "false",
    "no",
}
OPENSEARCH_TIMEOUT_SECONDS = int(_get_env("OPENSEARCH_TIMEOUT_SECONDS", "30"))
CLICKHOUSE_TIMEOUT_SECONDS = int(_get_env("CLICKHOUSE_TIMEOUT_SECONDS", "30"))
MAX_RETRIES = int(_get_env("MAX_RETRIES", "3"))
BACKOFF_BASE_SECONDS = float(_get_env("BACKOFF_BASE_SECONDS", "1"))
RATE_LIMIT_SECONDS = float(_get_env("RATE_LIMIT_SECONDS", "0"))
WORKER_ID = os.getenv("WORKER_ID") or os.getenv("HOSTNAME", "opensearch-puller")
SECRET_KEY = os.getenv("ITSEC_SECRET_KEY") or os.getenv("ITSEC_UI_PASSWORD") or ""
