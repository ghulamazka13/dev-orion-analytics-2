from typing import Any, Dict, List

import requests

from .config import CLICKHOUSE_HTTP_URL


def query_json(sql: str, timeout: int = 20) -> Dict[str, Any]:
    query = sql.strip()
    if "FORMAT" not in query.upper():
        query = f"{query}\nFORMAT JSON"
    response = requests.post(
        CLICKHOUSE_HTTP_URL.rstrip("/") + "/",
        params={"query": query},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def query_rows(sql: str, timeout: int = 20) -> List[Dict[str, Any]]:
    payload = query_json(sql, timeout=timeout)
    return payload.get("data", [])
