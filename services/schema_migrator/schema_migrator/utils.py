import re


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")


def require_identifier(value: str) -> str:
    if not value or not _IDENTIFIER_RE.match(value):
        raise ValueError(f"Invalid identifier: {value!r}")
    return value


def quote_identifier(value: str) -> str:
    return f"`{require_identifier(value)}`"
