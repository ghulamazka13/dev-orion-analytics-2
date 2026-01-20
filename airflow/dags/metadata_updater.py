import logging
import os
from typing import Any, Dict, List

import yaml
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago

from generator.gold_pipeline import GoldPipelineGenerator

DEFAULT_OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "gold_pipelines.yml")


def _select_dag_config(configs: List[Dict[str, Any]], dag_id: str) -> Dict[str, Any]:
    if dag_id:
        for cfg in configs:
            if cfg.get("dag_id") == dag_id:
                return cfg
        raise ValueError(f"DAG config not found for dag_id={dag_id}")
    if len(configs) == 1:
        return configs[0]
    raise ValueError("Multiple DAG configs found; set GOLD_METADATA_DAG_ID")


def _build_payload(dag_cfg: Dict[str, Any]) -> Dict[str, Any]:
    dag_section = {
        "dag_id": dag_cfg.get("dag_id"),
        "schedule_cron": dag_cfg.get("schedule_cron"),
        "timezone": dag_cfg.get("timezone"),
        "owner": dag_cfg.get("owner"),
        "tags": dag_cfg.get("tags") or [],
        "max_active_tasks": int(dag_cfg.get("max_active_tasks") or 8),
        "default_window_minutes": int(dag_cfg.get("default_window_minutes") or 10),
    }
    if "enabled" in dag_cfg:
        dag_section["enabled"] = bool(dag_cfg.get("enabled"))

    pipelines_payload: List[Dict[str, Any]] = []
    for pipeline in dag_cfg.get("pipelines") or []:
        entry: Dict[str, Any] = {
            "pipeline_id": pipeline.get("pipeline_id"),
            "enabled": bool(pipeline.get("enabled", True)),
            "sql_path": pipeline.get("sql_path"),
        }
        if pipeline.get("window_minutes") is not None:
            entry["window_minutes"] = int(pipeline.get("window_minutes"))
        depends_on = pipeline.get("depends_on") or []
        if depends_on:
            entry["depends_on"] = depends_on
        params = pipeline.get("params") or {}
        if params:
            entry["params"] = params
        pipelines_payload.append(entry)

    return {
        "dag": dag_section,
        "pipelines": pipelines_payload,
    }


def _resolve_output_path() -> str:
    output_path = os.environ.get("GOLD_PIPELINES_PATH")
    if output_path:
        if not os.path.isabs(output_path):
            output_path = os.path.join(os.path.dirname(__file__), output_path)
        return os.path.abspath(output_path)
    return os.path.abspath(DEFAULT_OUTPUT_PATH)


def refresh_metadata_cache() -> None:
    generator = GoldPipelineGenerator()
    dag_id = (
        os.environ.get("GOLD_METADATA_DAG_NAME")
        or os.environ.get("GOLD_METADATA_DAG_ID")
        or ""
    )
    configs = generator.load_configs_from_postgres()
    if not configs:
        raise ValueError("No metadata configs loaded from Postgres")

    dag_cfg = _select_dag_config(configs, dag_id)
    payload = _build_payload(dag_cfg)

    output_path = _resolve_output_path()
    rendered = yaml.safe_dump(
        payload,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=False,
    )

    if os.path.exists(output_path):
        with open(output_path, "r", encoding="utf-8") as handle:
            existing = handle.read()
        if existing == rendered:
            logging.info("Metadata YAML already up-to-date at %s", output_path)
            return

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    logging.info("Updated metadata YAML at %s", output_path)


with DAG(
    dag_id="metadata_updater",
    start_date=days_ago(1),
    schedule_interval="*/10 * * * *",
    catchup=False,
    tags=["metadata", "gold"],
) as dag:
    PythonOperator(
        task_id="refresh_gold_metadata",
        python_callable=refresh_metadata_cache,
    )
