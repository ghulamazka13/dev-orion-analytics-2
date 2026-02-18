import re

import pandas as pd
import streamlit as st

from datapipeline_manager import db, ui


ui.set_page_config("Projects")
ui.inject_css()
ui.require_auth()
ui.sidebar()
ui.header("Projects", "Manage project catalog and retention")


_NON_IDENT_RE = re.compile(r"[^A-Za-z0-9_]+")
_MULTI_UNDERSCORE_RE = re.compile(r"_+")
_CH_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _normalize_token(value: str) -> str:
    token = (value or "").strip()
    if not token:
        return ""
    token = _NON_IDENT_RE.sub("_", token)
    token = _MULTI_UNDERSCORE_RE.sub("_", token)
    token = token.strip("_")
    return token.lower()


def _derive_clickhouse_namespace(project_id: str, name: str) -> str:
    project_token = _normalize_token(project_id)
    name_token = _normalize_token(name)
    if project_token and project_token[0].isalpha():
        namespace = project_token
    else:
        namespace = name_token or project_token or "project"
    if not namespace[0].isalpha():
        namespace = f"p_{namespace}"
    return namespace

HAS_CH_NAMESPACE = True
try:
    projects = db.fetch_all(
        """
        SELECT project_id, name, clickhouse_namespace, timezone, retention_days, enabled, created_at, updated_at
        FROM metadata.projects
        ORDER BY project_id
        """
    )
except Exception:
    HAS_CH_NAMESPACE = False
    projects = db.fetch_all(
        """
        SELECT project_id, name, NULL::text AS clickhouse_namespace, timezone, retention_days, enabled, created_at, updated_at
        FROM metadata.projects
        ORDER BY project_id
        """
    )

st.markdown("### Project List")
search = st.text_input("Search by project_id or name", value="")
status_filter = st.selectbox("Filter by status", ["all", "enabled", "disabled"], index=0)

filtered = []
for row in projects:
    match = search.lower() in (row["project_id"] + " " + row["name"]).lower()
    status_ok = (
        status_filter == "all"
        or (status_filter == "enabled" and row["enabled"])
        or (status_filter == "disabled" and not row["enabled"])
    )
    if match and status_ok:
        filtered.append(row)

df = pd.DataFrame(filtered)
page_size = st.selectbox("Rows per page", [10, 20, 50], index=1)
total_pages = max(1, (len(df) + page_size - 1) // page_size)
page = st.number_input("Page", min_value=1, max_value=total_pages, value=1)
start = (page - 1) * page_size
end = start + page_size

st.dataframe(df.iloc[start:end] if not df.empty else df, use_container_width=True)

st.markdown("### Create Project")
st.caption("ClickHouse DB memakai namespace: <clickhouse_namespace>_bronze dan <clickhouse_namespace>_gold.")
if not HAS_CH_NAMESPACE:
    st.warning(
        "Kolom `clickhouse_namespace` belum ada. Jalankan migration metadata "
        "(`ALTER TABLE metadata.projects ADD COLUMN IF NOT EXISTS clickhouse_namespace TEXT`)."
    )
with st.form("create_project"):
    project_id = st.text_input("Project ID", help="Alphanumeric + underscore only.")
    name = st.text_input("Project Name")
    clickhouse_namespace = st.text_input(
        "ClickHouse Namespace (optional)",
        help="Jika kosong: pakai Project ID (jika diawali huruf), jika tidak pakai Project Name.",
    )
    timezone = st.text_input("Timezone", value="UTC")
    retention_days = st.number_input("Retention Days", min_value=0, step=1, value=90)
    enabled = st.checkbox("Enabled", value=True)
    submitted = st.form_submit_button("Create Project")
    if submitted:
        if not project_id or not project_id.replace("_", "").isalnum():
            st.error("Project ID must be alphanumeric + underscore.")
        elif not name:
            st.error("Project name is required.")
        else:
            if not HAS_CH_NAMESPACE:
                st.error("Schema metadata belum mendukung `clickhouse_namespace`.")
                st.stop()
            namespace = (clickhouse_namespace or "").strip().lower()
            if not namespace:
                namespace = _derive_clickhouse_namespace(project_id, name)
            if not _CH_IDENT_RE.match(namespace):
                st.error(
                    "ClickHouse Namespace tidak valid. Gunakan huruf/angka/underscore "
                    "dan harus diawali huruf."
                )
                st.stop()
            try:
                db.execute(
                    """
                    INSERT INTO metadata.projects (
                      project_id, name, clickhouse_namespace, timezone, retention_days, enabled, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, now(), now())
                    """,
                    (project_id, name, namespace, timezone, retention_days, enabled),
                )
                ui.notify("Project created.")
                st.rerun()
            except Exception as exc:
                st.error(f"Create failed: {exc}")

st.markdown("### Edit / Enable / Disable")
project_ids = [row["project_id"] for row in projects]
selected = st.selectbox("Select project", options=project_ids or ["no-projects"])
current = next((row for row in projects if row["project_id"] == selected), None)

if current:
    with st.form("edit_project"):
        name = st.text_input("Project Name", value=current["name"])
        clickhouse_namespace = st.text_input(
            "ClickHouse Namespace",
            value=current.get("clickhouse_namespace") or _derive_clickhouse_namespace(current["project_id"], current["name"]),
            help="Digunakan sebagai prefix database ClickHouse.",
        )
        timezone = st.text_input("Timezone", value=current["timezone"])
        retention_days = st.number_input(
            "Retention Days", min_value=0, step=1, value=current["retention_days"] or 0
        )
        enabled = st.checkbox("Enabled", value=current["enabled"])
        submitted = st.form_submit_button("Update Project")
        if submitted:
            if not HAS_CH_NAMESPACE:
                st.error("Schema metadata belum mendukung `clickhouse_namespace`.")
                st.stop()
            namespace = (clickhouse_namespace or "").strip().lower()
            if not namespace:
                namespace = _derive_clickhouse_namespace(current["project_id"], name)
            if not _CH_IDENT_RE.match(namespace):
                st.error(
                    "ClickHouse Namespace tidak valid. Gunakan huruf/angka/underscore "
                    "dan harus diawali huruf."
                )
                st.stop()
            try:
                rowcount = db.execute(
                    """
                    UPDATE metadata.projects
                    SET name = %s,
                        clickhouse_namespace = %s,
                        timezone = %s,
                        retention_days = %s,
                        enabled = %s,
                        updated_at = now()
                    WHERE project_id = %s
                      AND updated_at = %s
                    """,
                    (
                        name,
                        namespace,
                        timezone,
                        retention_days,
                        enabled,
                        current["project_id"],
                        current["updated_at"],
                    ),
                )
                if rowcount == 0:
                    st.error("Update conflict: project was modified by another user.")
                else:
                    ui.notify("Project updated.")
                    st.rerun()
            except Exception as exc:
                st.error(f"Update failed: {exc}")
