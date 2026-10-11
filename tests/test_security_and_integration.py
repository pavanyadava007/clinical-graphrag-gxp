import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = [r"sk-lf-[0-9a-f]{16,}", r"pk-lf-[0-9a-f]{12,}", r"hf_[A-Za-z0-9]{30,}", r"ghp_[A-Za-z0-9]{30,}",
            r"NEO4J_AUTH=neo4j/(?!\$)", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"]


@pytest.mark.req("URS-026")
def test_no_secrets_in_tracked_files():
    files = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).split()
    assert "infra/.env" not in files
    hits = []
    for f in files:
        p = ROOT / f
        if not p.is_file() or p.stat().st_size > 5_000_000 or p == Path(__file__).resolve():
            continue
        txt = p.read_text(errors="ignore")
        for pat in PATTERNS:
            if re.search(pat, txt):
                hits.append((f, pat))
    assert hits == []


@pytest.mark.integration
@pytest.mark.req("URS-007")
def test_graph_snapshot_matches_gold_report():
    import json

    from cgg.graph.store import neo4j_snapshot_hash

    rep = json.loads((ROOT / "results" / "graph_load_report.json").read_text())
    assert neo4j_snapshot_hash() == rep["gold_snapshot_sha256"]


@pytest.mark.integration
@pytest.mark.req("URS-009")
def test_read_only_session_blocks_writes_even_without_validator():
    from neo4j import READ_ACCESS
    from neo4j.exceptions import ClientError

    from cgg.graph.store import QueryRejected, driver, run_read

    with pytest.raises(QueryRejected):
        run_read("MATCH (n) DETACH DELETE n")
    with driver().session(default_access_mode=READ_ACCESS) as s:
        with pytest.raises(ClientError):
            s.execute_read(lambda tx: tx.run("CREATE (:Label {set_id: 'should-not-exist'})").consume())
    _, rows = run_read("MATCH (l:Label {set_id: 'should-not-exist'}) RETURN count(l) AS answer")
    assert rows[0]["answer"] == 0


@pytest.mark.integration
@pytest.mark.req("URS-019")
def test_langfuse_sample_has_spans_and_scores():
    import json

    p = ROOT / "results" / "langfuse_sample.json"
    if not p.exists():
        pytest.skip("no exported Langfuse sample yet")
    d = json.loads(p.read_text())
    t = d["sample"][0]
    assert t["observations"] and t["scores"]
    assert {"route", "text2cypher"} & {o["name"] for o in t["observations"]}


@pytest.mark.integration
@pytest.mark.req("URS-018")
def test_registered_versions_carry_lineage():
    from cgg import config

    if not (ROOT / "mlflow.db").exists():
        pytest.skip("no local MLflow store")
    from mlflow import MlflowClient

    from cgg.tracking import LINEAGE_KEYS, _mlflow

    _mlflow()
    vs = MlflowClient().search_model_versions(f"name='{config.REGISTERED_MODEL}'")
    if not vs:
        pytest.skip("no registered versions yet")
    for v in vs:
        assert not [k for k in LINEAGE_KEYS if not v.tags.get(k)]
