"""Pytest setup: requirement markers are collected into results/oq_results.json (OQ evidence) when
CGG_OQ_RECORD=1, and integration tests are skipped when the local services are not running."""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_RESULTS: list[dict] = []


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def pytest_collection_modifyitems(config, items):
    neo4j_up = _port_open(7687) and bool(os.environ.get("CGG_NEO4J_PASSWORD") or (ROOT / "infra" / ".env").exists())
    for item in items:
        if "integration" in item.keywords and not neo4j_up:
            item.add_marker(pytest.mark.skip(reason="Neo4j not running on 127.0.0.1:7687"))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    reqs = [m.args[0] for m in item.iter_markers("req")]
    if not reqs:
        return
    if rep.when == "call" or (rep.when == "setup" and rep.skipped):
        _RESULTS.append({"nodeid": item.nodeid, "req": reqs, "outcome": rep.outcome,
                         "duration_s": round(rep.duration, 3)})


def pytest_sessionfinish(session, exitstatus):
    if os.environ.get("CGG_OQ_RECORD") != "1":
        return
    import platform

    out = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "python": platform.python_version(), "exitstatus": int(exitstatus), "tests": _RESULTS}
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "oq_results.json").write_text(json.dumps(out, indent=1))


@pytest.fixture(autouse=True)
def _isolated_audit(tmp_path, monkeypatch):
    """Tests never write to the real audit trail or review queue."""
    from cgg import config

    monkeypatch.setattr(config, "AUDIT_LOG", tmp_path / "audit.jsonl")
    monkeypatch.setattr(config, "HITL_DIR", tmp_path / "hitl")
    yield
