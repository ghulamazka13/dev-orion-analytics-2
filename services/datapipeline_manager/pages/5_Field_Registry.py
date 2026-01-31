import re
import pandas as pd
import streamlit as st

from datapipeline_manager import db, ui
from schema_migrator.migrator import apply_schema


ui.set_page_config("Field Registry")
ui.inject_css()
ui.require_auth()
ui.sidebar()
ui.header("Field Registry", "Schema evolution and derived fields")

IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")

projects = db.fetch_all("SELECT project_id FROM metadata.projects ORDER BY project_id")
project_ids = [row["project_id"] for row in projects]

fields = db.fetch_all(
    """
    SELECT field_id, project_id, dataset, layer, table_name, column_name, column_type,
           expression_sql, mode, enabled, created_at, updated_at
    FROM metadata.field_registry
    ORDER BY field_id
    """
)

st.markdown("### Create Field Mapping")
with st.form("create_field"):
    project_scope = st.selectbox("Project Scope", ["global"] + project_ids)
    dataset = st.text_input("Dataset", value="generic")
    layer = st.selectbox("Layer", ["bronze", "gold_fact", "gold_dim"])
    table_name = st.text_input("Table Name", value="os_events_raw")
    column_name = st.text_input("Column Name")
    column_type = st.text_input("Column Type", value="Nullable(String)")
    mode = st.selectbox("Mode", ["ALIAS", "MATERIALIZED"])
    expression_sql = st.text_area("Expression SQL", value="JSONExtractString(raw, 'field')", height=80)
    enabled = st.checkbox("Enabled", value=True)
    submitted = st.form_submit_button("Add Field")
    if submitted:
        project_id = None if project_scope == "global" else project_scope
        if not column_name or not IDENT_RE.match(column_name):
            st.error("Column name must be alphanumeric + underscore.")
        elif "." in table_name:
            parts = table_name.split(".", 1)
            if not IDENT_RE.match(parts[0]) or not IDENT_RE.match(parts[1]):
                st.error("Table name parts must be alphanumeric + underscore.")
        elif not IDENT_RE.match(table_name):
            st.error("Table name must be alphanumeric + underscore.")
        else:
            db.execute(
                """
                INSERT INTO metadata.field_registry (
                  project_id, dataset, layer, table_name, column_name, column_type,
                  expression_sql, mode, enabled, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                """,
                (
                    project_id,
                    dataset,
                    layer,
                    table_name,
                    column_name,
                    column_type,
                    expression_sql,
                    mode,
                    enabled,
                ),
            )
            ui.notify("Field registered.")
            st.rerun()

st.markdown("### Registered Fields")
project_filter = st.selectbox("Filter by project", ["all"] + project_ids, index=0)
layer_filter = st.selectbox("Filter by layer", ["all", "bronze", "gold_fact", "gold_dim"], index=0)
status_filter = st.selectbox("Filter by status", ["all", "enabled", "disabled"], index=0)

filtered = []
for row in fields:
    project_ok = project_filter == "all" or row["project_id"] == project_filter
    layer_ok = layer_filter == "all" or row["layer"] == layer_filter
    status_ok = (
        status_filter == "all"
        or (status_filter == "enabled" and row["enabled"])
        or (status_filter == "disabled" and not row["enabled"])
    )
    if project_ok and layer_ok and status_ok:
        filtered.append(row)

df = pd.DataFrame(filtered)
page_size = st.selectbox("Rows per page", [10, 20, 50], index=1)
total_pages = max(1, (len(df) + page_size - 1) // page_size)
page = st.number_input("Page", min_value=1, max_value=total_pages, value=1, key="field_page")
start = (page - 1) * page_size
end = start + page_size
st.dataframe(df.iloc[start:end] if not df.empty else df, use_container_width=True)

st.markdown("### Field Actions")
field_ids = [str(row["field_id"]) for row in filtered]
selected = st.selectbox("Select field", field_ids or ["none"])
current = next((row for row in fields if str(row["field_id"]) == selected), None)

if current:
    with st.form("edit_field"):
        if current["project_id"] is None:
            scope_index = 0
        elif current["project_id"] in project_ids:
            scope_index = project_ids.index(current["project_id"]) + 1
        else:
            scope_index = 0
        project_scope = st.selectbox(
            "Project Scope",
            ["global"] + project_ids,
            index=scope_index,
        )
        dataset = st.text_input("Dataset", value=current["dataset"])
        layer_options = ["bronze", "gold_fact", "gold_dim"]
        layer_index = layer_options.index(current["layer"]) if current["layer"] in layer_options else 0
        layer = st.selectbox("Layer", layer_options, index=layer_index)
        table_name = st.text_input("Table Name", value=current["table_name"])
        column_name = st.text_input("Column Name", value=current["column_name"])
        column_type = st.text_input("Column Type", value=current["column_type"])
        mode_options = ["ALIAS", "MATERIALIZED"]
        current_mode = (current["mode"] or "ALIAS").upper()
        mode_index = mode_options.index(current_mode) if current_mode in mode_options else 0
        mode = st.selectbox("Mode", mode_options, index=mode_index)
        expression_sql = st.text_area("Expression SQL", value=current.get("expression_sql") or "", height=80)
        enabled = st.checkbox("Enabled", value=current["enabled"])
        submitted = st.form_submit_button("Update Field")
        if submitted:
            project_id = None if project_scope == "global" else project_scope
            if not column_name or not IDENT_RE.match(column_name):
                st.error("Column name must be alphanumeric + underscore.")
            elif "." in table_name:
                parts = table_name.split(".", 1)
                if not IDENT_RE.match(parts[0]) or not IDENT_RE.match(parts[1]):
                    st.error("Table name parts must be alphanumeric + underscore.")
            elif not IDENT_RE.match(table_name):
                st.error("Table name must be alphanumeric + underscore.")
            else:
                rowcount = db.execute(
                    """
                    UPDATE metadata.field_registry
                    SET project_id = %s,
                        dataset = %s,
                        layer = %s,
                        table_name = %s,
                        column_name = %s,
                        column_type = %s,
                        expression_sql = %s,
                        mode = %s,
                        enabled = %s,
                        updated_at = now()
                    WHERE field_id = %s
                      AND updated_at = %s
                    """,
                    (
                        project_id,
                        dataset,
                        layer,
                        table_name,
                        column_name,
                        column_type,
                        expression_sql,
                        mode,
                        enabled,
                        current["field_id"],
                        current["updated_at"],
                    ),
                )
                if rowcount == 0:
                    st.error("Update conflict: field was modified by another user.")
                else:
                    ui.notify("Field updated.")
                    st.rerun()

    col1, col2, _ = st.columns(3)
    with col1:
        if st.button("Enable / Disable"):
            confirm = st.checkbox("Confirm toggle", key="confirm_field_toggle")
            if confirm:
                db.execute(
                    """
                    UPDATE metadata.field_registry
                    SET enabled = %s, updated_at = now()
                    WHERE field_id = %s
                      AND updated_at = %s
                    """,
                    (not current["enabled"], current["field_id"], current["updated_at"]),
                )
                ui.notify("Field status updated.")
                st.rerun()
    with col2:
        if st.button("Delete Field"):
            confirm = st.checkbox("Confirm delete", key="confirm_field_delete")
            if confirm:
                db.execute(
                    "DELETE FROM metadata.field_registry WHERE field_id = %s",
                    (current["field_id"],),
                )
                ui.notify("Field deleted.")
                st.rerun()

st.markdown("### Apply Schema Changes")
if st.button("Apply Schema Changes"):
    results = apply_schema(collect_results=True)
    ui.notify("Schema migration completed.")
    if results:
        st.dataframe(pd.DataFrame(results), use_container_width=True)
    else:
        st.info("No field registry entries to apply.")
