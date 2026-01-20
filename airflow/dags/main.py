import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable

from airflow import DAG  # imported so Airflow safe mode parses this file
from generator.gold_pipeline import GoldPipelineGenerator


@dataclass(frozen=True)
class GeneratorSpec:
    name: str
    load_configs: Callable[[], Iterable[Dict[str, Any]]]
    build_dag: Callable[[Dict[str, Any]], Any]


GOLD_GENERATOR = GoldPipelineGenerator()


def _load_gold_configs():
    logging.info("Loading gold pipeline configs from metadata file")
    return GOLD_GENERATOR.load_configs()


def _build_gold_dag(dag_cfg: Dict[str, Any]):
    logging.info("Building gold DAG %s", dag_cfg.get("dag_id"))
    return GOLD_GENERATOR.generate_dag(dag_cfg)


def _register_dags(spec: GeneratorSpec, seen: set) -> None:
    dag_cfgs = list(spec.load_configs() or [])
    logging.info("Registering %s DAG configs for %s", len(dag_cfgs), spec.name)
    if not dag_cfgs:
        logging.warning("No DAG configs loaded for %s", spec.name)
    for dag_cfg in dag_cfgs:
        if not isinstance(dag_cfg, dict):
            continue
        if not dag_cfg.get("enabled", True):
            continue
        dag_name = dag_cfg.get("dag_id") or dag_cfg.get("dag_name")
        if not dag_name:
            logging.warning("Skipping DAG without name from %s", spec.name)
            continue
        if dag_name in seen:
            logging.warning("DAG %s already registered; skipping %s", dag_name, spec.name)
            continue
        try:
            dag = spec.build_dag(dag_cfg)
        except Exception as exc:
            logging.warning("Failed to build DAG %s from %s: %s", dag_name, spec.name, exc)
            continue
        globals()[dag_name] = dag
        seen.add(dag_name)
        logging.info("Registered DAG %s from %s", dag_name, spec.name)


def _load_generators() -> None:
    seen: set = set()
    for spec in GENERATORS:
        _register_dags(spec, seen)


GENERATORS = [
    GeneratorSpec(
        name="gold_pipelines",
        load_configs=_load_gold_configs,
        build_dag=_build_gold_dag,
    ),
]

_load_generators()
