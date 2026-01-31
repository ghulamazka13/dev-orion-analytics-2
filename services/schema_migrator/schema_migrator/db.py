from typing import Iterable

import psycopg2
import psycopg2.extras
import requests


def connect_postgres(dsn: str):
    return psycopg2.connect(dsn)


class ClickHouseClient:
    def __init__(self, base_url: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.timeout = timeout

    def execute(self, sql: str) -> str:
        response = self.session.post(
            f"{self.base_url}/",
            params={"query": sql},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.text

    def table_exists(self, database: str, table: str) -> bool:
        query = (
            "SELECT count() FROM system.tables "
            f"WHERE database = '{database}' AND name = '{table}' "
            "FORMAT TabSeparated"
        )
        response = self.execute(query)
        try:
            return int(response.strip() or "0") > 0
        except ValueError:
            return False

    def execute_many(self, statements: Iterable[str]) -> None:
        for statement in statements:
            self.execute(statement)
