from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

import psycopg2
import psycopg2.extras

from .config import POSTGRES_DSN


@contextmanager
def connect():
    conn = psycopg2.connect(POSTGRES_DSN)
    conn.autocommit = True
    try:
        yield conn
    finally:
        conn.close()


def fetch_all(query: str, params: Optional[Iterable[Any]] = None) -> List[Dict[str, Any]]:
    with connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params or ())
            return list(cur.fetchall())


def fetch_one(query: str, params: Optional[Iterable[Any]] = None) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params or ())
            return cur.fetchone()


def execute(query: str, params: Optional[Iterable[Any]] = None) -> int:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            return cur.rowcount
