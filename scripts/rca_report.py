"""RCA evidence: compare a baseline PQ run with a candidate run, question by question.

    python scripts/rca_report.py RCA-001 pq-C-llama3.1-8b pq-C-llama3.1-8b-cypher-v2 text2cypher
    python scripts/rca_report.py RCA-002 pq-C-llama3.1-8b pq-C-llama3.1-8b-answer-v2 answer

Writes results/<id>.json and docs/rca/<ID>.md. The narrative (symptom, 5 whys, CAPA) lives in
docs/rca/<id>_narrative.md and is merged in; every number comes from the runs and Langfuse.
"""

from __future__ import annotations

import collections
import difflib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

KEYS = ["accuracy", "precision_auto", "escalation_rate", "silent_error_rate", "citation_precision",
        "ungrounded_answer_rate", "unsafe_handled_rate", "false_refusal_rate", "latency_p50_s", "latency_p95_s",
        "tokens_mean"]


def load(run):
    rows = {}
    for ln in (ROOT / "results" / "runs" / run / "answers.jsonl").read_text().splitlines():
        if ln.strip():
            d = json.loads(ln)
            if d["variant"] == "original":
                rows[d["qid"]] = d
    return rows


def lf_obs(trace_id: str) -> dict:
    """Pull the citation-check span and the generation output of one trace from Langfuse."""
    try:
        from langfuse import Langfuse

        lf = Langfuse(host=os.environ["LANGFUSE_HOST"], public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
                      secret_key=os.environ["LANGFUSE_SECRET_KEY"])
        t = lf.fetch_trace(trace_id).data
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}
    out = {"trace_id": trace_id, "observations": []}
    for o in sorted(t.observations, key=lambda o: o.start_time):
        if o.name in ("generate", "guard_citations"):
            out["observations"].append({"name": o.name, "prompt_version": (o.metadata or {}).get("prompt_version"),
                                        "output": o.output if o.name == "guard_citations" else str(o.output)[:500]})
    return out


def failure_category(rec: dict) -> str:
    """Coarse, rule-based category of a wrong or unreleased answer (used to rank root-cause candidates)."""
    import re

    st, cy, reason = rec["status"], rec.get("cypher") or "", rec.get("reason") or ""
    if st == "refused":
        return "normal question refused by the safety policy"
    if st == "escalated" and "resolves to" in reason:
        return "escalated: named label ambiguous or not found"
    if st == "escalated" and "graph query" in reason:
        return "escalated: graph query failed or empty after repair"
    if st == "escalated" and "verified" in reason:
        return "escalated: citation could not be verified"
    if st == "escalated":
        return "escalated: other"
    if re.search(r"(generic_name|brand_name)\s*=\s*'[^']*'\s+OR\s", cy, flags=re.I):
        return "released wrong: name split into OR conditions"
    if rec.get("route") == "graph":
        return "released wrong: other graph query error"
    return "released wrong: text answer"


def main() -> int:
    rid, BASE, CAND, prompt_name = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    from cgg import config  # noqa: F401  (loads infra/.env for Langfuse keys)
    from cgg.promptlib import load as load_prompt
    from cgg.release import evaluate_criteria

    mb = json.loads((ROOT / "results" / "runs" / BASE / "metrics.json").read_text())
    mc = json.loads((ROOT / "results" / "runs" / CAND / "metrics.json").read_text())
    b, c = load(BASE), load(CAND)
    common = sorted(set(b) & set(c))
    regressed = [q for q in common if b[q]["score"]["correct"] and not c[q]["score"]["correct"]]
    improved = [q for q in common if not b[q]["score"]["correct"] and c[q]["score"]["correct"]]
    by_t = collections.Counter(q.split("-")[0] for q in regressed)
    by_route = collections.Counter(str(c[q]["record"]["route"]) for q in regressed)
    by_status = collections.Counter(c[q]["record"]["status"] for q in regressed)
    reasons = collections.Counter()
    for q in common:
        chk = c[q]["record"]["checks"].get("citation_check")
        if chk:
            reasons.update(chk["reasons"])
    reasons_b = collections.Counter()
    for q in common:
        chk = b[q]["record"]["checks"].get("citation_check")
        if chk:
            reasons_b.update(chk["reasons"])
    text_q = [q for q in common if c[q]["record"]["route"] == "text"]
    graph_q = [q for q in common if c[q]["record"]["route"] == "graph"]
    v1 = int(mb["params"][f"prompt.{prompt_name}"].split("@v")[1])
    v2 = int(mc["params"][f"prompt.{prompt_name}"].split("@v")[1])
    p1, p2 = load_prompt(prompt_name, v1), load_prompt(prompt_name, v2)
    diff = list(difflib.unified_diff(p1.system.splitlines(), p2.system.splitlines(), p1.ref, p2.ref,
                                     lineterm="", n=0))
    from cgg.evalset import load_gold
    from cgg.metrics import score as _score

    gq = {x["qid"]: x for x in load_gold()}
    cats_b = collections.Counter(failure_category(b[q]["record"]) for q in common
                                 if q in gq and not _score(gq[q], b[q]["record"])["correct"])
    cats_c = collections.Counter(failure_category(c[q]["record"]) for q in common
                                 if q in gq and not _score(gq[q], c[q]["record"])["correct"])
    examples = []
    for q in regressed[:2]:
        examples.append({"qid": q, "question": c[q]["question"],
                         "baseline": lf_obs(b[q]["record"]["trace_id"]),
                         "candidate": lf_obs(c[q]["record"]["trace_id"])})
    crit_b = {x["id"]: x["pass"] for x in evaluate_criteria(mb)}
    crit_c = {x["id"]: (x["pass"], x["metric"], x["value"]) for x in evaluate_criteria(mc)}
    failed_c = [f"{k} {m} = {v:.4g}" for k, (ok, m, v) in crit_c.items() if not ok and v is not None]
    out = {
        "baseline": BASE, "candidate": CAND, "n_compared": len(common),
        "n_regressed": len(regressed), "n_improved": len(improved),
        "regressed_qids": regressed, "improved_qids": improved,
        "regressed_by_template": dict(by_t), "regressed_by_route": dict(by_route),
        "regressed_by_status": dict(by_status),
        "citation_check_reasons_candidate": dict(reasons), "citation_check_reasons_baseline": dict(reasons_b),
        "n_text_route": len(text_q), "n_graph_route": len(graph_q),
        "graph_route_regressions": sum(1 for q in regressed if c[q]["record"]["route"] == "graph"),
        "metric_deltas": {k: [mb.get(k), mc.get(k)] for k in KEYS},
        "criteria_failed_candidate": failed_c,
        "criteria_failed_baseline": [k for k, ok in crit_b.items() if not ok],
        "prompt_diff": diff, "langfuse_examples": examples,
        "failure_categories_baseline": dict(cats_b.most_common()),
        "failure_categories_candidate": dict(cats_c.most_common()),
        "prompt_changed": f"{p1.ref} -> {p2.ref}",
    }
    out["summary"] = (f"{rid}: {p2.ref} vs {p1.ref} on {len(common)} questions: {len(regressed)} "
                      f"regressed, {len(improved)} improved. Failing criteria for the candidate: "
                      f"{', '.join(failed_c) or 'none'}.")
    (ROOT / "results" / f"{rid.lower().replace('-', '_')}.json").write_text(json.dumps(out, indent=1, default=str))
    narrative = (ROOT / "docs" / "rca" / f"{rid.lower().replace('-', '_')}_narrative.md")
    text = narrative.read_text() if narrative.exists() else "(narrative not written yet)\n"
    md = [text.rstrip(), "", f"## Evidence (generated by scripts/rca_report.py, {BASE} vs {CAND})", "",
          f"| Metric | Baseline {p1.ref} | Candidate {p2.ref} |", "|---|---|---|"]
    for k, (x, y) in out["metric_deltas"].items():
        md.append(f"| {k} | {x if x is None else round(x, 4)} | {y if y is None else round(y, 4)} |")
    md += ["", f"- Questions compared: {len(common)}; regressed {len(regressed)}, improved {len(improved)}.",
           f"- Regressions by template: {dict(by_t)}; by route: {dict(by_route)}; by final status: {dict(by_status)}.",
           f"- Citation-check failure reasons, candidate: {dict(reasons)}; baseline: {dict(reasons_b)}.",
           f"- Graph-route regressions: {out['graph_route_regressions']}.",
           f"- Failure categories (wrong or unreleased normal questions), baseline: {dict(cats_b.most_common())}.",
           f"- Failure categories, candidate: {dict(cats_c.most_common())}.",
           f"- Acceptance criteria failed by the candidate: {', '.join(failed_c) or 'none'}; by the baseline: "
           f"{', '.join(out['criteria_failed_baseline']) or 'none'}.", "",
           "Prompt diff (system message):", "", "```diff", *diff, "```", "",
           "Langfuse trace excerpts for the first regressed questions (citation-check span output):", ""]
    for e in examples:
        md.append(f"- `{e['qid']}` {e['question']}")
        for side in ("baseline", "candidate"):
            obs = [o for o in e[side].get("observations", []) if o["name"] == "guard_citations"]
            last = obs[-1]["output"] if obs else e[side].get("error", "no citation span")
            md.append(f"  - {side} trace `{e[side].get('trace_id', '-')}`: {json.dumps(last)[:300]}")
    (ROOT / "docs" / "rca" / f"{rid}.md").write_text("\n".join(md) + "\n")
    print(out["summary"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
