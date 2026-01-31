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
CLICKHOUSE_HTTP_URL = _get_env("CLICKHOUSE_HTTP_URL", "http://admin:admin@clickhouse:8123")
OPENSEARCH_VERIFY_SSL = _get_env("OPENSEARCH_VERIFY_SSL", "true").lower() not in {
    "0",
    "false",
    "no",
}
UI_USER = _get_env("ITSEC_UI_USER", "admin")
UI_PASSWORD = _get_env("ITSEC_UI_PASSWORD", "admin123!")
PAGE_SIZE_DEFAULT = int(_get_env("ITSEC_PAGE_SIZE", "20"))
AUTH_TTL_SECONDS = int(_get_env("ITSEC_AUTH_TTL_SECONDS", "3600"))
AUTH_COOKIE_NAME = _get_env("ITSEC_AUTH_COOKIE_NAME", "itsec_auth")
AUTH_COOKIE_SECURE = _get_env("ITSEC_AUTH_COOKIE_SECURE", "true").lower() not in {
    "0",
    "false",
    "no",
}
AUTH_COOKIE_SAMESITE = _get_env("ITSEC_AUTH_COOKIE_SAMESITE", "Lax")
