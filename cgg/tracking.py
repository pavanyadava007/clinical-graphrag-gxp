"""MLflow integration: prompt registry, evaluation runs (params, datasets, metrics, artifacts, trace ids),
model registration (models-from-code) with lineage tags and the 'candidate' alias."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from cgg import audit, config, promptlib

EXPERIMENT = "clinical-graphrag-pq"
DEPLOY_EXPERIMENT = "clinical-graphrag-deployments"
LINEAGE_KEYS = ["git_commit", "eval_run_id", "eval_run_name", "gold_set_sha256", "kg_snapshot_sha256",
                "delta.silver.labels.version", "delta.silver.sections.version", "delta.gold.chunks.version",
                "delta.gold.kg_nodes.version", "delta.gold.kg_edges.version", "embeddings_sha256",
                "prompt.router", "prompt.text2cypher", "prompt.answer", "prompt.safety", "llm_model", "llm_digest",
                "author"]


def _mlflow():
    import logging

    import mlflow

    for name in ("mlflow", "alembic"):
        logging.getLogger(name).setLevel(logging.WARNING)

    mlflow.set_tracking_uri(config.MLFLOW_URI)
    return mlflow


def _experiment(name: str) -> str:
    mlflow = _mlflow()
    exp = mlflow.get_experiment_by_name(name)
    if exp is None:
        config.MLFLOW_ARTIFACTS.mkdir(exist_ok=True)
        return mlflow.create_experiment(name, artifact_location=(config.MLFLOW_ARTIFACTS / name).as_uri())
    return exp.experiment_id


def git_commit() -> str:
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=config.ROOT, text=True).strip()
        dirty = subprocess.call(["git", "diff", "--quiet", "HEAD", "--", "cgg", "config"], cwd=config.ROOT) != 0
        return sha + ("-dirty" if dirty else "")
    except Exception:  # noqa: BLE001
        return "unknown"


def lineage_snapshot() -> dict:
    pipe = json.loads((config.RESULTS / "pipeline_report.json").read_text())
    emb = json.loads((config.GOLD_DIR / "embedding_manifest.json").read_text())
    gold = json.loads((config.EVAL_DIR / "gold_manifest.json").read_text())
    graph = json.loads((config.RESULTS / "graph_load_report.json").read_text())
    d = {
        "git_commit": git_commit(),
        "gold_set_sha256": gold["sha256"],
        "kg_snapshot_sha256": graph["neo4j_snapshot_sha256"],
        "kg_snapshot_matches_gold_tables": str(graph["match"]),
        "embeddings_sha256": emb["embeddings_sha256"],
        "embedding_model": f"{emb['model']}@{emb['model_digest'][:12]}",
        "ingest_run_id": pipe["ingest_run_id"],
        "raw_manifest_sha256": pipe["raw_manifest_sha256"],
    }
    for k, v in pipe["delta_versions"].items():
        d[f"delta.{k}.version"] = str(v)
    return d


def _live_digest(model: str) -> str:
    from cgg.llm import Ollama

    return Ollama(model=model).model_digest()


# ------------------------------------------------------------------ prompts
def register_prompts() -> dict:
    """Register every prompt file version in the MLflow prompt registry (idempotent by content hash)."""
    mlflow = _mlflow()
    out = {}
    for p in promptlib.all_prompts():
        name = f"cgg-{p.name}"
        existing = None
        try:
            existing = mlflow.genai.load_prompt(f"prompts:/{name}/{p.version}")
        except Exception:  # noqa: BLE001
            existing = None
        if existing is not None:
            out[p.ref] = {"uri": f"prompts:/{name}/{existing.version}", "status": "exists",
                          "sha256": existing.tags.get("sha256")}
            continue
        reg = mlflow.genai.register_prompt(
            name=name,
            template=[{"role": "system", "content": p.system}, {"role": "user", "content": p.user}],
            commit_message=p.description,
            tags={"sha256": p.sha256, "file": f"cgg/prompts/{p.name}.v{p.version}.yaml", "git_commit": git_commit()},
        )
        if int(reg.version) != p.version:
            raise RuntimeError(f"registry version {reg.version} != file version {p.version} for {name}")
        out[p.ref] = {"uri": f"prompts:/{name}/{reg.version}", "status": "registered", "sha256": p.sha256}
        audit.append("prompt.register", f"prompts:/{name}/{reg.version}", {"sha256": p.sha256}, actor="pavan.dev")
    return out


# ------------------------------------------------------------------ evaluation runs
def _flat(prefix: str, d: dict, out: dict):
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out[key] = float(v)
        elif isinstance(v, dict):
            _flat(key + ".", v, out)


def log_eval_run(run_name: str) -> str:
    import mlflow.data
    import pandas as pd
    from mlflow.data.delta_dataset_source import DeltaDatasetSource

    from cgg.evaluate import RUNS
    from cgg.pipeline.medallion import TABLES

    mlflow = _mlflow()
    exp = _experiment(EXPERIMENT)
    d = RUNS / run_name
    m = json.loads((d / "metrics.json").read_text())
    meta = json.loads((d / "run_meta.json").read_text())
    lin = lineage_snapshot()
    prompts = register_prompts()
    digest = meta.get("llm_digest") or _live_digest(m["params"]["model"])
    with mlflow.start_run(experiment_id=exp, run_name=run_name) as run:
        mlflow.log_params({**m["params"], "system": m["system"], "n_requests": m["n_requests"]})
        mlflow.set_tags({**lin, "eval_git_commit": meta.get("git_commit", "not recorded"), "system": m["system"],
                         "llm_digest": digest, "tracing_backend": m["tracing_backend"],
                         "eval_started_utc": meta["started_utc"], "judge": "deterministic (no LLM judge)",
                         **{f"prompt_uri.{k.replace('@', '.')}": v["uri"] for k, v in prompts.items()}})
        metrics: dict = {}
        _flat("", {k: v for k, v in m.items() if k not in ("params",)}, metrics)
        mlflow.log_metrics(metrics)
        gold = pd.read_json(config.EVAL_DIR / "gold_set.jsonl", lines=True)
        gold_ds = mlflow.data.from_pandas(
            gold[["qid", "template", "category", "answer_type", "question"]], name="gold_set",
            source=str(config.EVAL_DIR / "gold_set.jsonl"), digest=lin["gold_set_sha256"][:16])
        mlflow.log_input(gold_ds, context="evaluation")
        labels = pd.read_parquet(config.GOLD_DIR / "labels.parquet", columns=["set_id", "brand_name", "generic_name",
                                                                               "manufacturer", "version"])
        src = DeltaDatasetSource(path=TABLES["silver.labels"],
                                 delta_table_version=int(lin["delta.silver.labels.version"]))
        mlflow.log_input(mlflow.data.from_pandas(labels, source=src, name="silver.labels"), context="source")
        rows = [json.loads(ln) for ln in (d / "answers.jsonl").read_text().splitlines() if ln.strip()]
        table = pd.DataFrame([{
            "qid": r["qid"], "variant": r["variant"], "question": r["question"], "status": r["record"]["status"],
            "route": r["record"]["route"], "answer": json.dumps(r["record"]["answer"], default=str)[:500],
            "correct": r["score"]["correct"], "latency_s": r["record"]["latency_s"],
            "trace_id": r["record"]["trace_id"], "cypher": r["record"]["cypher"], "reason": r["record"]["reason"],
        } for r in rows])
        mlflow.log_table(table, "eval/per_question.json")
        mlflow.log_artifact(str(d / "metrics.json"), "eval")
        mlflow.log_artifact(str(d / "answers.jsonl"), "eval")
        mlflow.log_artifact(str(d / "run_meta.json"), "eval")
        if (d / "reviews.json").exists():
            mlflow.log_artifact(str(d / "reviews.json"), "eval")
        mlflow.log_dict({"langfuse_host": "self-hosted v2 (127.0.0.1)", "trace_ids": table.trace_id.tolist()},
                        "eval/langfuse_trace_ids.json")
        for f in ("pipeline_report.json", "graph_load_report.json", "embedding_report.json"):
            mlflow.log_artifact(str(config.RESULTS / f), "lineage")
        mlflow.log_artifact(str(config.ROOT / "config" / "acceptance_criteria.yaml"), "lineage")
        rid = run.info.run_id
    (d / "mlflow_run_id.txt").write_text(rid)
    audit.append("mlflow.log_eval", f"mlflow-run/{rid}", {"run_name": run_name}, actor="pavan.dev")
    return rid


# ------------------------------------------------------------------ model registry
def register_model(eval_run: str, as_user: str | None = None) -> dict:
    from mlflow import MlflowClient

    from cgg.evaluate import RUNS

    user = audit.require("register_model", as_user)
    mlflow = _mlflow()
    client = MlflowClient()
    d = RUNS / eval_run
    eval_run_id = (d / "mlflow_run_id.txt").read_text().strip()
    m = json.loads((d / "metrics.json").read_text())
    params = m["params"]
    if not m["system"].startswith("C_"):
        raise ValueError("only the guarded system C is registered for release")
    model_config = {"system": "C", "model": params["model"], "temperature": params["temperature"],
                    "seed": params["seed"], "top_k": params["top_k"],
                    "prompts": {k.split(".", 1)[1]: int(v.split("@v")[1]) for k, v in params.items()
                                if k.startswith("prompt.")}}
    lin = lineage_snapshot()
    meta = json.loads((d / "run_meta.json").read_text())
    digest = meta.get("llm_digest") or _live_digest(params["model"])
    exp = _experiment(EXPERIMENT)
    with mlflow.start_run(experiment_id=exp, run_name=f"package-{eval_run}") as run:
        mlflow.set_tags({**lin, "eval_run_id": eval_run_id, "kind": "model-package"})
        info = mlflow.pyfunc.log_model(
            name="model",
            python_model=str(config.ROOT / "cgg" / "serving_model.py"),
            model_config=model_config,
            code_paths=[str(config.ROOT / "cgg")],
            pip_requirements=["mlflow>=3.1,<3.6", "neo4j>=5.20,<6", "httpx>=0.27", "pandas>=2", "numpy>=1.26",
                              "pyyaml>=6", "langfuse>=2.50,<3", "pyarrow>=15"],
        )
        pkg_run = run.info.run_id
    mv = mlflow.register_model(info.model_uri, config.REGISTERED_MODEL)
    cfg_hash = hashlib.sha256(json.dumps(model_config, sort_keys=True).encode()).hexdigest()
    tags = {
        **{k: str(v) for k, v in lin.items()},
        "eval_run_id": eval_run_id, "eval_run_name": eval_run, "package_run_id": pkg_run,
        "prompt.router": f"router@v{model_config['prompts']['router']}",
        "prompt.text2cypher": f"text2cypher@v{model_config['prompts']['text2cypher']}",
        "prompt.answer": f"answer@v{model_config['prompts']['answer']}",
        "prompt.safety": f"safety@v{model_config['prompts']['safety']}",
        "llm_model": params["model"], "llm_digest": digest, "model_config_sha256": cfg_hash, "author": user,
        "validation_status": "candidate - not released",
    }
    for k, v in tags.items():
        client.set_model_version_tag(config.REGISTERED_MODEL, mv.version, k, v)
    client.set_registered_model_alias(config.REGISTERED_MODEL, "candidate", mv.version)
    audit.append("model.register", f"models:/{config.REGISTERED_MODEL}/{mv.version}",
                 {"eval_run": eval_run, "model_config_sha256": cfg_hash, "alias": "candidate"}, actor=user)
    return {"name": config.REGISTERED_MODEL, "version": int(mv.version), "alias": "candidate",
            "model_uri": info.model_uri, "tags": tags}


def version_tags(version: int) -> dict:
    from mlflow import MlflowClient

    _mlflow()
    return dict(MlflowClient().get_model_version(config.REGISTERED_MODEL, str(version)).tags)


def run_metrics(eval_run: str) -> dict:
    from cgg.evaluate import RUNS

    return json.loads((RUNS / eval_run / "metrics.json").read_text())


def artifact_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
