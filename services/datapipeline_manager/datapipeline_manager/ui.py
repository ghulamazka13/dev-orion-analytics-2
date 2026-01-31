import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import streamlit as st
from cryptography.fernet import Fernet, InvalidToken

from . import config, db

APP_TITLE = "ITSEC Datapipeline Manager"
DEFAULT_PAGE = "Dashboard.py"
ROLE_OPTIONS = ("viewer", "editor", "admin")
ROLE_LEVELS = {"viewer": 1, "editor": 2, "admin": 3}


def set_page_config(title: str) -> None:
    st.set_page_config(
        page_title=f"{title} | {APP_TITLE}",
        page_icon="🛰️",
        layout="wide",
    )


def _rerun() -> None:
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


def _switch_page(page: str) -> bool:
    if hasattr(st, "switch_page"):
        st.switch_page(page)
        return True
    return False


def inject_css(hide_sidebar: bool = False) -> None:
    hide_css = ""
    if hide_sidebar:
        hide_css = """
        section[data-testid="stSidebar"] { display: none; }
        [data-testid="collapsedControl"] { display: none; }
        """

    st.markdown(
        f"""
        <style>
          @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600&display=swap');
          :root {{
            --itsec-ink: #e2e8f0;
            --itsec-muted: #94a3b8;
            --itsec-border: #1f2937;
            --itsec-card: #0f172a;
            --itsec-surface: #0b1117;
            --itsec-panel: #111827;
            --itsec-navy: #0b1d2a;
            --itsec-accent: #38bdf8;
            --itsec-accent-2: #34d399;
            --itsec-accent-3: #f59e0b;
          }}
          html, body, [class*="css"]  {{
            font-family: "Space Grotesk", "Segoe UI", sans-serif;
            color: var(--itsec-ink);
          }}
          .stApp {{
            background: radial-gradient(circle at 10% 10%, #0f1b2b 0%, #0b1117 45%, #0b1117 100%);
          }}
          main .block-container {{
            padding-top: 1.4rem;
            padding-bottom: 2.5rem;
            max-width: 1200px;
          }}
          h1, h2, h3, h4, h5 {{
            color: var(--itsec-ink);
          }}
          .itsec-header {{
            padding: 18px 22px;
            background: linear-gradient(120deg, #0b1d2a, #143a52);
            color: #f7fbff;
            border-radius: 18px;
            margin-bottom: 20px;
            box-shadow: 0 16px 32px rgba(15, 23, 42, 0.18);
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 16px;
          }}
          .itsec-header h1 {{
            color: #f8fafc;
            margin: 0;
            font-size: 28px;
            font-weight: 600;
          }}
          .itsec-header p {{
            color: #e2e8f0;
            margin: 6px 0 0;
            opacity: 0.85;
          }}
          .itsec-pill {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 999px;
            background: rgba(255,255,255,0.16);
            color: #e2e8f0;
            font-size: 12px;
            letter-spacing: 0.4px;
            text-transform: uppercase;
          }}
          .itsec-card {{
            background: var(--itsec-card);
            border-radius: 16px;
            padding: 16px;
            border: 1px solid var(--itsec-border);
            box-shadow: 0 12px 24px rgba(2, 6, 23, 0.35);
          }}
          .itsec-card--metric {{
            border-left: 4px solid var(--itsec-accent);
            min-height: 110px;
          }}
          .itsec-muted {{
            color: var(--itsec-muted);
            font-size: 13px;
          }}
          .itsec-metric {{
            font-size: 30px;
            font-weight: 600;
          }}
          .itsec-metric-caption {{
            color: var(--itsec-muted);
            font-size: 12px;
          }}
          div[data-testid="stMetric"] {{
            background: var(--itsec-card);
            border-radius: 14px;
            padding: 14px 16px;
            border: 1px solid var(--itsec-border);
            box-shadow: 0 10px 18px rgba(2, 6, 23, 0.35);
          }}
          div[data-testid="stDataFrame"] {{
            background: var(--itsec-card);
            border-radius: 14px;
            border: 1px solid var(--itsec-border);
            box-shadow: 0 10px 18px rgba(2, 6, 23, 0.35);
            padding: 6px;
          }}
          div[data-testid="stForm"] {{
            background: var(--itsec-card);
            border-radius: 18px;
            border: 1px solid var(--itsec-border);
            padding: 18px;
            box-shadow: 0 14px 28px rgba(2, 6, 23, 0.35);
          }}
          div[data-testid="stMetric"] label,
          div[data-testid="stMetric"] span {{
            color: var(--itsec-ink);
          }}
          div[data-testid="stDataFrame"] * {{
            color: var(--itsec-ink);
          }}
          div[data-testid="stDataFrame"] div[role="columnheader"],
          div[data-testid="stDataFrame"] div[role="gridcell"] {{
            background: var(--itsec-card);
            border-color: var(--itsec-border);
          }}
          label, .stCaption, .stMarkdown, .stMarkdown p {{
            color: var(--itsec-ink);
          }}
          .stCaption {{
            color: var(--itsec-muted);
          }}
          div[data-baseweb="input"] input,
          div[data-baseweb="textarea"] textarea {{
            background: #0b1220;
            color: var(--itsec-ink);
            border: 1px solid var(--itsec-border);
          }}
          div[data-baseweb="input"] input::placeholder,
          div[data-baseweb="textarea"] textarea::placeholder {{
            color: #64748b;
          }}
          div[data-baseweb="select"] > div {{
            background: #0b1220;
            color: var(--itsec-ink);
            border: 1px solid var(--itsec-border);
          }}
          div[data-baseweb="select"] svg {{
            fill: var(--itsec-ink);
          }}
          div[role="listbox"] {{
            background: var(--itsec-card);
            color: var(--itsec-ink);
            border: 1px solid var(--itsec-border);
          }}
          div[role="listbox"] div[role="option"] {{
            color: var(--itsec-ink);
          }}
          div[role="listbox"] div[aria-selected="true"] {{
            background: #1f2937;
          }}
          .stCheckbox span, .stRadio span {{
            color: var(--itsec-ink);
          }}
          div[data-baseweb="tab-list"] {{
            gap: 6px;
          }}
          div[data-baseweb="tab"] {{
            color: var(--itsec-ink);
            font-weight: 500;
            padding: 0.35rem 0.8rem;
            border-radius: 10px;
          }}
          div[data-baseweb="tab"][aria-selected="true"] {{
            background: #1f2937;
            color: var(--itsec-ink);
          }}
          div.stButton > button {{
            border-radius: 12px;
            border: 1px solid transparent;
            background: linear-gradient(120deg, #1d4ed8, #0ea5e9);
            color: #ffffff;
            padding: 0.5rem 1rem;
          }}
          div.stButton > button:hover {{
            filter: brightness(1.05);
          }}
          section[data-testid="stSidebar"] {{
            background: linear-gradient(180deg, #0b1d2a 0%, #123247 55%, #0b1d2a 100%);
          }}
          section[data-testid="stSidebar"] * {{
            color: #e2e8f0 !important;
          }}
          [data-testid="stSidebarNav"] {{
            margin-top: 1rem;
          }}
          [data-testid="stSidebarNav"] a {{
            border-radius: 10px;
            padding: 0.35rem 0.6rem;
          }}
          [data-testid="stSidebarNav"] a:hover {{
            background: rgba(255,255,255,0.08);
          }}
          [data-testid="stSidebarNav"] [aria-current="page"] {{
            background: rgba(56, 189, 248, 0.2);
            border-left: 3px solid var(--itsec-accent);
            padding-left: 0.45rem;
          }}
          .itsec-login-hero {{
            text-align: center;
            margin: 2rem auto 1.5rem;
            max-width: 520px;
          }}
          .itsec-login-hero h1 {{
            margin-bottom: 0.5rem;
          }}
          .itsec-login-hero p {{
            color: var(--itsec-muted);
          }}
          {hide_css}
          #MainMenu {{ visibility: hidden; }}
          footer {{ visibility: hidden; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def header(title: str, subtitle: Optional[str] = None) -> None:
    st.markdown(
        f"""
        <div class="itsec-header">
          <div>
            <div class="itsec-pill">Control Plane</div>
            <h1>{title}</h1>
            <p>{subtitle or APP_TITLE}</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def sidebar() -> None:
    st.sidebar.markdown(
        """
        <div style="margin-bottom: 0.75rem;">
          <div style="font-size: 18px; font-weight: 600;">ITSEC Datapipeline Manager</div>
          <div style="font-size: 12px; opacity: 0.8;">Operational control plane</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if is_authenticated():
        username = st.session_state.get("username") or config.UI_USER
        role = st.session_state.get("role") or "admin"
        st.sidebar.markdown(
            f"""
            <div style="margin-bottom: 0.75rem;">
              <div style="font-size: 12px; opacity: 0.7;">Signed in as</div>
              <div style="font-size: 14px; font-weight: 600;">{username}</div>
              <div style="font-size: 12px; opacity: 0.7;">Role: {role}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    if config.UI_PASSWORD and is_authenticated():
        if st.sidebar.button("Sign out", use_container_width=True):
            st.session_state.pop("authenticated", None)
            st.session_state.pop("username", None)
            st.session_state.pop("role", None)
            _rerun()


def notify(message: str, level: str = "success") -> None:
    if hasattr(st, "toast"):
        st.toast(message)
        return
    if level == "success":
        st.success(message)
    elif level == "error":
        st.error(message)
    elif level == "warning":
        st.warning(message)
    else:
        st.info(message)


def is_authenticated() -> bool:
    if not config.UI_PASSWORD:
        return True
    return bool(st.session_state.get("authenticated"))


def login_page() -> None:
    if not config.UI_PASSWORD:
        st.session_state["authenticated"] = True
        _rerun()

    if is_authenticated():
        return

    st.markdown(
        """
        <div class="itsec-login-hero">
          <div class="itsec-pill">Secure access</div>
          <h1>Welcome back</h1>
          <p>Sign in to manage projects, sources, backfills, and schema changes.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("Username", placeholder="admin")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in")

        if submitted:
            user, error = authenticate_user(username, password)
            if user:
                st.session_state["authenticated"] = True
                st.session_state["username"] = user["username"]
                st.session_state["role"] = user["role"]
                _rerun()
            else:
                st.error(error or "Invalid credentials.")


def require_auth() -> None:
    if is_authenticated():
        return
    inject_css(hide_sidebar=True)
    login_page()
    st.stop()


def parse_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _coerce_bytes(value: Any) -> Optional[bytes]:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, str):
        return value.encode("utf-8")
    return None


def _secret_key() -> Optional[bytes]:
    key_material = os.getenv("ITSEC_SECRET_KEY") or config.UI_PASSWORD
    if not key_material:
        return None
    digest = hashlib.sha256(key_material.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_secret(secret: str) -> Optional[bytes]:
    if not secret:
        return None
    key = _secret_key()
    if not key:
        return secret.encode("utf-8")
    return Fernet(key).encrypt(secret.encode("utf-8"))


def decrypt_secret(secret_enc: Any) -> Optional[str]:
    blob = _coerce_bytes(secret_enc)
    if not blob:
        return None
    key = _secret_key()
    if not key:
        try:
            return blob.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        return Fernet(key).decrypt(blob).decode("utf-8")
    except InvalidToken:
        try:
            return blob.decode("utf-8")
        except UnicodeDecodeError:
            return None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_role(role: Optional[str]) -> str:
    if role in ROLE_LEVELS:
        return role
    return "viewer"


def _hash_password(password: str, iterations: int = 260_000) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (
        iterations,
        base64.b64encode(salt).decode("utf-8"),
        base64.b64encode(dk).decode("utf-8"),
    )


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algo, iterations, salt_b64, hash_b64 = stored_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64.encode("utf-8"))
        expected = base64.b64decode(hash_b64.encode("utf-8"))
        computed = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
        return hmac.compare_digest(computed, expected)
    except Exception:
        return False


def ensure_user_store() -> None:
    db.execute("CREATE SCHEMA IF NOT EXISTS metadata;")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata.ui_users (
          user_id BIGSERIAL PRIMARY KEY,
          username TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'viewer',
          enabled BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def _user_count() -> int:
    row = db.fetch_one("SELECT COUNT(*) AS count FROM metadata.ui_users")
    return int(row["count"]) if row else 0


def get_user(username: str) -> Optional[Dict[str, Any]]:
    return db.fetch_one(
        """
        SELECT username, password_hash, role, enabled, created_at, updated_at
        FROM metadata.ui_users
        WHERE username = %s
        """,
        (username,),
    )


def list_users() -> list[Dict[str, Any]]:
    return db.fetch_all(
        """
        SELECT username, role, enabled, created_at, updated_at
        FROM metadata.ui_users
        ORDER BY username
        """
    )


def create_user(username: str, password: str, role: str = "viewer", enabled: bool = True) -> None:
    role = _normalize_role(role)
    password_hash = _hash_password(password)
    db.execute(
        """
        INSERT INTO metadata.ui_users (username, password_hash, role, enabled, created_at, updated_at)
        VALUES (%s, %s, %s, %s, now(), now())
        """,
        (username, password_hash, role, enabled),
    )


def update_user(username: str, role: str, enabled: bool) -> int:
    role = _normalize_role(role)
    return db.execute(
        """
        UPDATE metadata.ui_users
        SET role = %s,
            enabled = %s,
            updated_at = now()
        WHERE username = %s
        """,
        (role, enabled, username),
    )


def reset_password(username: str, password: str) -> int:
    password_hash = _hash_password(password)
    return db.execute(
        """
        UPDATE metadata.ui_users
        SET password_hash = %s,
            updated_at = now()
        WHERE username = %s
        """,
        (password_hash, username),
    )


def authenticate_user(username: str, password: str) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    ensure_user_store()
    user = get_user(username)
    if user:
        if not user["enabled"]:
            return None, "User is disabled."
        if _verify_password(password, user["password_hash"]):
            return user, None
        return None, "Invalid credentials."
    if _user_count() == 0 and username == config.UI_USER and password == config.UI_PASSWORD:
        create_user(username, password, role="admin", enabled=True)
        user = get_user(username)
        return user, None
    return None, "Invalid credentials."


def require_role(required: str) -> None:
    if not config.UI_PASSWORD:
        return
    current_role = st.session_state.get("role") or "viewer"
    if ROLE_LEVELS.get(current_role, 0) < ROLE_LEVELS.get(required, 0):
        st.error("Access denied. Please contact an administrator.")
        st.stop()
