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
SEAWEED_S3_ENDPOINT = _get_env("SEAWEED_S3_ENDPOINT", "http://seaweedfs:8333")
SEAWEED_S3_REGION = _get_env("SEAWEED_S3_REGION", "us-east-1")
SEAWEED_S3_ACCESS_KEY = _get_env("SEAWEED_S3_ACCESS_KEY", "")
SEAWEED_S3_SECRET_KEY = _get_env("SEAWEED_S3_SECRET_KEY", "")
SEAWEED_S3_BUCKET = _get_env("SEAWEED_S3_BUCKET", "itsec-test")
SEAWEED_S3_VERIFY_SSL = _get_env("SEAWEED_S3_VERIFY_SSL", "false").lower() not in {
    "0",
    "false",
    "no",
}
SEAWEED_S3_ADDRESSING_STYLE = _get_env("SEAWEED_S3_ADDRESSING_STYLE", "path")
OPENSEARCH_VERIFY_SSL = _get_env("OPENSEARCH_VERIFY_SSL", "true").lower() not in {
    "0",
    "false",
    "no",
}
UI_USER = _get_env("ITSEC_UI_USER", "admin")
UI_PASSWORD = _get_env("ITSEC_UI_PASSWORD", "admin123!")
PAGE_SIZE_DEFAULT = int(_get_env("ITSEC_PAGE_SIZE", "20"))
FILE_EXPORT_BATCH_SIZE = int(_get_env("ITSEC_FILE_EXPORT_BATCH_SIZE", "1000"))
FILE_EXPORT_AUTOMATION_POLL_SECONDS = int(_get_env("ITSEC_FILE_EXPORT_AUTOMATION_POLL_SECONDS", "30"))
AUTH_TTL_SECONDS = int(_get_env("ITSEC_AUTH_TTL_SECONDS", "3600"))
AUTH_COOKIE_NAME = _get_env("ITSEC_AUTH_COOKIE_NAME", "itsec_auth")
AUTH_COOKIE_SECURE = _get_env("ITSEC_AUTH_COOKIE_SECURE", "true").lower() not in {
    "0",
    "false",
    "no",
}
AUTH_COOKIE_SAMESITE = _get_env("ITSEC_AUTH_COOKIE_SAMESITE", "Lax")
