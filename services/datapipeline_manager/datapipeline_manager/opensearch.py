from typing import Dict, List, Optional, Tuple

import requests

from .config import OPENSEARCH_VERIFY_SSL


def _build_session(auth_type: Optional[str], username: Optional[str], secret: Optional[str]) -> requests.Session:
    session = requests.Session()
    auth = (auth_type or "").strip().lower()
    if auth == "basic" and username and secret:
        session.auth = (username, secret)
    elif auth == "api_key" and secret:
        session.headers["Authorization"] = f"ApiKey {secret}"
    elif auth == "bearer" and secret:
        session.headers["Authorization"] = f"Bearer {secret}"
    return session


def test_connection(
    base_url: str,
    index_pattern: str,
    auth_type: Optional[str],
    username: Optional[str],
    secret: Optional[str],
    timeout: int = 15,
) -> Tuple[bool, str, List[str]]:
    session = _build_session(auth_type, username, secret)
    url = base_url.rstrip("/") + f"/_cat/indices/{index_pattern}"
    try:
        response = session.get(
            url,
            params={"format": "json", "h": "index,status"},
            timeout=timeout,
            verify=OPENSEARCH_VERIFY_SSL,
        )
        if response.status_code == 404:
            return False, "No indices matched the pattern.", []
        response.raise_for_status()
        indices = []
        for row in response.json():
            if row.get("status") == "close":
                continue
            index_name = row.get("index")
            if index_name:
                indices.append(index_name)
        if not indices:
            return False, "No open indices found.", []
        return True, f"Found {len(indices)} indices.", indices
    except requests.RequestException as exc:
        return False, f"Connection failed: {exc}", []
