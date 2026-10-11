"""Generate the traceability matrix and the validation summary report from code, tests and results.

Inputs: docs/validation/urs.yaml, risks.yaml, deviations.yaml, config/acceptance_criteria.yaml,
results/oq_results.json (pytest run with CGG_OQ_RECORD=1), results/iq_report.json,
results/runs/<pq run>/metrics.json, mlflow_run_id.txt, results/release_decisions.json.
Outputs: docs/validation/{urs,risk_assessment,traceability_matrix,validation_summary_report}.md and
results/traceability.json. Nothing in these files is typed by hand.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import yaml

from cgg import audit, config
from cgg.release import evaluate_criteria

VAL = config.DOCS / "validation"
PQ_RUN = "pq-C-llama3.1-8b"


def _load(p):
    return yaml.safe_load(p.read_text())


def _json(p, default=None):
    return json.loads(p.read_text()) if p.exists() else default


def generate(pq_run: str = PQ_RUN) -> dict:
    urs = _load(VAL / "urs.yaml")["requirements"]
    risks = _load(VAL / "risks.yaml")["risks"]
    devs = _load(VAL / "deviations.yaml")["deviations"]
    oq = _json(config.RESULTS / "oq_results.json", {"tests": []})
    iq = _json(config.RESULTS / "iq_report.json", {})
    run_dir = config.RESULTS / "runs" / pq_run
    metrics = _json(run_dir / "metrics.json", {})
    mlflow_run = (run_dir / "mlflow_run_id.txt").read_text().strip() if (run_dir / "mlflow_run_id.txt").exists() \
        else "not logged"
    crit = {c["id"]: c for c in evaluate_criteria(metrics)} if metrics else {}
    decisions = _json(config.RESULTS / "release_decisions.json", [])
    released = [d for d in decisions if d.get("released") and d.get("eval_run") == pq_run]
    release_ref = f"model version {released[-1]['version']} (production)" if released else "not released yet"

    risk_by_urs: dict = {}
    for r in risks:
        for u in r["urs"]:
            risk_by_urs.setdefault(u, []).append(r["id"])
    tests_by_urs: dict = {}
    for t in oq["tests"]:
        for u in t["req"]:
            tests_by_urs.setdefault(u, []).append(t)
    rows = []
    for u in urs:
        v = u["verification"]
        tests = tests_by_urs.get(u["id"], [])
        oq_ok = (not v["oq"]) or (bool(tests) and all(t["outcome"] == "passed" for t in tests))
        pq_items = [crit.get(c) for c in v["pq"]]
        pq_ok = all(c is not None and c["pass"] for c in pq_items)
        missing = (v["oq"] and not tests) or any(c is None for c in pq_items)
        status = "verified" if oq_ok and pq_ok and not missing else ("not verified" if missing else "failed")
        rows.append({
            "urs": u["id"], "area": u["area"], "gxp_impact": u["gxp_impact"], "text": u["text"],
            "risks": risk_by_urs.get(u["id"], []),
            "oq_tests": [{"test": t["nodeid"], "outcome": t["outcome"]} for t in tests],
            "pq": [{"id": c["id"], "metric": c["metric"], "value": c["value"], "op": c["op"],
                    "threshold": c["threshold"], "pass": c["pass"]} for c in pq_items if c],
            "mlflow_run": mlflow_run if v["pq"] else "", "release": release_ref if status == "verified" else "",
            "status": status,
        })
    out = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "eval_run": pq_run,
           "mlflow_run_id": mlflow_run, "rows": rows,
           "summary": {s: sum(r["status"] == s for r in rows) for s in ("verified", "failed", "not verified")}}
    (config.RESULTS / "traceability.json").write_text(json.dumps(out, indent=1))
    _write_urs(urs)
    _write_risks(risks, urs)
    _write_matrix(out)
    _write_vsr(out, oq, iq, metrics, crit, devs, decisions, pq_run)
    audit.append("validation.report", "docs/validation", {"summary": out["summary"], "eval_run": pq_run},
                 actor="pavan.dev")
    return out["summary"]


def _write_urs(urs):
    lines = ["# User Requirements Specification", "",
             "Generated from `docs/validation/urs.yaml`. GxP impact: High = could affect the correctness of label "
             "information given to medical-information staff.", "",
             "| ID | Area | GxP impact | Requirement | OQ | PQ criteria |", "|---|---|---|---|---|---|"]
    for u in urs:
        v = u["verification"]
        lines.append(f"| {u['id']} | {u['area']} | {u['gxp_impact']} | {u['text']} | "
                     f"{'yes' if v['oq'] else '-'} | {', '.join(v['pq']) or '-'} |")
    (VAL / "urs.md").write_text("\n".join(lines) + "\n")


def _write_risks(risks, urs):
    lines = ["# Risk Assessment (FMEA)", "",
             "Generated from `docs/validation/risks.yaml`. S = severity, O = occurrence, D = detectability "
             "(1 = always detected), each 1 to 5; RPN = S x O x D before mitigation. Controls link to URS items, "
             "which link to tests in the traceability matrix.", "",
             "| ID | Hazard | Effect | S | O | D | RPN | Controls (URS) | Residual risk |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(risks, key=lambda r: -r["S"] * r["O"] * r["D"]):
        lines.append(f"| {r['id']} | {r['hazard']} | {r['effect']} | {r['S']} | {r['O']} | {r['D']} | "
                     f"{r['S'] * r['O'] * r['D']} | {', '.join(r['urs'])} | {r['residual']} |")
    (VAL / "risk_assessment.md").write_text("\n".join(lines) + "\n")


def _fmt(v):
    return f"{v:.4g}" if isinstance(v, float) else str(v)


def _write_matrix(out):
    lines = ["# Traceability Matrix", "",
             f"Generated {out['generated_utc']} by `cgg validation-report` from urs.yaml, risks.yaml, "
             f"results/oq_results.json and the PQ run `{out['eval_run']}` (MLflow run `{out['mlflow_run_id']}`).",
             "", f"Summary: {out['summary']}", "",
             "| URS | Risks | OQ tests (outcome) | PQ criteria (value vs threshold) | Release | Status |",
             "|---|---|---|---|---|---|"]
    for r in out["rows"]:
        tests = "<br>".join(f"`{t['test'].split('::')[-1]}` {t['outcome']}" for t in r["oq_tests"]) or "-"
        pq = "<br>".join(f"{c['id']} {c['metric']} = {_fmt(c['value'])} ({c['op']} {c['threshold']}) "
                         f"{'pass' if c['pass'] else 'FAIL'}" for c in r["pq"]) or "-"
        lines.append(f"| {r['urs']} | {', '.join(r['risks']) or '-'} | {tests} | {pq} | {r['release'] or '-'} | "
                     f"{r['status']} |")
    (VAL / "traceability_matrix.md").write_text("\n".join(lines) + "\n")


def _write_vsr(out, oq, iq, metrics, crit, devs, decisions, pq_run):
    n_t = len(oq["tests"])
    n_pass = sum(t["outcome"] == "passed" for t in oq["tests"])
    n_skip = sum(t["outcome"] == "skipped" for t in oq["tests"])
    failed_c = [c for c in crit.values() if not c["pass"]]
    lines = [
        "# Validation Summary Report", "",
        f"Generated {out['generated_utc']} by `cgg validation-report`. All values below are read from files "
        "written by code; nothing is typed by hand.", "",
        "**Status statement.** This is a GxP-style validation exercise on a public-data demo, aligned with GAMP 5 "
        "(category 5, custom application) and CSA risk-based principles. It is not a validated system and makes "
        "no claim of regulatory compliance.", "",
        "## 1. Scope", "",
        "Drug-label question answering for medical-information and pharmacovigilance staff over a public openFDA "
        "snapshot, released as MLflow model version of system C (guarded GraphRAG).", "",
        "## 2. Installation Qualification (IQ)", "",
    ]
    if iq:
        lines += [f"- {k}: {v}" for k, v in iq.get("checks", {}).items()]
        lines.append(f"- IQ result: **{'pass' if iq.get('ok') else 'FAIL'}** (results/iq_report.json)")
    else:
        lines.append("- IQ report missing (run `python scripts/iq_check.py`).")
    lines += ["", "## 3. Operational Qualification (OQ)", "",
              f"- Automated tests with requirement markers: {n_t} collected, {n_pass} passed, {n_skip} skipped, "
              f"{n_t - n_pass - n_skip} failed (results/oq_results.json).", "",
              "## 4. Performance Qualification (PQ)", "",
              f"PQ run `{pq_run}`, MLflow run `{out['mlflow_run_id']}`, acceptance criteria frozen in "
              "config/acceptance_criteria.yaml before the run.", "",
              "| Criterion | Dimension | Metric | Value | Limit | Result |", "|---|---|---|---|---|---|"]
    for c in crit.values():
        lines.append(f"| {c['id']} | {c['dimension']} | {c['metric']} | {_fmt(c['value'])} | {c['op']} "
                     f"{c['threshold']} | {'pass' if c['pass'] else 'FAIL'} |")
    lines += ["", f"n: {metrics.get('n_normal')} normal questions, {metrics.get('n_unsafe')} unsafe questions, "
              f"{metrics.get('n_repeat')} questions x {metrics.get('n_repeat_runs')} runs for repeat agreement, "
              f"{metrics.get('n_paraphrase')} paraphrases, {metrics.get('n_typo')} typo variants, "
              f"{metrics.get('n_requests')} requests in total. Judge: deterministic comparison with gold values "
              "derived from structured fields; quotes checked by string containment.", "",
              "## 5. Traceability", "", f"{out['summary']} (traceability_matrix.md).", "",
              "## 6. Deviations", ""]
    for c in failed_c:
        lines.append(f"- PQ-{c['id']}: {c['metric']} = {_fmt(c['value'])} does not meet {c['op']} {c['threshold']}.")
    for t in oq["tests"]:
        if t["outcome"] == "failed":
            lines.append(f"- OQ failure: {t['nodeid']}")
    for d in devs:
        lines.append(f"- {d['id']}: {d['text']} Impact: {d['impact']}.")
    lines += ["", "## 7. Release decisions", ""]
    for d in decisions:
        lines.append(f"- {d['ts_utc']} version {d['version']} requested by {d['requested_by']}: "
                     f"{'RELEASED' if d['released'] else 'BLOCKED'}"
                     + (f" ({'; '.join(d['reasons'])})" if d["reasons"] else ""))
    if not decisions:
        lines.append("- none yet")
    av = audit.verify()
    lines += ["", "## 8. Audit trail", "",
              f"- audit/audit_trail.jsonl: {av['n_events']} events, hash chain "
              f"{'verified' if av['ok'] else 'BROKEN'}.", "",
              "## 9. Conclusion", "",
              ("All requirements are verified for the PQ run and no PQ criterion failed; the deviations above "
               "remain open and limit the meaning of this result to a demonstration."
               if out["summary"]["verified"] == len(out["rows"]) else
               "Not all requirements are verified; see the deviations above. The system is not fit for release "
               "on this evidence.")]
    (VAL / "validation_summary_report.md").write_text("\n".join(lines) + "\n")
