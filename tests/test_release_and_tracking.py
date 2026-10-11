import json

import pytest

from cgg import audit, config, release, tracking

GOOD_METRICS = {"precision_auto": 0.95, "accuracy_after_review": 0.97, "escalation_rate": 0.1,
                "citation_precision": 1.0, "ungrounded_answer_rate": 0.0, "repeat_agreement": 1.0,
                "paraphrase_agreement": 0.9, "typo_accuracy_drop": 0.0, "unsafe_handled_rate": 1.0,
                "false_refusal_rate": 0.0, "error_rate": 0.0, "latency_p95_s": 5.0}


def _tags(**over):
    t = {k: "x" for k in tracking.LINEAGE_KEYS}
    t.update({"author": "pavan.dev", "eval_run_name": "run1", "model_config_sha256": "c" * 64})
    t.update(over)
    return t


@pytest.fixture
def gate_env(monkeypatch, tmp_path):
    state = {"tags": _tags(), "metrics": dict(GOOD_METRICS)}
    monkeypatch.setattr(release, "version_tags", lambda v: state["tags"])
    monkeypatch.setattr(release, "run_metrics", lambda r: state["metrics"])
    monkeypatch.setattr(config, "RESULTS", tmp_path)
    (tmp_path / "traceability.json").write_text(json.dumps({"rows": [{"urs": "URS-001", "status": "verified"}]}))
    return state


def _sign(state, user="qa.approver"):
    ts = "2026-10-11T00:00:00+00:00"
    sig = release._signature(1, user, "approved", ts, state["tags"]["model_config_sha256"])
    state["tags"].update({"approval.approver": user, "approval.meaning": "approved", "approval.ts_utc": ts,
                          "approval.model_config_sha256": state["tags"]["model_config_sha256"],
                          "approval.signature_sha256": sig})


@pytest.mark.req("URS-025")
def test_all_gates_pass(gate_env):
    _sign(gate_env)
    g = release.gates(1)
    assert all(g[k] for k in g if k.startswith("G")), g["reasons"]


@pytest.mark.req("URS-025")
def test_failed_criterion_blocks(gate_env):
    _sign(gate_env)
    gate_env["metrics"]["citation_precision"] = 0.5
    g = release.gates(1)
    assert not g["G1_acceptance_criteria"] and any("AC-04" in r for r in g["reasons"])


@pytest.mark.req("URS-025")
def test_missing_approval_and_traceability_block(gate_env, tmp_path):
    (tmp_path / "traceability.json").write_text(json.dumps({"rows": [{"urs": "URS-009", "status": "failed"}]}))
    g = release.gates(1)
    assert not g["G3_approval"] and not g["G2_traceability"]


@pytest.mark.req("URS-024")
def test_author_cannot_approve(gate_env):
    gate_env["tags"]["author"] = "qa.approver"
    with pytest.raises(audit.AccessDenied):
        release.approve(1, "approved", "qa.approver")
    _sign(gate_env, user="qa.approver")
    assert not release.gates(1)["G3_approval"]


@pytest.mark.req("URS-024")
def test_approval_over_changed_config_is_invalid(gate_env):
    _sign(gate_env)
    gate_env["tags"]["model_config_sha256"] = "d" * 64
    assert not release.gates(1)["G3_approval"]


@pytest.mark.req("URS-018")
def test_missing_lineage_blocks(gate_env):
    _sign(gate_env)
    del gate_env["tags"]["kg_snapshot_sha256"]
    g = release.gates(1)
    assert not g["G4_lineage"] and any("kg_snapshot_sha256" in r for r in g["reasons"])


@pytest.mark.req("URS-025")
def test_broken_audit_trail_blocks(gate_env):
    _sign(gate_env)
    audit.append("x", "y", actor="pavan.dev")
    audit.append("x", "z", actor="pavan.dev")
    lines = config.AUDIT_LOG.read_text().splitlines()
    config.AUDIT_LOG.write_text(lines[1] + "\n")
    assert not release.gates(1)["G5_audit_trail"]


@pytest.mark.req("URS-017")
def test_eval_run_logged_to_mlflow(tmp_path, monkeypatch):
    """Log a tiny synthetic eval run into a throwaway MLflow store and read it back."""
    import mlflow

    from cgg import evaluate

    monkeypatch.setattr(config, "MLFLOW_URI", f"sqlite:///{tmp_path / 'm.db'}")
    monkeypatch.setattr(config, "MLFLOW_ARTIFACTS", tmp_path / "art")
    monkeypatch.setattr(evaluate, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(tracking, "lineage_snapshot", lambda: {"git_commit": "abc", "gold_set_sha256": "f" * 64,
                                                               "delta.silver.labels.version": "0"})
    monkeypatch.setattr(tracking, "register_prompts", lambda: {"answer@v1": {"uri": "prompts:/cgg-answer/1"}})
    monkeypatch.setattr(tracking, "_live_digest", lambda m: "digest123")
    d = tmp_path / "runs" / "r1"
    d.mkdir(parents=True)
    rec = {"status": "answered", "route": "graph", "answer": 3, "latency_s": 1.0, "trace_id": "t1",
           "cypher": "MATCH", "reason": None}
    (d / "answers.jsonl").write_text(json.dumps({"qid": "A1-01", "variant": "original", "question": "q",
                                                 "record": rec, "score": {"correct": True}}) + "\n")
    (d / "metrics.json").write_text(json.dumps({"system": "C_guarded_graphrag", "accuracy": 1.0,
                                                "n_requests": 1, "tracing_backend": "none",
                                                "params": {"model": "m", "prompt.answer": "answer@v1"},
                                                "accuracy_by_template": {"A1": {"acc": 1.0, "n": 1}}}))
    (d / "run_meta.json").write_text(json.dumps({"started_utc": "2026-10-11T00:00:00"}))
    monkeypatch.setattr(config, "GOLD_DIR", tmp_path)
    import pandas as pd

    pd.DataFrame([{"set_id": "s", "brand_name": "b", "generic_name": "g", "manufacturer": "m", "version": 1}]
                 ).to_parquet(tmp_path / "labels.parquet")
    for f in ("pipeline_report.json", "graph_load_report.json", "embedding_report.json"):
        (tmp_path / f).write_text("{}")
    monkeypatch.setattr(config, "RESULTS", tmp_path)
    rid = tracking.log_eval_run("r1")
    mlflow.set_tracking_uri(config.MLFLOW_URI)
    run = mlflow.get_run(rid)
    assert run.data.params["model"] == "m" and run.data.params["prompt.answer"] == "answer@v1"
    assert run.data.metrics["accuracy"] == 1.0 and run.data.metrics["accuracy_by_template.A1.acc"] == 1.0
    assert run.data.tags["git_commit"] == "abc" and run.data.tags["llm_digest"] == "digest123"
    assert {i.dataset.name for i in run.inputs.dataset_inputs} == {"gold_set", "silver.labels"}
