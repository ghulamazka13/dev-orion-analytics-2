import json
from typing import Optional

import pandas as pd
import psycopg2
import streamlit as st

from datapipeline_manager import db, opensearch, ui


ui.set_page_config("Sources")
ui.inject_css()
ui.require_auth()
ui.sidebar()
ui.header("OpenSearch Sources", "Onboard and manage data sources")


def _read_secret(secret_ref: Optional[str]) -> Optional[str]:
    if not secret_ref:
        return None
    try:
        with open(secret_ref, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return None


projects = db.fetch_all(
    "SELECT project_id FROM metadata.projects ORDER BY project_id"
)
project_ids = [row["project_id"] for row in projects]

sources = db.fetch_all(
    """
    SELECT source_id, project_id, name, base_url, auth_type, username, secret_ref, secret_enc,
           index_pattern, time_field, query_filter_json, enabled, created_at, updated_at
    FROM metadata.opensearch_sources
    ORDER BY source_id
    """
)

tabs = st.tabs(["Add / Edit", "Source List"])

with tabs[0]:
    st.markdown("### Source Wizard")
    source_ids = ["new"] + [str(row["source_id"]) for row in sources]
    selected_id = st.selectbox("Select source to edit", source_ids)
    current = next(
        (row for row in sources if str(row["source_id"]) == selected_id), None
    )

    with st.form("source_form"):
        project_id = st.selectbox(
            "Project",
            options=project_ids or ["no-projects"],
            index=project_ids.index(current["project_id"]) if current and current["project_id"] in project_ids else 0,
        )
        name = st.text_input("Source Name", value=current["name"] if current else "")

        auth_options = ["none", "basic", "api_key", "bearer"]
        current_auth = (current["auth_type"] if current and current["auth_type"] else "none")
        auth_index = auth_options.index(current_auth) if current_auth in auth_options else 0

        with st.expander("Step 1: Connection", expanded=True):
            base_url = st.text_input("Base URL", value=current["base_url"] if current else "")
            auth_type = st.selectbox(
                "Auth Type",
                options=auth_options,
                index=auth_index,
            )
            username = st.text_input("Username", value=current["username"] if current else "")
            secret_mode = "stored"
            if current and current.get("secret_ref"):
                secret_mode = "secret_ref"
            secret_mode = st.radio(
                "Credential Source",
                options=["stored", "secret_ref"],
                index=0 if secret_mode == "stored" else 1,
                horizontal=True,
                help="Store credentials in Postgres or reference a mounted secret file.",
            )
            secret_ref = None
            secret = ""
            if auth_type != "none":
                if secret_mode == "stored":
                    label = "Password" if auth_type == "basic" else "Secret"
                    secret = st.text_input(
                        label,
                        type="password",
                        placeholder="Leave blank to keep existing",
                    )
                    if current and current.get("secret_enc"):
                        st.caption("A secret is already stored. Leave blank to keep it.")
                else:
                    secret_ref = st.text_input(
                        "Secret Ref (file path)",
                        value=current["secret_ref"] if current else "/run/secrets/opensearch_key",
                    )
                    st.caption("Secret file must be mounted into /run/secrets.")
            else:
                st.caption("No secret needed for auth_type=none.")
            if auth_type != "none" and secret_mode == "stored":
                st.caption("The stored credential is also used for Test Connection.")

        with st.expander("Step 2: Indexing", expanded=True):
            index_pattern = st.text_input(
                "Index Pattern", value=current["index_pattern"] if current else ""
            )
            time_field = st.text_input(
                "Time Field", value=current["time_field"] if current else "@timestamp"
            )

        with st.expander("Step 3: Filters", expanded=False):
            query_filter_json = st.text_area(
                "Query Filter JSON",
                value=json.dumps(current["query_filter_json"] or {}, indent=2) if current else "{}",
                height=80,
            )

        enabled = st.checkbox("Enabled", value=current["enabled"] if current else True)
        col_a, col_b = st.columns(2)
        with col_a:
            submit = st.form_submit_button("Save Source")
        with col_b:
            test = st.form_submit_button("Test Connection")

    if test:
        query_filter = ui.parse_json(query_filter_json)
        if query_filter is None:
            st.error("Query filter JSON is invalid.")
        else:
            secret_value = None
            if auth_type != "none":
                if secret_mode == "stored":
                    secret_value = secret or (
                        ui.decrypt_secret(current.get("secret_enc")) if current else None
                    )
                else:
                    secret_value = _read_secret(secret_ref)
            if auth_type != "none" and not secret_value:
                label = "Password" if auth_type == "basic" else "Secret"
                st.error(f"{label} is required for the selected auth type.")
            ok, message, indices = opensearch.test_connection(
                base_url=base_url,
                index_pattern=index_pattern,
                auth_type=None if auth_type == "none" else auth_type,
                username=username,
                secret=secret_value,
            )
            if ok:
                ui.notify(message, "success")
                st.write(indices)
            else:
                st.error(message)

    if submit:
        query_filter = ui.parse_json(query_filter_json)
        if query_filter is None:
            st.error("Query filter JSON is invalid.")
        elif not name or not base_url or not index_pattern or not time_field:
            st.error("Name, base URL, index pattern, and time field are required.")
        elif auth_type != "none" and secret_mode == "secret_ref" and not secret_ref:
            st.error("Secret ref is required for the selected auth type.")
        elif auth_type != "none" and secret_mode == "stored" and not secret and not (current and current.get("secret_enc")):
            label = "Password" if auth_type == "basic" else "Secret"
            st.error(f"{label} is required for the selected auth type.")
        elif project_id == "no-projects":
            st.error("No enabled projects available.")
        else:
            secret_ref_value = None
            secret_enc_value = None
            if auth_type != "none":
                if secret_mode == "secret_ref":
                    secret_ref_value = secret_ref
                    secret_enc_value = None
                else:
                    if secret:
                        secret_enc_value = ui.encrypt_secret(secret)
                    elif current and current.get("secret_enc") is not None:
                        secret_enc_value = bytes(current["secret_enc"])
            secret_enc_param = (
                psycopg2.Binary(secret_enc_value) if secret_enc_value is not None else None
            )
            try:
                if current:
                    rowcount = db.execute(
                        """
                        UPDATE metadata.opensearch_sources
                        SET project_id = %s,
                            name = %s,
                            base_url = %s,
                            auth_type = %s,
                            username = %s,
                            secret_ref = %s,
                            secret_enc = %s,
                            index_pattern = %s,
                            time_field = %s,
                            query_filter_json = %s,
                            enabled = %s,
                            updated_at = now()
                        WHERE source_id = %s
                          AND updated_at = %s
                        """,
                        (
                            project_id,
                            name,
                            base_url,
                            None if auth_type == "none" else auth_type,
                            username,
                            secret_ref_value,
                            secret_enc_param,
                            index_pattern,
                            time_field,
                            json.dumps(query_filter),
                            enabled,
                            current["source_id"],
                            current["updated_at"],
                        ),
                    )
                    if rowcount == 0:
                        st.error("Update conflict: source was modified by another user.")
                    else:
                        ui.notify("Source updated.")
                        st.rerun()
                else:
                    db.execute(
                        """
                        INSERT INTO metadata.opensearch_sources (
                          project_id, name, base_url, auth_type, username, secret_ref,
                          secret_enc, index_pattern, time_field, query_filter_json, enabled, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                        """,
                        (
                            project_id,
                            name,
                            base_url,
                            None if auth_type == "none" else auth_type,
                            username,
                            secret_ref_value,
                            secret_enc_param,
                            index_pattern,
                            time_field,
                            json.dumps(query_filter),
                            enabled,
                        ),
                    )
                    ui.notify("Source created.")
                    st.rerun()
            except Exception as exc:
                st.error(f"Save failed: {exc}")

with tabs[1]:
    st.markdown("### Sources")
    search = st.text_input("Search by name or base URL", value="")
    project_filter = st.selectbox(
        "Filter by project", options=["all"] + project_ids, index=0
    )
    status_filter = st.selectbox("Filter by status", ["all", "enabled", "disabled"], index=0)

    filtered = []
    for row in sources:
        match = search.lower() in (row["name"] + " " + row["base_url"]).lower()
        project_ok = project_filter == "all" or row["project_id"] == project_filter
        status_ok = (
            status_filter == "all"
            or (status_filter == "enabled" and row["enabled"])
            or (status_filter == "disabled" and not row["enabled"])
        )
        if match and project_ok and status_ok:
            filtered.append(row)

    df = pd.DataFrame(filtered)
    page_size = st.selectbox("Rows per page", [10, 20, 50], index=1)
    total_pages = max(1, (len(df) + page_size - 1) // page_size)
    page = st.number_input("Page", min_value=1, max_value=total_pages, value=1, key="source_page")
    start = (page - 1) * page_size
    end = start + page_size
    st.dataframe(df.iloc[start:end] if not df.empty else df, use_container_width=True)

    st.markdown("### Actions")
    selected = st.selectbox(
        "Select source", options=[str(row["source_id"]) for row in filtered] or ["none"]
    )
    current = next((row for row in sources if str(row["source_id"]) == selected), None)
    if current:
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Enable / Disable"):
                confirm = st.checkbox("Confirm status change", key="confirm_toggle")
                if confirm:
                    new_status = not current["enabled"]
                    rowcount = db.execute(
                        """
                        UPDATE metadata.opensearch_sources
                        SET enabled = %s,
                            updated_at = now()
                        WHERE source_id = %s
                          AND updated_at = %s
                        """,
                        (new_status, current["source_id"], current["updated_at"]),
                    )
                    if rowcount == 0:
                        st.error("Update conflict: source was modified by another user.")
                    else:
                        ui.notify("Source status updated.")
                        st.rerun()
        with col2:
            if st.button("Test Connection"):
                secret_value = _read_secret(current.get("secret_ref"))
                if not secret_value:
                    secret_value = ui.decrypt_secret(current.get("secret_enc"))
                ok, message, indices = opensearch.test_connection(
                    base_url=current["base_url"],
                    index_pattern=current["index_pattern"],
                    auth_type=current.get("auth_type"),
                    username=current.get("username"),
                    secret=secret_value,
                )
                if ok:
                    ui.notify(message, "success")
                    st.write(indices)
                else:
                    st.error(message)
        with col3:
            if st.button("View Details"):
                st.json(current)
            else:
                st.write("Use the wizard above to edit details.")
