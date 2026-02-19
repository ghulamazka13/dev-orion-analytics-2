import os


def _get_env(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _as_bool(value: str) -> bool:
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


POSTGRES_DSN = _get_env(
    "POSTGRES_DSN",
    "postgresql://airflow:airflow@postgres:5432/airflow",
)
CLICKHOUSE_HTTP_URL = _get_env("CLICKHOUSE_HTTP_URL", "http://clickhouse:8123")
LOG_LEVEL = _get_env("LOG_LEVEL", "INFO").upper()
ENABLE_METADATA_BRONZE_PARSING = _as_bool(
    _get_env("ENABLE_METADATA_BRONZE_PARSING", "false")
)
