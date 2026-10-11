"""Approvals and the controlled release gate.

approve(): a QA approver signs a model version (meaning, time, signature hash). The author of the version
cannot approve it. release(): moves the 'production' alias only when all gates pass:

G1 PQ acceptance criteria (config/acceptance_criteria.yaml) pass on the eval run linked to the version
G2 traceability is complete (every URS has a passing verification) - results/traceability.json
G3 a valid approval by a qa_approver who is not the author, signed over the current model config hash
G4 lineage tags complete on the model version
G5 audit trail hash chain verifies
Every decision (released or blocked, with reasons) is written to the audit trail and results/release_decisions.json.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import yaml

from cgg import audit, config
from cgg.tracking import LINEAGE_KEYS, _experiment, _mlflow, run_metrics, version_tags

DECISIONS_FILE = config.RESULTS / "release_decisions.json"
OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b}


def evaluate_criteria(metrics: dict, criteria_file=config.ROOT / "config" / "acceptance_criteria.yaml") -> list[dict]:
    spec = yaml.safe_load(criteria_file.read_text())
    out = []
    for c in spec["criteria"]:
        v = metrics.get(c["metric"])
        ok = v is not None and OPS[c["op"]](float(v), float(c["threshold"]))
        out.append({**c, "value": v, "pass": bool(ok)})
    return out


def _signature(version: int, user: str, meaning: str, ts: str, cfg_hash: str) -> str:
    return hashlib.sha256(f"{config.REGISTERED_MODEL}|{version}|{user}|{meaning}|{ts}|{cfg_hash}".encode()).hexdigest()


def approve(version: int, meaning: str, as_user: str | None = None) -> dict:
    from mlflow import MlflowClient

    user = audit.require("approve_release", as_user)
    _mlflow()
    tags = version_tags(version)
    if tags.get("author") == user:
        audit.append("approval.refused", f"models:/{config.REGISTERED_MODEL}/{version}",
                     {"reason": "author cannot approve own version"}, actor=user)
        raise audit.AccessDenied("segregation of duties: the author of a version cannot approve it")
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sig = _signature(version, user, meaning, ts, tags["model_config_sha256"])
    rec = {"approver": user, "roles": sorted(audit.roles_of(user)), "meaning": meaning, "ts_utc": ts,
           "model_config_sha256": tags["model_config_sha256"], "signature_sha256": sig}
    client = MlflowClient()
    for k, v in rec.items():
        client.set_model_version_tag(config.REGISTERED_MODEL, str(version), f"approval.{k}", str(v))
    audit.append("approval.sign", f"models:/{config.REGISTERED_MODEL}/{version}", rec, actor=user)
    return rec


def gates(version: int) -> dict:
    tags = version_tags(version)
    reasons: list[str] = []
    eval_run = tags.get("eval_run_name")
    crit = evaluate_criteria(run_metrics(eval_run)) if eval_run else []
    failed = [c for c in crit if not c["pass"]]
    g1 = bool(crit) and not failed
    if not g1:
        reasons += [f"{c['id']} {c['metric']}={c['value']} fails {c['op']} {c['threshold']}" for c in failed] or [
            "no evaluation run linked"]
    tr_path = config.RESULTS / "traceability.json"
    g2 = False
    if tr_path.exists():
        tr = json.loads(tr_path.read_text())
        open_items = [r["urs"] for r in tr["rows"] if r["status"] != "verified"]
        same_run = tr.get("eval_run", eval_run) == eval_run
        g2 = not open_items and same_run
        if open_items:
            reasons.append(f"traceability incomplete: {', '.join(open_items)}")
        if not same_run:
            reasons.append(f"traceability matrix was generated for {tr.get('eval_run')}, not {eval_run}")
    else:
        reasons.append("traceability matrix not generated")
    appr = tags.get("approval.approver")
    g3 = False
    if not appr:
        reasons.append("no QA approval recorded")
    elif appr == tags.get("author"):
        reasons.append("approval by the author is not valid")
    elif "qa_approver" not in audit.roles_of(appr):
        reasons.append(f"approver {appr} lacks qa_approver role")
    elif tags.get("approval.model_config_sha256") != tags.get("model_config_sha256"):
        reasons.append("approval was signed over a different model configuration")
    elif _signature(version, appr, tags["approval.meaning"], tags["approval.ts_utc"],
                    tags["model_config_sha256"]) != tags.get("approval.signature_sha256"):
        reasons.append("approval signature does not verify")
    else:
        g3 = True
    missing = [k for k in LINEAGE_KEYS if not tags.get(k)]
    g4 = not missing
    if missing:
        reasons.append(f"lineage tags missing: {', '.join(missing)}")
    av = audit.verify()
    g5 = av["ok"]
    if not g5:
        reasons.append(f"audit trail broken at seq {av.get('first_bad_seq')}")
    return {"G1_acceptance_criteria": g1, "G2_traceability": g2, "G3_approval": g3, "G4_lineage": g4,
            "G5_audit_trail": g5, "criteria": crit, "reasons": reasons, "eval_run": eval_run,
            "audit_head_hash": av.get("head_hash")}


def release(version: int, as_user: str | None = None, dry_run: bool = False) -> dict:
    from mlflow import MlflowClient

    user = audit.require("promote", as_user)
    mlflow = _mlflow()
    client = MlflowClient()
    g = gates(version)
    ok = all(g[k] for k in g if k.startswith("G"))
    try:
        prev = client.get_model_version_by_alias(config.REGISTERED_MODEL, "production").version
    except Exception:  # noqa: BLE001
        prev = None
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    decision = {"version": version, "requested_by": user, "ts_utc": ts, "released": bool(ok and not dry_run),
                "dry_run": dry_run, "previous_production": prev, "eval_run": g["eval_run"],
                "gates": {k: v for k, v in g.items() if k.startswith("G")}, "reasons": g["reasons"],
                "audit_head_hash_at_decision": g["audit_head_hash"],
                "criteria": [{k: c[k] for k in ("id", "metric", "op", "threshold", "value", "pass")}
                             for c in g["criteria"]]}
    if ok and not dry_run:
        client.set_registered_model_alias(config.REGISTERED_MODEL, "production", version)
        for k, v in {"deployment.released_utc": ts, "deployment.released_by": user,
                     "deployment.previous_production": str(prev), "validation_status": "released"}.items():
            client.set_model_version_tag(config.REGISTERED_MODEL, str(version), k, v)
        with mlflow.start_run(experiment_id=_experiment("clinical-graphrag-deployments"),
                              run_name=f"deploy-v{version}") as run:
            mlflow.set_tags({"model_version": str(version), "released_by": user, "previous_production": str(prev),
                             "eval_run": g["eval_run"]})
            mlflow.log_dict(decision, "deployment_record.json")
            decision["deployment_run_id"] = run.info.run_id
    if not ok and not dry_run:
        failed = ",".join(k.split("_")[0] for k, v in decision["gates"].items() if not v)
        client.set_model_version_tag(config.REGISTERED_MODEL, str(version), "validation_status",
                                     f"blocked by release gate ({failed})")
    if not dry_run:
        audit.append("release.promote" if ok else "release.blocked",
                     f"models:/{config.REGISTERED_MODEL}/{version}",
                     {"gates": decision["gates"], "reasons": g["reasons"], "previous_production": prev}, actor=user)
        hist = json.loads(DECISIONS_FILE.read_text()) if DECISIONS_FILE.exists() else []
        hist.append(decision)
        DECISIONS_FILE.write_text(json.dumps(hist, indent=1, default=str))
    return decision
