"""Generate RESULTS.md and results/summary.json from the JSON files written by the pipeline and evaluations.

Every number in RESULTS.md comes from results/*.json; nothing is typed by hand.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / "results"
RUNS = [
    ("pq-A-llama3.1-8b", "A vector RAG", "llama3.1:8b"),
    ("pq-B-llama3.1-8b", "B GraphRAG", "llama3.1:8b"),
    ("pq-C-llama3.1-8b", "C GraphRAG + guardrails + HITL", "llama3.1:8b"),
    ("pq-C-qwen2.5-7b", "C GraphRAG + guardrails + HITL", "qwen2.5:7b"),
    ("pq-C-llama3.1-8b-answer-v2", "C, answer@v2 (RCA-002 drill)", "llama3.1:8b"),
    ("pq-C-llama3.1-8b-cypher-v2", "C, text2cypher@v2 (CAPA-001)", "llama3.1:8b"),
]
README_RUNS = ["pq-A-llama3.1-8b", "pq-B-llama3.1-8b", "pq-C-llama3.1-8b", "pq-C-llama3.1-8b-cypher-v2",
               "pq-C-qwen2.5-7b"]


def _j(p: Path, default=None):
    return json.loads(p.read_text()) if p.exists() else default


def pct(v) -> str:
    return "-" if v is None else f"{100 * v:.1f} %"


def num(v, d=2) -> str:
    return "-" if v is None else f"{v:.{d}f}"


def _exp(silver: dict, action: str) -> str:
    items = [f"{k} {v['failed']}" for k, v in silver["expectations"].items() if v["failed"] and v["action"] == action]
    return ", ".join(items) or "none"


def main() -> int:
    pipe = _j(R / "pipeline_report.json", {})
    graph = _j(R / "graph_load_report.json", {})
    emb = _j(R / "embedding_report.json", {})
    gold = _j(ROOT / "eval" / "gold_manifest.json", {})
    runs = {}
    for name, label, model in RUNS:
        m = _j(R / "runs" / name / "metrics.json")
        if m:
            runs[name] = {"label": label, "model": model, "m": m}
    lines = [
        "# Results", "",
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} by `scripts/make_results.py` from "
        "`results/*.json`. Do not edit by hand. Host: NVIDIA L4 24 GB, models served by Ollama at temperature 0, "
        "seed 7. Judge: deterministic comparison with gold values derived from structured openFDA fields (no LLM "
        "judge); quotes are checked by string containment in the cited label section.", "",
        "## 1. Data pipeline (local PySpark + Delta Lake, not Databricks)", "",
    ]
    if pipe:
        s = pipe["silver"]
        g = pipe["gold"]
        lines += [
            "| Item | Value | Source |", "|---|---|---|",
            f"| Raw label records (bronze) | {pipe['bronze']['rows']} | pipeline_report.json |",
            f"| Duplicate records removed (same set_id) | {s['duplicate_records_removed']} | pipeline_report.json |",
            f"| Labels passed / quarantined | {s['labels_passed']} / {s['labels_quarantined']} | "
            "pipeline_report.json |",
            f"| Sections passed / quarantined | {s['sections_passed']} / {s['sections_quarantined']} | "
            "pipeline_report.json |",
            f"| Retrieval chunks | {g['chunks']} | pipeline_report.json |",
            f"| Graph nodes / edges | {g['kg_nodes']} / {g['kg_edges']} | pipeline_report.json |",
            f"| Neo4j snapshot hash equals gold tables | {graph.get('match')} | graph_load_report.json |",
            f"| Embeddings | {emb.get('n_chunks')} x {emb.get('dims')} ({emb.get('model')}) | embedding_report.json |",
            f"| Pipeline duration | {pipe['duration_s']} s | pipeline_report.json |", "",
            "Quarantined by expectation: " + _exp(s, "quarantine") + ". Warnings only (kept in silver): "
            + _exp(s, "warn") + ".", "",
        ]
    lines += ["## 2. Evaluation set", "",
              f"{gold.get('n_questions')} normal questions from 13 templates (gold sha256 "
              f"`{str(gold.get('sha256'))[:16]}`), 30 hand-written unsafe / out-of-scope questions, and a subset of "
              f"{gold.get('subset_size')} questions used for 2 extra repeat runs, paraphrases and typo variants.", ""]
    if runs:
        cols = [n for n, _, _ in RUNS if n in runs]
        hdr = "| Metric | n | " + " | ".join(f"{runs[c]['label']} ({runs[c]['model']})" for c in cols) + " |"
        lines += ["## 3. System comparison", "", hdr, "|" + "---|" * (len(cols) + 2)]

        def row(title, key, fmt=pct, nkey=None):
            n = runs[cols[0]]["m"].get(nkey) if nkey else ""
            vals = [fmt(runs[c]["m"].get(key)) for c in cols]
            lines.append(f"| {title} | {n} | " + " | ".join(vals) + " |")

        row("Accuracy, all normal questions (auto-released answers)", "accuracy", nkey="n_normal")
        row("Accuracy without template S3 (EPC vocabulary, see note)", "accuracy_excl_S3", nkey="n_excl_S3")
        for cat, title in (("single_fact", "single-label facts"), ("quote", "quote with citation"),
                           ("aggregate_seen", "aggregate, template in few-shot"),
                           ("aggregate_heldout", "aggregate, held-out template")):
            n = runs[cols[0]]["m"]["accuracy_by_category"].get(cat, {}).get("n")
            vals = [pct(runs[c]["m"]["accuracy_by_category"].get(cat, {}).get("acc")) for c in cols]
            lines.append(f"| - {title} | {n} | " + " | ".join(vals) + " |")
        row("Set-answer F1 (mean over answered set questions)", "set_f1_mean", fmt=lambda v: num(v, 3))
        row("Precision of auto-released answers", "precision_auto")
        row("Escalated to human review", "escalation_rate", nkey="n_normal")
        row("Silent errors (released and wrong)", "silent_error_rate", nkey="n_normal")
        row("Accuracy after review (oracle reviewer, upper bound)", "accuracy_after_review", nkey="n_normal")
        row("Citation precision (quote found in cited section)", "citation_precision")
        lines.append("| - citations checked | | " + " | ".join(str(runs[c]["m"].get("n_citations")) for c in cols)
                     + " |")
        row("Ungrounded released answers", "ungrounded_answer_rate")
        row("Repeat agreement (3 runs, T=0)", "repeat_agreement", nkey="n_repeat")
        row("Paraphrase agreement", "paraphrase_agreement", nkey="n_paraphrase")
        row("Typo accuracy drop", "typo_accuracy_drop", fmt=lambda v: "-" if v is None else f"{100 * v:.1f} pts",
            nkey="n_typo")
        row("Unsafe / out-of-scope handled (refused or escalated)", "unsafe_handled_rate", nkey="n_unsafe")
        kinds = sorted(runs[cols[0]]["m"].get("unsafe_handled_by_kind", {}))
        for k in kinds:
            n = runs[cols[0]]["m"]["unsafe_handled_by_kind"][k]["n"]
            vals = [pct(runs[c]["m"]["unsafe_handled_by_kind"].get(k, {}).get("rate")) for c in cols]
            lines.append(f"| - {k} | {n} | " + " | ".join(vals) + " |")
        row("Refused or empty answer on normal questions", "false_refusal_rate", nkey="n_normal")
        row("Error rate (all requests)", "error_rate", nkey="n_requests")
        row("Latency p50 (s)", "latency_p50_s", fmt=num)
        row("Latency p95 (s)", "latency_p95_s", fmt=num)
        row("LLM calls per request (mean)", "llm_calls_mean", fmt=num)
        lines += ["", "Accuracy by template: see `results/runs/<run>/metrics.json` (`accuracy_by_template`).", "",
                  "Note on template S3 (\"established pharmacologic class\"): the gold value is the openFDA EPC term "
                  "(for example \"Angiotensin Converting Enzyme Inhibitor\"), while label text often says \"ACE "
                  "inhibitor\", and for some combination products openFDA lists only one class. The graph systems read "
                  "the same openFDA field as the gold set, so S3 favours them; the row without S3 removes that effect.",
                  ""]

    sys.path.insert(0, str(ROOT))
    from cgg.release import evaluate_criteria

    for crit_run in ("pq-C-llama3.1-8b", "pq-C-llama3.1-8b-answer-v2", "pq-C-llama3.1-8b-cypher-v2"):
        if crit_run not in runs:
            continue
        lines += [f"## 4. PQ acceptance criteria: {runs[crit_run]['label']} (`{crit_run}`)", "",
                  "| ID | Metric | Value | Limit | Result |", "|---|---|---|---|---|"]
        for c in evaluate_criteria(runs[crit_run]["m"]):
            v = c["value"]
            lines.append(f"| {c['id']} | {c['metric']} | {num(v, 4) if isinstance(v, float) else v} | "
                         f"{c['op']} {c['threshold']} | {'pass' if c['pass'] else 'FAIL'} |")
        lines.append("")
    dec = _j(R / "release_decisions.json", [])
    if dec:
        lines += ["## 5. Release decisions", "", "| Time (UTC) | Version | Eval run | Decision | Reasons |",
                  "|---|---|---|---|---|"]
        for d in dec:
            lines.append(f"| {d['ts_utc']} | {d['version']} | {d['eval_run']} | "
                         f"{'released' if d['released'] else 'blocked'} | {'; '.join(d['reasons']) or '-'} |")
        lines.append("")
    rcas = [x for x in (_j(R / "rca_001.json"), _j(R / "rca_002.json")) if x]
    if rcas:
        lines += ["## 6. Root cause analyses", ""]
    for rca in rcas:
        rid = rca["summary"].split(":")[0]
        lines += [f"### {rid} ({rca['prompt_changed']})", "",
                  f"Baseline `{rca['baseline']}` vs candidate `{rca['candidate']}`: "
                  f"{rca['n_regressed']} questions regressed, {rca['n_improved']} improved (n = {rca['n_compared']}). "
                  f"See docs/rca/{rid}.md.", "",
                  "| Metric | Baseline | Candidate |", "|---|---|---|"]
        for k, (a, b) in rca["metric_deltas"].items():
            lines.append(f"| {k} | {num(a, 4)} | {num(b, 4)} |")
        lines.append("")
    lf = _j(R / "langfuse_sample.json")
    if lf:
        lines += ["## 7. Observability", "",
                  f"Langfuse (self-hosted v2) project held {lf['total_traces_in_project']} traces at export time; "
                  f"{len(lf['sample'])} sample traces with spans and scores are in `results/langfuse_sample.json`.", ""]
    oq = _j(R / "oq_results.json")
    tr = _j(R / "traceability.json")
    iq = _j(R / "iq_report.json")
    if oq or tr or iq:
        lines += ["## 8. Validation evidence", ""]
        if iq:
            lines.append(f"- IQ: {'pass' if iq['ok'] else 'FAIL'} ({len(iq['checks'])} checks, results/iq_report.json)")
        if oq:
            t = oq["tests"]
            lines.append(f"- OQ: {sum(x['outcome'] == 'passed' for x in t)} of {len(t)} requirement-linked tests "
                         f"passed, {sum(x['outcome'] == 'skipped' for x in t)} skipped (results/oq_results.json)")
        if tr:
            lines.append(f"- Traceability: {tr['summary']} (results/traceability.json)")
        lines.append("")
    (ROOT / "RESULTS.md").write_text("\n".join(lines) + "\n")
    _readme(runs, dec)
    summary = {"runs": {k: v for k, v in runs.items()}, "pipeline": pipe, "graph": graph, "embedding": emb,
               "gold": gold, "release_decisions": dec, "rca": rcas, "iq": iq,
               "traceability": tr["summary"] if tr else None}
    (R / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print("wrote RESULTS.md and results/summary.json")
    return 0


def _readme(runs: dict, dec: list) -> None:
    """Replace the block between the RESULTS markers in README.md with a compact generated table."""
    readme = ROOT / "README.md"
    txt = readme.read_text()
    a, b = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"
    if a not in txt or not runs:
        return
    cols = [n for n in README_RUNS if n in runs]
    out = ["Generated by `scripts/make_results.py` from `results/runs/*/metrics.json` (L4 GPU, T=0).", "",
           "| Metric | n | " + " | ".join(f"{runs[c]['label']} ({runs[c]['model']})" for c in cols) + " |",
           "|" + "---|" * (len(cols) + 2)]
    m0 = runs[cols[0]]["m"]

    def cat(c, k):
        return runs[c]["m"]["accuracy_by_category"].get(k, {}).get("acc")

    rows = [
        ("Accuracy, auto-released (all normal)", m0["n_normal"], lambda c: runs[c]["m"]["accuracy"]),
        ("- single-label facts", m0["accuracy_by_category"]["single_fact"]["n"], lambda c: cat(c, "single_fact")),
        ("- quote with verified citation", m0["accuracy_by_category"]["quote"]["n"], lambda c: cat(c, "quote")),
        ("- aggregate (few-shot templates)", m0["accuracy_by_category"]["aggregate_seen"]["n"],
         lambda c: cat(c, "aggregate_seen")),
        ("- aggregate (held-out templates)", m0["accuracy_by_category"]["aggregate_heldout"]["n"],
         lambda c: cat(c, "aggregate_heldout")),
        ("Silent errors (released and wrong)", m0["n_normal"], lambda c: runs[c]["m"]["silent_error_rate"]),
        ("Escalated to review", m0["n_normal"], lambda c: runs[c]["m"]["escalation_rate"]),
        ("Citation precision", "all", lambda c: runs[c]["m"]["citation_precision"]),
        ("Unsafe handled", m0["n_unsafe"], lambda c: runs[c]["m"]["unsafe_handled_rate"]),
        ("Refused or empty answer (normal)", m0["n_normal"], lambda c: runs[c]["m"]["false_refusal_rate"]),
    ]
    for title, n, f in rows:
        out.append(f"| {title} | {n} | " + " | ".join(pct(f(c)) for c in cols) + " |")
    out.append("| Latency p95 (s) | all | " + " | ".join(num(runs[c]["m"]["latency_p95_s"]) for c in cols) + " |")
    if dec:
        out += ["", "Release decisions: " + "; ".join(
            f"v{d['version']} ({d['eval_run']}) {'released' if d['released'] else 'blocked'}" for d in dec) + "."]
    i, j = txt.index(a) + len(a), txt.index(b)
    readme.write_text(txt[:i] + "\n" + "\n".join(out) + "\n" + txt[j:])


if __name__ == "__main__":
    sys.exit(main())
