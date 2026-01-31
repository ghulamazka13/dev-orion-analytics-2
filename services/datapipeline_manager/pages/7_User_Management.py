import re

import pandas as pd
import streamlit as st

from datapipeline_manager import ui


ui.set_page_config("User Management")
ui.inject_css()
ui.require_auth()
ui.require_role("admin")
ui.sidebar()
ui.header("User Access", "Create and manage UI users with access levels")
ui.ensure_user_store()

st.markdown("### Current Users")
users = ui.list_users()
if users:
    df = pd.DataFrame(users)
    st.dataframe(df, use_container_width=True)
else:
    st.info("No users yet. Create the first user below.")

st.markdown("### Add User")
st.caption("Usernames: 3-32 chars, letters/numbers/._- only. Passwords: min 8 chars.")
with st.form("create_user"):
    username = st.text_input("Username")
    role = st.selectbox("Access level", options=list(ui.ROLE_OPTIONS), index=0)
    password = st.text_input("Password", type="password")
    confirm = st.text_input("Confirm password", type="password")
    enabled = st.checkbox("Enabled", value=True)
    submitted = st.form_submit_button("Create user")

    if submitted:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username or ""):
            st.error("Username format is invalid.")
        elif password != confirm:
            st.error("Passwords do not match.")
        elif len(password or "") < 8:
            st.error("Password must be at least 8 characters.")
        elif ui.get_user(username):
            st.error("Username already exists.")
        else:
            try:
                ui.create_user(username, password, role=role, enabled=enabled)
                ui.notify("User created.")
                st.rerun()
            except Exception as exc:
                st.error(f"Create failed: {exc}")

st.markdown("### Update User")
if not users:
    st.info("Create a user first to edit access levels.")
else:
    usernames = [user["username"] for user in users]
    selected = st.selectbox("Select user", options=usernames)
    current = next((user for user in users if user["username"] == selected), None)
    if current:
        current_user = st.session_state.get("username")
        admin_count = sum(
            1 for user in users if user["role"] == "admin" and user["enabled"]
        )
        with st.form("edit_user"):
            role_options = list(ui.ROLE_OPTIONS)
            role_index = role_options.index(current["role"]) if current["role"] in role_options else 0
            role = st.selectbox(
                "Access level",
                options=role_options,
                index=role_index,
            )
            enabled = st.checkbox("Enabled", value=current["enabled"])
            password = st.text_input("Reset password (optional)", type="password")
            confirm = st.text_input("Confirm new password", type="password")
            submitted = st.form_submit_button("Save changes")
            if submitted:
                if selected == current_user and not enabled:
                    st.error("You cannot disable your own account.")
                elif (
                    current["role"] == "admin"
                    and admin_count == 1
                    and (role != "admin" or not enabled)
                ):
                    st.error("At least one enabled admin is required.")
                elif password and password != confirm:
                    st.error("Passwords do not match.")
                elif password and len(password) < 8:
                    st.error("Password must be at least 8 characters.")
                else:
                    try:
                        ui.update_user(selected, role=role, enabled=enabled)
                        if password:
                            ui.reset_password(selected, password)
                        if selected == current_user:
                            st.session_state["role"] = role
                        ui.notify("User updated.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Update failed: {exc}")
