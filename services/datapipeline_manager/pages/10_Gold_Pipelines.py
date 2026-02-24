import json

import pandas as pd
import streamlit as st

from datapipeline_manager import db, ui


ui.set_page_config("Gold Pipelines")
ui.inject_css()
ui.require_auth()
ui.sidebar()
ui.header("Gold Pipelines", "Manage DAG metadata and SQL from Postgres")


def _has_sql_text_column() -> bool:
    try:
        row = db.fetch_one(
            """
            SELECT count(*) AS count
            FROM information_schema.columns
            WHERE table_schema = 'metadata'
              AND table_name = 'gold_pipelines'
              AND column_name = 'sql_text'
            """
        )
        return bool(row and int(row.get("count", 0)) > 0)
    except Exception:
        return False


def _parse_depends_on(raw: str) -> list[str]:
    items = [item.strip() for item in (raw or "").split(",")]
    return [item for item in items if item]


HAS_SQL_TEXT = _has_sql_text_column()

if HAS_SQL_TEXT:
    pipelines = db.fetch_all(
        """
        SELECT
          p.id,
          d.dag_name,
          p.pipeline_name,
          p.enabled,
          p.sql_path,
          p.sql_text,
          p.window_minutes,
          p.depends_on,
          p.target_table,
          p.params,
          p.pipeline_order,
          p.updated_at
        FROM metadata.gold_pipelines p
        JOIN metadata.gold_dags d
          ON d.id = p.dag_id
        ORDER BY d.dag_name, p.pipeline_order, p.pipeline_name
        """
    )
else:
    st.warning(
        "Kolom `metadata.gold_pipelines.sql_text` belum ada. "
        "Jalankan migrasi metadata dulu agar SQL bisa disimpan di Postgres."
    )
    pipelines = db.fetch_all(
        """
        SELECT
          p.id,
          d.dag_name,
          p.pipeline_name,
          p.enabled,
          p.sql_path,
          NULL::text AS sql_text,
          p.window_minutes,
          p.depends_on,
          p.target_table,
          p.params,
          p.pipeline_order,
          p.updated_at
        FROM metadata.gold_pipelines p
        JOIN metadata.gold_dags d
          ON d.id = p.dag_id
        ORDER BY d.dag_name, p.pipeline_order, p.pipeline_name
        """
    )

dags = db.fetch_all(
    """
    SELECT
      id,
      dag_name,
      schedule_cron,
      timezone,
      owner,
      tags,
      max_active_tasks,
      default_window_minutes,
      enabled,
      updated_at
    FROM metadata.gold_dags
    ORDER BY dag_name
    """
)

st.markdown("### DAG List")
st.dataframe(pd.DataFrame(dags), use_container_width=True)

st.markdown("### Gold Pipeline List")
search = st.text_input("Search by dag / pipeline / target", value="")
status_filter = st.selectbox("Filter by status", ["all", "enabled", "disabled"], index=0)

filtered = []
for row in pipelines:
    haystack = f"{row.get('dag_name', '')} {row.get('pipeline_name', '')} {row.get('target_table', '')}".lower()
    match = search.lower() in haystack
    status_ok = (
        status_filter == "all"
        or (status_filter == "enabled" and row.get("enabled"))
        or (status_filter == "disabled" and not row.get("enabled"))
    )
    if match and status_ok:
        item = dict(row)
        sql_text = str(item.get("sql_text") or "")
        item["sql_source"] = "sql_text" if sql_text.strip() else "sql_path"
        item["sql_preview"] = " ".join(sql_text.split())[:120]
        filtered.append(item)

display_columns = [
    "dag_name",
    "pipeline_name",
    "enabled",
    "pipeline_order",
    "target_table",
    "sql_source",
    "sql_path",
    "sql_preview",
    "updated_at",
]
st.dataframe(pd.DataFrame(filtered)[display_columns] if filtered else pd.DataFrame(columns=display_columns), use_container_width=True)

tabs = st.tabs(["Create Pipeline", "Edit Pipeline"])

dag_options = {row["dag_name"]: row["id"] for row in dags}

with tabs[0]:
    st.markdown("### Create Pipeline")
    with st.form("create_gold_pipeline"):
        dag_name = st.selectbox("DAG", options=list(dag_options.keys()) or ["no-dag"])
        pipeline_name = st.text_input("Pipeline Name")
        target_table = st.text_input("Target Table", placeholder="gold.fact_new_events")
        sql_path = st.text_input("SQL Path (optional)", placeholder="sql/fact_new_events.sql")
        sql_text = st.text_area(
            "SQL Text (optional)",
            value="",
            height=240,
            disabled=not HAS_SQL_TEXT,
            help="Isi SQL transform langsung di metadata Postgres.",
        )
        depends_on_text = st.text_input(
            "Depends On (comma-separated pipeline_name)",
            placeholder="dim_date,dim_time",
        )
        window_minutes = st.number_input("Window Minutes", min_value=1, value=10, step=1)
        pipeline_order = st.number_input("Pipeline Order", min_value=0, value=0, step=1)
        enabled = st.checkbox("Enabled", value=True)
        params_json = st.text_area("Params JSON", value="{}", height=120)
        submitted = st.form_submit_button("Create Pipeline")

    if submitted:
        if dag_name == "no-dag":
            st.error("Belum ada DAG metadata. Tambahkan row di metadata.gold_dags dulu.")
            st.stop()
        params_obj = ui.parse_json(params_json)
        if params_obj is None:
            st.error("Params JSON tidak valid.")
            st.stop()
        depends_on = _parse_depends_on(depends_on_text)
        sql_path_value = (sql_path or "").strip() or None
        sql_text_value = (sql_text or "").strip() or None
        if not sql_path_value and not sql_text_value:
            st.error("Isi minimal salah satu: SQL Path atau SQL Text.")
            st.stop()
        if not pipeline_name.strip():
            st.error("Pipeline name wajib diisi.")
            st.stop()
        if not target_table.strip():
            st.error("Target table wajib diisi.")
            st.stop()
        try:
            if HAS_SQL_TEXT:
                db.execute(
                    """
                    INSERT INTO metadata.gold_pipelines (
                      dag_id, pipeline_name, enabled, sql_path, sql_text, window_minutes,
                      depends_on, target_table, params, pipeline_order, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                    """,
                    (
                        dag_options[dag_name],
                        pipeline_name.strip(),
                        enabled,
                        sql_path_value,
                        sql_text_value,
                        int(window_minutes),
                        depends_on or None,
                        target_table.strip(),
                        json.dumps(params_obj),
                        int(pipeline_order),
                    ),
                )
            else:
                if not sql_path_value:
                    st.error("Schema lama butuh `sql_path` (kolom sql_text belum tersedia).")
                    st.stop()
                db.execute(
                    """
                    INSERT INTO metadata.gold_pipelines (
                      dag_id, pipeline_name, enabled, sql_path, window_minutes,
                      depends_on, target_table, params, pipeline_order, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                    """,
                    (
                        dag_options[dag_name],
                        pipeline_name.strip(),
                        enabled,
                        sql_path_value,
                        int(window_minutes),
                        depends_on or None,
                        target_table.strip(),
                        json.dumps(params_obj),
                        int(pipeline_order),
                    ),
                )
            ui.notify("Pipeline created.")
            st.rerun()
        except Exception as exc:
            st.error(f"Create failed: {exc}")

with tabs[1]:
    st.markdown("### Edit Pipeline")
    options = [
        (str(row["id"]), f"{row['dag_name']} / {row['pipeline_name']} (id={row['id']})")
        for row in pipelines
    ]
    selected_label = st.selectbox(
        "Select Pipeline",
        options=[label for _, label in options] or ["no-pipeline"],
    )
    selected_id = next((pid for pid, label in options if label == selected_label), None)
    current = next((row for row in pipelines if str(row["id"]) == str(selected_id)), None)

    if current:
        with st.form("edit_gold_pipeline"):
            enabled = st.checkbox("Enabled", value=bool(current.get("enabled")))
            target_table = st.text_input("Target Table", value=current.get("target_table") or "")
            sql_path = st.text_input("SQL Path", value=current.get("sql_path") or "")
            sql_text = st.text_area(
                "SQL Text",
                value=current.get("sql_text") or "",
                height=280,
                disabled=not HAS_SQL_TEXT,
            )
            depends_on_text = st.text_input(
                "Depends On (comma-separated)",
                value=",".join(current.get("depends_on") or []),
            )
            current_window = int(current["window_minutes"]) if current.get("window_minutes") else 10
            window_minutes = st.number_input(
                "Window Minutes",
                min_value=1,
                value=current_window,
                step=1,
            )
            pipeline_order = st.number_input(
                "Pipeline Order",
                min_value=0,
                value=int(current.get("pipeline_order") or 0),
                step=1,
            )
            params_json = st.text_area(
                "Params JSON",
                value=json.dumps(current.get("params") or {}, indent=2),
                height=140,
            )
            submitted = st.form_submit_button("Update Pipeline")

        if submitted:
            params_obj = ui.parse_json(params_json)
            if params_obj is None:
                st.error("Params JSON tidak valid.")
                st.stop()
            depends_on = _parse_depends_on(depends_on_text)
            sql_path_value = (sql_path or "").strip() or None
            sql_text_value = (sql_text or "").strip() or None
            if not sql_path_value and not sql_text_value:
                st.error("Isi minimal salah satu: SQL Path atau SQL Text.")
                st.stop()
            if not target_table.strip():
                st.error("Target table wajib diisi.")
                st.stop()
            try:
                if HAS_SQL_TEXT:
                    rowcount = db.execute(
                        """
                        UPDATE metadata.gold_pipelines
                        SET enabled = %s,
                            sql_path = %s,
                            sql_text = %s,
                            window_minutes = %s,
                            depends_on = %s,
                            target_table = %s,
                            params = %s,
                            pipeline_order = %s,
                            updated_at = now()
                        WHERE id = %s
                          AND updated_at = %s
                        """,
                        (
                            enabled,
                            sql_path_value,
                            sql_text_value,
                            int(window_minutes),
                            depends_on or None,
                            target_table.strip(),
                            json.dumps(params_obj),
                            int(pipeline_order),
                            int(current["id"]),
                            current["updated_at"],
                        ),
                    )
                else:
                    if not sql_path_value:
                        st.error("Schema lama butuh `sql_path` (kolom sql_text belum tersedia).")
                        st.stop()
                    rowcount = db.execute(
                        """
                        UPDATE metadata.gold_pipelines
                        SET enabled = %s,
                            sql_path = %s,
                            window_minutes = %s,
                            depends_on = %s,
                            target_table = %s,
                            params = %s,
                            pipeline_order = %s,
                            updated_at = now()
                        WHERE id = %s
                          AND updated_at = %s
                        """,
                        (
                            enabled,
                            sql_path_value,
                            int(window_minutes),
                            depends_on or None,
                            target_table.strip(),
                            json.dumps(params_obj),
                            int(pipeline_order),
                            int(current["id"]),
                            current["updated_at"],
                        ),
                    )
                if rowcount == 0:
                    st.error("Update conflict: row sudah diubah user lain.")
                else:
                    ui.notify("Pipeline updated.")
                    st.rerun()
            except Exception as exc:
                st.error(f"Update failed: {exc}")
