import html
import json
import os
import re
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from schema_migrator.migrator import apply_schema


POSTGRES_DSN = os.getenv(
    "POSTGRES_DSN",
    "postgresql://airflow:airflow@postgres:5432/airflow",
)

IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")

app = FastAPI()


def _connect():
    conn = psycopg2.connect(POSTGRES_DSN)
    conn.autocommit = True
    return conn


def _fetch_all(query: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
    with _connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params or ())
            return list(cur.fetchall())


def _execute(query: str, params: Optional[tuple] = None) -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params or ())


def _render_table(rows: List[Dict[str, Any]], columns: List[str]) -> str:
    header = "".join(f"<th>{html.escape(col)}</th>" for col in columns)
    body_rows = []
    for row in rows:
        cells = []
        for col in columns:
            value = row.get(col, "")
            cells.append(f"<td>{html.escape(str(value))}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    body = "".join(body_rows) if body_rows else "<tr><td colspan='10'>No data</td></tr>"
    return f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"


def _page(content: str) -> HTMLResponse:
    return HTMLResponse(
        f"""
        <html>
          <head>
            <title>Source Manager</title>
            <style>
              body {{ font-family: Arial, sans-serif; margin: 24px; }}
              h2 {{ margin-top: 32px; }}
              table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
              th, td {{ border: 1px solid #ddd; padding: 8px; font-size: 12px; }}
              th {{ background: #f3f3f3; text-align: left; }}
              form {{ margin-bottom: 16px; padding: 12px; border: 1px solid #ddd; }}
              label {{ display: inline-block; width: 160px; font-weight: bold; }}
              input[type='text'], textarea {{ width: 420px; }}
              .note {{ font-size: 12px; color: #555; }}
              .btn {{ padding: 6px 12px; }}
            </style>
          </head>
          <body>
            <h1>OpenSearch Source Manager</h1>
            {content}
          </body>
        </html>
        """
    )


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    projects = _fetch_all(
        """
        SELECT project_id, name, timezone, retention_days, enabled, created_at, updated_at
        FROM metadata.projects
        ORDER BY project_id
        """
    )
    sources = _fetch_all(
        """
        SELECT source_id, project_id, name, base_url, auth_type, username, secret_ref,
               index_pattern, time_field, enabled, created_at, updated_at
        FROM metadata.opensearch_sources
        ORDER BY source_id
        """
    )
    fields = _fetch_all(
        """
        SELECT field_id, project_id, dataset, layer, table_name, column_name, column_type,
               mode, enabled, created_at, updated_at
        FROM metadata.field_registry
        ORDER BY field_id
        """
    )
    backfills = _fetch_all(
        """
        SELECT job_id, source_id, start_ts, end_ts, status, last_error, updated_at
        FROM metadata.backfill_jobs
        ORDER BY created_at DESC
        """
    )

    content = """
    <h2>Projects</h2>
    <p class="note">project_id must be alphanumeric + underscore (used for ClickHouse database names).</p>
    <form method="post" action="/projects">
      <label>project_id</label><input type="text" name="project_id" required />
      <label>name</label><input type="text" name="name" required /><br/><br/>
      <label>timezone</label><input type="text" name="timezone" value="UTC" />
      <label>retention_days</label><input type="text" name="retention_days" /><br/><br/>
      <label>enabled</label><input type="checkbox" name="enabled" checked />
      <button class="btn" type="submit">Upsert Project</button>
    </form>
    """
    content += _render_table(projects, ["project_id", "name", "timezone", "retention_days", "enabled", "updated_at"])

    content += """
    <h2>OpenSearch Sources</h2>
    <form method="post" action="/sources">
      <label>source_id (optional)</label><input type="text" name="source_id" />
      <label>project_id</label><input type="text" name="project_id" required /><br/><br/>
      <label>name</label><input type="text" name="name" required />
      <label>base_url</label><input type="text" name="base_url" required /><br/><br/>
      <label>auth_type</label><input type="text" name="auth_type" placeholder="basic/api_key/bearer" />
      <label>username</label><input type="text" name="username" /><br/><br/>
      <label>secret_ref</label><input type="text" name="secret_ref" placeholder="/run/secrets/os_api_key" /><br/><br/>
      <label>index_pattern</label><input type="text" name="index_pattern" required />
      <label>time_field</label><input type="text" name="time_field" required /><br/><br/>
      <label>query_filter_json</label><textarea name="query_filter_json" rows="2"></textarea><br/><br/>
      <label>enabled</label><input type="checkbox" name="enabled" checked />
      <button class="btn" type="submit">Upsert Source</button>
    </form>
    """
    content += _render_table(
        sources,
        ["source_id", "project_id", "name", "base_url", "auth_type", "index_pattern", "time_field", "enabled", "updated_at"],
    )

    content += """
    <h2>Backfill Jobs</h2>
    <form method="post" action="/backfills">
      <label>source_id</label><input type="text" name="source_id" required />
      <label>requested_by</label><input type="text" name="requested_by" /><br/><br/>
      <label>start_ts (ISO)</label><input type="text" name="start_ts" placeholder="2026-01-01T00:00:00Z" required />
      <label>end_ts (ISO)</label><input type="text" name="end_ts" placeholder="2026-01-02T00:00:00Z" required /><br/><br/>
      <button class="btn" type="submit">Create Backfill Job</button>
    </form>
    """
    content += _render_table(backfills, ["job_id", "source_id", "start_ts", "end_ts", "status", "last_error", "updated_at"])

    content += """
    <h2>Field Registry</h2>
    <form method="post" action="/fields">
      <label>field_id (optional)</label><input type="text" name="field_id" />
      <label>project_id (optional)</label><input type="text" name="project_id" /><br/><br/>
      <label>dataset</label><input type="text" name="dataset" required />
      <label>layer</label><input type="text" name="layer" placeholder="bronze/gold_fact/gold_dim" required /><br/><br/>
      <label>table_name</label><input type="text" name="table_name" required />
      <label>column_name</label><input type="text" name="column_name" required /><br/><br/>
      <label>column_type</label><input type="text" name="column_type" required />
      <label>mode</label><input type="text" name="mode" value="ALIAS" /><br/><br/>
      <label>expression_sql</label><textarea name="expression_sql" rows="2"></textarea><br/><br/>
      <label>enabled</label><input type="checkbox" name="enabled" checked />
      <button class="btn" type="submit">Upsert Field</button>
    </form>
    """
    content += _render_table(
        fields,
        ["field_id", "project_id", "dataset", "layer", "table_name", "column_name", "column_type", "mode", "enabled"],
    )

    content += """
    <h2>Schema Migrator</h2>
    <form method="post" action="/schema/apply">
      <button class="btn" type="submit">Apply Schema</button>
    </form>
    """
    return _page(content)


@app.post("/projects")
def upsert_project(
    project_id: str = Form(...),
    name: str = Form(...),
    timezone: str = Form("UTC"),
    retention_days: Optional[str] = Form(None),
    enabled: Optional[str] = Form(None),
) -> RedirectResponse:
    if not IDENT_RE.match(project_id):
        return RedirectResponse("/?error=invalid_project_id", status_code=303)

    retention_value = int(retention_days) if retention_days else None
    is_enabled = enabled is not None

    _execute(
        """
        INSERT INTO metadata.projects (
          project_id, name, timezone, retention_days, enabled, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, now(), now())
        ON CONFLICT (project_id) DO UPDATE SET
          name = EXCLUDED.name,
          timezone = EXCLUDED.timezone,
          retention_days = EXCLUDED.retention_days,
          enabled = EXCLUDED.enabled,
          updated_at = now()
        """,
        (project_id, name, timezone, retention_value, is_enabled),
    )
    return RedirectResponse("/", status_code=303)


@app.post("/sources")
def upsert_source(
    project_id: str = Form(...),
    name: str = Form(...),
    base_url: str = Form(...),
    auth_type: Optional[str] = Form(None),
    username: Optional[str] = Form(None),
    secret_ref: Optional[str] = Form(None),
    index_pattern: str = Form(...),
    time_field: str = Form(...),
    query_filter_json: Optional[str] = Form(None),
    enabled: Optional[str] = Form(None),
    source_id: Optional[str] = Form(None),
) -> RedirectResponse:
    query_filter = {}
    if query_filter_json:
        try:
            query_filter = json.loads(query_filter_json)
        except json.JSONDecodeError:
            return RedirectResponse("/?error=invalid_query_filter", status_code=303)

    is_enabled = enabled is not None

    if source_id:
        _execute(
            """
            UPDATE metadata.opensearch_sources
            SET project_id = %s,
                name = %s,
                base_url = %s,
                auth_type = %s,
                username = %s,
                secret_ref = %s,
                index_pattern = %s,
                time_field = %s,
                query_filter_json = %s,
                enabled = %s,
                updated_at = now()
            WHERE source_id = %s
            """,
            (
                project_id,
                name,
                base_url,
                auth_type,
                username,
                secret_ref,
                index_pattern,
                time_field,
                psycopg2.extras.Json(query_filter),
                is_enabled,
                int(source_id),
            ),
        )
    else:
        _execute(
            """
            INSERT INTO metadata.opensearch_sources (
              project_id, name, base_url, auth_type, username, secret_ref,
              index_pattern, time_field, query_filter_json, enabled, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
            ON CONFLICT (project_id, name) DO UPDATE SET
              base_url = EXCLUDED.base_url,
              auth_type = EXCLUDED.auth_type,
              username = EXCLUDED.username,
              secret_ref = EXCLUDED.secret_ref,
              index_pattern = EXCLUDED.index_pattern,
              time_field = EXCLUDED.time_field,
              query_filter_json = EXCLUDED.query_filter_json,
              enabled = EXCLUDED.enabled,
              updated_at = now()
            """,
            (
                project_id,
                name,
                base_url,
                auth_type,
                username,
                secret_ref,
                index_pattern,
                time_field,
                psycopg2.extras.Json(query_filter),
                is_enabled,
            ),
        )
    return RedirectResponse("/", status_code=303)


@app.post("/backfills")
def create_backfill(
    source_id: str = Form(...),
    start_ts: str = Form(...),
    end_ts: str = Form(...),
    requested_by: Optional[str] = Form(None),
) -> RedirectResponse:
    _execute(
        """
        INSERT INTO metadata.backfill_jobs (
          source_id, start_ts, end_ts, status, requested_by, created_at, updated_at
        ) VALUES (%s, %s, %s, 'pending', %s, now(), now())
        """,
        (int(source_id), start_ts, end_ts, requested_by),
    )
    return RedirectResponse("/", status_code=303)


@app.post("/fields")
def upsert_field(
    dataset: str = Form(...),
    layer: str = Form(...),
    table_name: str = Form(...),
    column_name: str = Form(...),
    column_type: str = Form(...),
    mode: str = Form("ALIAS"),
    expression_sql: Optional[str] = Form(None),
    project_id: Optional[str] = Form(None),
    enabled: Optional[str] = Form(None),
    field_id: Optional[str] = Form(None),
) -> RedirectResponse:
    is_enabled = enabled is not None

    if field_id:
        _execute(
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
                is_enabled,
                int(field_id),
            ),
        )
    else:
        _execute(
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
                is_enabled,
            ),
        )
    return RedirectResponse("/", status_code=303)


@app.post("/schema/apply")
def apply_schema_action() -> RedirectResponse:
    apply_schema()
    return RedirectResponse("/", status_code=303)


@app.get("/api/projects")
def list_projects() -> List[Dict[str, Any]]:
    return _fetch_all(
        "SELECT project_id, name, timezone, retention_days, enabled FROM metadata.projects ORDER BY project_id"
    )


@app.get("/api/sources")
def list_sources() -> List[Dict[str, Any]]:
    return _fetch_all(
        "SELECT source_id, project_id, name, base_url, auth_type, username, index_pattern, time_field, enabled "
        "FROM metadata.opensearch_sources ORDER BY source_id"
    )


@app.get("/api/fields")
def list_fields() -> List[Dict[str, Any]]:
    return _fetch_all(
        "SELECT field_id, project_id, dataset, layer, table_name, column_name, column_type, mode, enabled "
        "FROM metadata.field_registry ORDER BY field_id"
    )


@app.get("/api/backfills")
def list_backfills() -> List[Dict[str, Any]]:
    return _fetch_all(
        "SELECT job_id, source_id, start_ts, end_ts, status, last_error, updated_at "
        "FROM metadata.backfill_jobs ORDER BY created_at DESC"
    )
