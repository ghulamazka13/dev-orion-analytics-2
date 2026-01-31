import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from dateutil import parser


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")


def require_identifier(value: str) -> str:
    if not value or not _IDENTIFIER_RE.match(value):
        raise ValueError(f"Invalid identifier: {value!r}")
    return value


def quote_identifier(value: str) -> str:
    return f"`{require_identifier(value)}`"


def parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Heuristic: treat large numbers as epoch milliseconds.
        seconds = value / 1000.0 if value > 1e11 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str):
        dt = parser.isoparse(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    if isinstance(value, dict) and "$date" in value:
        return parse_timestamp(value["$date"])
    return None


def format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def format_timestamp_ch(value: datetime) -> str:
    # ClickHouse DateTime64(3) expects "YYYY-MM-DD HH:MM:SS.mmm"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def safe_json_load(value: Any) -> Dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}
