import re
import pandas as pd
import streamlit as st

from datapipeline_manager import db, ui
from schema_migrator.migrator import apply_schema


ui.set_page_config("Bronze Parsing")
ui.inject_css()
ui.require_auth()
ui.sidebar()
ui.header("Bronze Parsing", "Map OpenSearch raw events into per-project bronze tables")

IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")

DEFAULT_DATASETS = {
    "suricata": {
        "table_name": "suricata_events_raw",
        "columns": [
            ("event_id", "String", "__event_id"),
            ("event_ts", "DateTime64(3, 'Asia/Jakarta')", "__event_ts"),
            ("sensor_type", "Nullable(String)", "$.event.provider\n$.event.module"),
            ("sensor_name", "Nullable(String)", "$.agent.name\n$.host.name\n$.node"),
            ("event_type", "Nullable(String)", "$.event.dataset\n$.event.kind"),
            ("severity", "Nullable(String)", "$.suricata.alert.severity\n$.event.severity"),
            ("src_ip", "Nullable(IPv6)", "$.source.ip"),
            ("dest_ip", "Nullable(IPv6)", "$.destination.ip"),
            ("src_port", "Nullable(Int32)", "$.source.port"),
            ("dest_port", "Nullable(Int32)", "$.destination.port"),
            ("community_id", "Nullable(String)", "$.network.community_id"),
            ("duration", "Nullable(Float64)", "$.event.duration"),
            ("dest_mac", "Nullable(String)", "$.suricata.ether.dest_mac"),
            ("src_mac", "Nullable(String)", "$.suricata.ether.src_mac"),
            ("mac", "Nullable(String)", "$.related.mac[0]"),
            ("latitude", "Nullable(Float64)", "$.source.geo.location.lat"),
            ("longitude", "Nullable(Float64)", "$.source.geo.location.lon"),
            ("country_name", "Nullable(String)", "$.source.geo.country_name"),
            (
                "protocol",
                "Nullable(String)",
                "$.network.application\n$.network.transport[0]\n$.network.protocol[0]\n$.protocol[0]",
            ),
            (
                "bytes",
                "Nullable(Int64)",
                "$.totDataBytes\n$.network.bytes\n$.client.bytes\n$.server.bytes",
            ),
            (
                "packets",
                "Nullable(Int64)",
                "$.network.packets\n$.client.packets\n$.server.packets",
            ),
            ("flow_id", "Nullable(String)", "$.suricata.flow_id"),
            ("signature", "Nullable(String)", "$.rule.name\n$.suricata.alert.signature"),
            ("signature_id", "Nullable(Int32)", "$.rule.id"),
            ("category", "Nullable(String)", "$.rule.category[0]"),
            ("alert_action", "Nullable(String)", "$.suricata.alert.action"),
            ("http_url", "Nullable(String)", "$.suricata.http.url"),
            ("tags", "Array(String)", "tags\nevent.severity_tags"),
            ("message", "Nullable(String)", "message\n$.event.original\n$.rule.name"),
            ("raw_data", "String", "__raw"),
        ],
    },
    "wazuh": {
        "table_name": "wazuh_events_raw",
        "columns": [
            ("event_id", "String", "__event_id"),
            ("event_ts", "DateTime64(3, 'Asia/Jakarta')", "__event_ts"),
            (
                "event_ingested_ts",
                "Nullable(DateTime64(3, 'Asia/Jakarta'))",
                "$.event.ingested\n__ingested_at",
            ),
            (
                "event_start_ts",
                "Nullable(DateTime64(3, 'Asia/Jakarta'))",
                "epoch_ms:$.event.start",
            ),
            (
                "event_end_ts",
                "Nullable(DateTime64(3, 'Asia/Jakarta'))",
                "epoch_ms:$.event.end",
            ),
            ("event_dataset", "Nullable(String)", "$.event.dataset"),
            ("event_kind", "Nullable(String)", "$.event.kind"),
            ("event_module", "Nullable(String)", "$.event.module"),
            ("event_provider", "Nullable(String)", "$.event.provider"),
            ("agent_name", "Nullable(String)", "$.agent.name"),
            ("agent_ip", "Nullable(IPv6)", "$.agent.ip"),
            ("host_name", "Nullable(String)", "$.host.name"),
            ("host_ip", "Nullable(IPv6)", "$.host.ip"),
            ("rule_id", "Nullable(String)", "$.rule.id"),
            ("rule_level", "Nullable(Int32)", "$.rule.level"),
            ("rule_name", "Nullable(String)", "$.rule.name"),
            ("rule_ruleset", "Nullable(String)", "$.rule.ruleset"),
            ("tags", "Array(String)", "tags"),
            ("message", "Nullable(String)", "message\n$.rule.name"),
            ("raw_data", "String", "__raw"),
        ],
    },
    "zeek": {
        "table_name": "zeek_events_raw",
        "columns": [
            ("event_id", "String", "__event_id"),
            ("event_ts", "DateTime64(3, 'Asia/Jakarta')", "__event_ts"),
            (
                "event_ingested_ts",
                "Nullable(DateTime64(3, 'Asia/Jakarta'))",
                "$.event.ingested\n__ingested_at",
            ),
            (
                "event_start_ts",
                "Nullable(DateTime64(3, 'Asia/Jakarta'))",
                "epoch_ms:$.event.start",
            ),
            (
                "event_end_ts",
                "Nullable(DateTime64(3, 'Asia/Jakarta'))",
                "epoch_ms:$.event.end",
            ),
            ("event_dataset", "Nullable(String)", "$.event.dataset"),
            ("event_kind", "Nullable(String)", "$.event.kind"),
            ("event_module", "Nullable(String)", "$.event.module"),
            ("event_provider", "Nullable(String)", "$.event.provider"),
            ("zeek_uid", "Nullable(String)", "$.zeek.uid\n$.event.id[0]"),
            ("sensor_name", "Nullable(String)", "$.agent.name\n$.host.name\n$.node"),
            ("src_ip", "Nullable(IPv6)", "$.source.ip"),
            ("dest_ip", "Nullable(IPv6)", "$.destination.ip"),
            ("src_port", "Nullable(Int32)", "$.source.port"),
            ("dest_port", "Nullable(Int32)", "$.destination.port"),
            (
                "geo_latitude",
                "Nullable(Float64)",
                "$.source.geo.location.lat\n$.source.geo.latitude\n$.destination.geo.location.lat\n$.destination.geo.latitude",
            ),
            (
                "geo_longitude",
                "Nullable(Float64)",
                "$.source.geo.location.lon\n$.source.geo.longitude\n$.destination.geo.location.lon\n$.destination.geo.longitude",
            ),
            (
                "geo_country",
                "Nullable(String)",
                "$.source.geo.country_name\n$.source.geo.country_iso_code\n$.source.geo.country_code2\n$.source.geo.country_code3\n$.destination.geo.country_name\n$.destination.geo.country_iso_code\n$.destination.geo.country_code2\n$.destination.geo.country_code3",
            ),
            (
                "geo_city_name",
                "Nullable(String)",
                "$.source.geo.city_name\n$.destination.geo.city_name",
            ),
            ("mac_address", "Nullable(String)", "$.source.mac[0]\n$.destination.mac[0]"),
            (
                "protocol",
                "Nullable(String)",
                "$.network.application\n$.network.transport[0]\n$.network.protocol[0]\n$.protocol[0]",
            ),
            ("application", "Nullable(String)", "$.network.application"),
            ("network_type", "Nullable(String)", "$.network.type"),
            ("direction", "Nullable(String)", "$.network.direction"),
            ("community_id", "Nullable(String)", "$.network.community_id"),
            (
                "bytes",
                "Nullable(Int64)",
                "$.totDataBytes\n$.network.bytes\n$.source.bytes\n$.destination.bytes",
            ),
            (
                "packets",
                "Nullable(Int64)",
                "$.network.packets\n$.source.packets\n$.destination.packets",
            ),
            ("orig_bytes", "Nullable(Int64)", "$.zeek.conn.orig_bytes\n$.zeek.conn.orig_ip_bytes"),
            ("resp_bytes", "Nullable(Int64)", "$.zeek.conn.resp_bytes\n$.zeek.conn.resp_ip_bytes"),
            ("orig_pkts", "Nullable(Int64)", "$.zeek.conn.orig_pkts"),
            ("resp_pkts", "Nullable(Int64)", "$.zeek.conn.resp_pkts"),
            ("conn_state", "Nullable(String)", "$.zeek.conn.conn_state"),
            (
                "conn_state_description",
                "Nullable(String)",
                "$.zeek.conn.conn_state_description",
            ),
            ("duration", "Nullable(Float64)", "$.zeek.conn.duration"),
            ("history", "Nullable(String)", "$.zeek.conn.history"),
            ("vlan_id", "Nullable(String)", "$.zeek.conn.vlan\n$.network.vlan.id[0]"),
            ("tags", "Array(String)", "tags\nevent.category\nevent.severity_tags"),
            ("domain", "Nullable(String)", "$.zeek.http.host\n$.zeek.dns.query\n$.zeek.ssl.server_name"),
            (
                "message",
                "Nullable(String)",
                "message\n$.event.original\n$.zeek.conn.conn_state_description",
            ),
            ("raw_data", "String", "__raw"),
        ],
    },
}


projects = db.fetch_all("SELECT project_id FROM metadata.projects ORDER BY project_id")
project_ids = [row["project_id"] for row in projects]

st.markdown("### Create Schema")
if not project_ids:
    st.info("Create a project first to define bronze schemas.")
else:
    with st.form("create_bronze_schema"):
        project_id = st.selectbox("Project", project_ids, key="bronze_schema_project")
        dataset = st.text_input("Dataset Name", value="custom")
        table_name = st.text_input("Table Name", value="")
        enabled = st.checkbox("Enabled", value=True)
        submitted = st.form_submit_button("Create Schema")
        if submitted:
            if not dataset or not IDENT_RE.match(dataset):
                st.error("Dataset must be alphanumeric + underscore.")
            elif not table_name or not IDENT_RE.match(table_name):
                st.error("Table name must be alphanumeric + underscore.")
            else:
                existing = db.fetch_one(
                    """
                    SELECT table_id
                    FROM metadata.bronze_event_tables
                    WHERE project_id = %s AND table_name = %s
                    """,
                    (project_id, table_name),
                )
                if existing:
                    st.warning("Schema already exists for this table.")
                else:
                    db.execute(
                        """
                        INSERT INTO metadata.bronze_event_tables (
                          project_id, dataset, table_name, enabled, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, now(), now())
                        """,
                        (project_id, dataset.lower(), table_name, enabled),
                    )
                    ui.notify("Schema created. Add fields below.")
                    st.rerun()

st.markdown("### Initialize Default Bronze Tables")
if not project_ids:
    st.info("Create a project first to initialize bronze tables.")
else:
    with st.form("init_bronze_defaults"):
        project_id = st.selectbox("Project", project_ids)
        dataset = st.selectbox("Dataset", ["suricata", "wazuh", "zeek"])
        default_table_name = DEFAULT_DATASETS[dataset]["table_name"]
        table_name = st.text_input("Table Name", value=default_table_name)
        submitted = st.form_submit_button("Create / Add Defaults")
        if submitted:
            if not table_name or not IDENT_RE.match(table_name):
                st.error("Table name must be alphanumeric + underscore.")
            else:
                existing = db.fetch_one(
                    """
                    SELECT table_id
                    FROM metadata.bronze_event_tables
                    WHERE project_id = %s AND table_name = %s
                    """,
                    (project_id, table_name),
                )
                if existing:
                    table_id = existing["table_id"]
                else:
                    db.execute(
                        """
                        INSERT INTO metadata.bronze_event_tables (
                          project_id, dataset, table_name, enabled, created_at, updated_at
                        ) VALUES (%s, %s, %s, TRUE, now(), now())
                        """,
                        (project_id, dataset, table_name),
                    )
                    created = db.fetch_one(
                        """
                        SELECT table_id
                        FROM metadata.bronze_event_tables
                        WHERE project_id = %s AND table_name = %s
                        """,
                        (project_id, table_name),
                    )
                    table_id = created["table_id"] if created else None

                if table_id is None:
                    st.error("Unable to create bronze table entry.")
                else:
                    columns = DEFAULT_DATASETS[dataset]["columns"]
                    for ordinal, (col_name, col_type, json_path) in enumerate(columns, start=1):
                        db.execute(
                            """
                            INSERT INTO metadata.bronze_event_fields (
                              table_id, column_name, column_type, json_path, enabled, ordinal, created_at, updated_at
                            ) VALUES (%s, %s, %s, %s, TRUE, %s, now(), now())
                            ON CONFLICT (table_id, column_name) DO NOTHING
                            """,
                            (table_id, col_name, col_type, json_path, ordinal),
                        )
                    ui.notify("Default mappings saved.")
                    st.rerun()

st.markdown("### Bronze Tables")
try:
    table_rows = db.fetch_all(
        """
        SELECT table_id, project_id, dataset, table_name, enabled, created_at, updated_at
        FROM metadata.bronze_event_tables
        ORDER BY project_id, table_name
        """
    )
except Exception as exc:
    st.error(f"Bronze parsing tables are not available: {exc}")
    st.info("Run postgres/init/11_control_plane.sql to create metadata tables.")
    st.stop()

table_df = pd.DataFrame(table_rows)
st.dataframe(table_df if not table_df.empty else table_df, use_container_width=True)

project_filter = st.selectbox("Filter by project", ["all"] + project_ids, index=0)
filtered_tables = [
    row for row in table_rows if project_filter == "all" or row["project_id"] == project_filter
]
table_ids = [str(row["table_id"]) for row in filtered_tables]
selected_table_id = st.selectbox("Select schema", table_ids or ["none"])
current_table = next(
    (row for row in filtered_tables if str(row["table_id"]) == selected_table_id),
    None,
)

if current_table:
    st.markdown("### Schema Settings")
    with st.form("edit_bronze_schema"):
        dataset = st.text_input("Dataset", value=current_table["dataset"] or "")
        enabled = st.checkbox("Enabled", value=current_table["enabled"])
        submitted = st.form_submit_button("Update Schema")
        if submitted:
            if not dataset or not IDENT_RE.match(dataset):
                st.error("Dataset must be alphanumeric + underscore.")
            else:
                rowcount = db.execute(
                    """
                    UPDATE metadata.bronze_event_tables
                    SET dataset = %s,
                        enabled = %s,
                        updated_at = now()
                    WHERE table_id = %s
                      AND updated_at = %s
                    """,
                    (
                        dataset.lower(),
                        enabled,
                        current_table["table_id"],
                        current_table["updated_at"],
                    ),
                )
                if rowcount == 0:
                    st.error("Update conflict: schema was modified by another user.")
                else:
                    ui.notify("Schema updated.")
                    st.rerun()

    col1, col2, _ = st.columns(3)
    with col1:
        if st.button("Set Active (disable others in project)"):
            db.execute(
                """
                UPDATE metadata.bronze_event_tables
                SET enabled = CASE WHEN table_id = %s THEN TRUE ELSE FALSE END,
                    updated_at = now()
                WHERE project_id = %s
                """,
                (current_table["table_id"], current_table["project_id"]),
            )
            ui.notify("Schema set active for project.")
            st.rerun()
    with col2:
        if st.button("Delete Schema"):
            confirm = st.checkbox("Confirm delete", key="confirm_bronze_schema_delete")
            if confirm:
                db.execute(
                    "DELETE FROM metadata.bronze_event_tables WHERE table_id = %s",
                    (current_table["table_id"],),
                )
                ui.notify("Schema deleted (metadata only).")
                st.rerun()

    st.markdown("### Table Fields")
    field_rows = db.fetch_all(
        """
        SELECT field_id, column_name, column_type, json_path, enabled, ordinal, created_at, updated_at
        FROM metadata.bronze_event_fields
        WHERE table_id = %s
        ORDER BY ordinal, column_name
        """,
        (current_table["table_id"],),
    )
    st.dataframe(pd.DataFrame(field_rows) if field_rows else pd.DataFrame(), use_container_width=True)

    st.markdown("### Add Field")
    st.caption(
        "Hints: use JSONPath (e.g. $.event.provider). One path per line for fallback. "
        "Prefix with epoch_ms: for millisecond timestamps. "
        "Use __event_id, __event_ts, __raw, __ingested_at to read from os_events_raw."
    )
    with st.form("add_bronze_field"):
        column_name = st.text_input("Column Name")
        column_type = st.text_input("Column Type", value="Nullable(String)")
        json_path = st.text_area(
            "JSON Path(s)",
            value="$.event.provider",
            help=(
                "One path per line. Use JSONPath (e.g. $.event.provider). "
                "Use __event_id, __event_ts, __raw, __ingested_at to read from os_events_raw."
            ),
            height=100,
        )
        ordinal = st.number_input("Order", min_value=0, value=0)
        enabled = st.checkbox("Enabled", value=True)
        submitted = st.form_submit_button("Add Field")
        if submitted:
            if not column_name or not IDENT_RE.match(column_name):
                st.error("Column name must be alphanumeric + underscore.")
            else:
                db.execute(
                    """
                    INSERT INTO metadata.bronze_event_fields (
                      table_id, column_name, column_type, json_path, enabled, ordinal, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, now(), now())
                    """,
                    (
                        current_table["table_id"],
                        column_name,
                        column_type,
                        json_path,
                        enabled,
                        ordinal,
                    ),
                )
                ui.notify("Field added.")
                st.rerun()

    st.markdown("### Edit Field")
    field_ids = [str(row["field_id"]) for row in field_rows]
    selected_field_id = st.selectbox("Select field", field_ids or ["none"])
    current_field = next((row for row in field_rows if str(row["field_id"]) == selected_field_id), None)
    if current_field:
        with st.form("edit_bronze_field"):
            column_name = st.text_input("Column Name", value=current_field["column_name"])
            column_type = st.text_input("Column Type", value=current_field["column_type"])
            json_path = st.text_area("JSON Path(s)", value=current_field["json_path"], height=100)
            ordinal = st.number_input("Order", min_value=0, value=current_field["ordinal"])
            enabled = st.checkbox("Enabled", value=current_field["enabled"])
            submitted = st.form_submit_button("Update Field")
            if submitted:
                if not column_name or not IDENT_RE.match(column_name):
                    st.error("Column name must be alphanumeric + underscore.")
                else:
                    rowcount = db.execute(
                        """
                        UPDATE metadata.bronze_event_fields
                        SET column_name = %s,
                            column_type = %s,
                            json_path = %s,
                            enabled = %s,
                            ordinal = %s,
                            updated_at = now()
                        WHERE field_id = %s
                          AND updated_at = %s
                        """,
                        (
                            column_name,
                            column_type,
                            json_path,
                            enabled,
                            ordinal,
                            current_field["field_id"],
                            current_field["updated_at"],
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
                confirm = st.checkbox("Confirm toggle", key="confirm_bronze_toggle")
                if confirm:
                    db.execute(
                        """
                        UPDATE metadata.bronze_event_fields
                        SET enabled = %s, updated_at = now()
                        WHERE field_id = %s
                          AND updated_at = %s
                        """,
                        (not current_field["enabled"], current_field["field_id"], current_field["updated_at"]),
                    )
                    ui.notify("Field status updated.")
                    st.rerun()
        with col2:
            if st.button("Delete Field"):
                confirm = st.checkbox("Confirm delete", key="confirm_bronze_delete")
                if confirm:
                    db.execute(
                        "DELETE FROM metadata.bronze_event_fields WHERE field_id = %s",
                        (current_field["field_id"],),
                    )
                    ui.notify("Field deleted.")
                    st.rerun()

st.markdown("### Apply Schema Changes")
st.info("Materialized views only process new rows. Re-run a backfill job to populate historical data.")
if st.button("Apply Schema Changes"):
    results = apply_schema(collect_results=True)
    ui.notify("Schema migration completed.")
    if results:
        st.dataframe(pd.DataFrame(results), use_container_width=True)
    else:
        st.info("No changes to apply.")
