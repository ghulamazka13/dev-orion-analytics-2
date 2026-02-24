#!/usr/bin/env python
import argparse
import os
from pathlib import Path

import psycopg2
import psycopg2.extras


DEFAULT_DSN = os.getenv(
    "POSTGRES_DSN",
    "postgresql://airflow:airflow@localhost:15432/airflow",
)


def has_sql_text_column(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) AS count
            FROM information_schema.columns
            WHERE table_schema = 'metadata'
              AND table_name = 'gold_pipelines'
              AND column_name = 'sql_text'
            """
        )
        return int(cur.fetchone()[0]) > 0


def resolve_sql_path(base_dir: Path, sql_path: str) -> Path:
    candidate = Path(sql_path)
    if candidate.is_absolute():
        return candidate
    return (base_dir / candidate).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync airflow/dags/sql/*.sql content into metadata.gold_pipelines.sql_text"
    )
    parser.add_argument("--dsn", default=DEFAULT_DSN, help="Postgres DSN")
    parser.add_argument(
        "--dags-dir",
        default=str((Path(__file__).resolve().parents[1] / "airflow" / "dags").resolve()),
        help="Base directory for resolving sql_path (default: repo/airflow/dags)",
    )
    parser.add_argument(
        "--clear-sql-path",
        action="store_true",
        help="Set sql_path = NULL after sql_text is updated",
    )
    args = parser.parse_args()

    base_dir = Path(args.dags_dir).resolve()
    if not base_dir.exists():
        print(f"[error] dags dir not found: {base_dir}")
        return 1

    conn = psycopg2.connect(args.dsn)
    conn.autocommit = False
    try:
        if not has_sql_text_column(conn):
            print("[error] column metadata.gold_pipelines.sql_text not found")
            print("        apply migration: postgres/init/12_gold_sql_text.sql")
            conn.rollback()
            return 1

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, pipeline_name, sql_path
                FROM metadata.gold_pipelines
                ORDER BY id
                """
            )
            rows = list(cur.fetchall())

        updated = 0
        missing = 0
        skipped = 0

        with conn.cursor() as cur:
            for row in rows:
                pipeline_id = row["id"]
                pipeline_name = row["pipeline_name"]
                sql_path = row.get("sql_path")
                if not sql_path or not str(sql_path).strip():
                    skipped += 1
                    print(f"[skip] {pipeline_name}: sql_path empty")
                    continue

                resolved = resolve_sql_path(base_dir, str(sql_path))
                if not resolved.exists():
                    missing += 1
                    print(f"[missing] {pipeline_name}: {resolved}")
                    continue

                sql_text = resolved.read_text(encoding="utf-8")
                if args.clear_sql_path:
                    cur.execute(
                        """
                        UPDATE metadata.gold_pipelines
                        SET sql_text = %s,
                            sql_path = NULL,
                            updated_at = now()
                        WHERE id = %s
                        """,
                        (sql_text, pipeline_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE metadata.gold_pipelines
                        SET sql_text = %s,
                            updated_at = now()
                        WHERE id = %s
                        """,
                        (sql_text, pipeline_id),
                    )
                updated += 1
                print(f"[ok] {pipeline_name}: {resolved}")

        conn.commit()
        print(
            f"[done] updated={updated} missing={missing} skipped={skipped} clear_sql_path={args.clear_sql_path}"
        )
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"[error] sync failed: {exc}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
