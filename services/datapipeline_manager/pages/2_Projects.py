import pandas as pd
import streamlit as st

from datapipeline_manager import db, ui


ui.set_page_config("Projects")
ui.inject_css()
ui.require_auth()
ui.sidebar()
ui.header("Projects", "Manage project catalog and retention")

projects = db.fetch_all(
    """
    SELECT project_id, name, timezone, retention_days, enabled, created_at, updated_at
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
st.caption("Project ID is used to create ClickHouse databases: <project_id>_bronze and <project_id>_gold.")
with st.form("create_project"):
    project_id = st.text_input("Project ID", help="Alphanumeric + underscore only.")
    name = st.text_input("Project Name")
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
            try:
                db.execute(
                    """
                    INSERT INTO metadata.projects (
                      project_id, name, timezone, retention_days, enabled, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, now(), now())
                    """,
                    (project_id, name, timezone, retention_days, enabled),
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
        timezone = st.text_input("Timezone", value=current["timezone"])
        retention_days = st.number_input(
            "Retention Days", min_value=0, step=1, value=current["retention_days"] or 0
        )
        enabled = st.checkbox("Enabled", value=current["enabled"])
        submitted = st.form_submit_button("Update Project")
        if submitted:
            try:
                rowcount = db.execute(
                    """
                    UPDATE metadata.projects
                    SET name = %s,
                        timezone = %s,
                        retention_days = %s,
                        enabled = %s,
                        updated_at = now()
                    WHERE project_id = %s
                      AND updated_at = %s
                    """,
                    (
                        name,
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
