"""Run one system over the gold + safety sets and the consistency / paraphrase / typo subsets.

Answers are appended to results/runs/<run>/answers.jsonl as they arrive, so an interrupted run resumes
where it stopped. Scores are pushed to the Langfuse trace of each answer.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from cgg import audit, config
from cgg.evalset import load_gold, load_safety
from cgg.hitl import ReviewQueue
from cgg.metrics import score, summarize
from cgg.systems.base import SystemConfig
from cgg.systems.qa import SYSTEMS
from cgg.tracing import Tracer

RUNS = config.RESULTS / "runs"
ORACLE = "oracle-reviewer"


def _key(qid: str, variant: str) -> str:
    return f"{qid}|{variant}"


def run_eval(system: str, run_name: str, cfg: SystemConfig | None = None, repeats: int = 2,
             variants: bool = True, tracer: Tracer | None = None, limit: int | None = None) -> dict:
    cfg = cfg or SystemConfig()
    out_dir = RUNS / run_name
    out_dir.mkdir(parents=True, exist_ok=True)
    ans_file = out_dir / "answers.jsonl"
    done = {}
    if ans_file.exists():
        for ln in ans_file.read_text().splitlines():
            if ln.strip():
                d = json.loads(ln)
                done[_key(d["qid"], d["variant"])] = d
    tracer = tracer or Tracer()
    queue = ReviewQueue(run_id=run_name) if system == "C" else None
    sys_obj = SYSTEMS[system](cfg, tracer, queue=queue) if system == "C" else SYSTEMS[system](cfg, tracer)
    gold = load_gold()
    safety = load_safety()
    items = gold + safety
    if limit:
        items = gold[: limit] + safety[: max(1, limit // 6)]
    plan = [(q, "original", q["question"]) for q in items]
    if variants:
        subset = [q for q in items if q.get("in_subset")]
        for i in range(1, repeats + 1):
            plan += [(q, f"repeat{i}", q["question"]) for q in subset]
        plan += [(q, "paraphrase", q["paraphrase"]) for q in subset]
        plan += [(q, "typo", q["typo"]) for q in subset]
    meta_run = {"run": run_name, "system": sys_obj.name, "started_utc": datetime.now(timezone.utc).isoformat(),
                "params": cfg.as_params(), "tracing_backend": tracer.backend, "n_planned": len(plan)}
    (out_dir / "run_meta.json").write_text(json.dumps(meta_run, indent=1))
    # warm-up (model load into GPU memory) so the first measured latency is not a cold start
    sys_obj.caller.llm.chat("You reply OK.", "ping", max_tokens=2)
    from cgg.llm import embed

    embed(["warm-up"], prefix="search_query: ")
    t0 = time.time()
    with open(ans_file, "a") as f:
        for i, (q, variant, text) in enumerate(plan, 1):
            k = _key(q["qid"], variant)
            if k in done:
                continue
            # only the original pass feeds the human review queue
            if queue is not None:
                sys_obj.queue = queue if variant == "original" else None
            r = sys_obj.ask(text, meta={"qid": q["qid"], "variant": variant, "run": run_name})
            rec = r.to_dict()
            s = score(q, rec)
            tracer.score(r.trace_id, "correct", float(s["correct"]), comment=f"{q['qid']} {variant}")
            if rec.get("citations"):
                from cgg.guards import check_citations

                chk = check_citations(rec["citations"])
                tracer.score(r.trace_id, "citation_precision", chk["n_valid"] / max(1, chk["n"]))
            row = {"qid": q["qid"], "variant": variant, "question": text, "record": rec, "score": s}
            f.write(json.dumps(row, default=str) + "\n")
            f.flush()
            done[k] = row
            if i % 20 == 0:
                print(f"[{run_name}] {i}/{len(plan)} {time.time() - t0:.0f}s", flush=True)
    tracer.flush()
    reviewed = oracle_review(run_name, {q["qid"]: q for q in items}) if queue is not None else None
    metrics = compute(run_name, items, reviewed)
    audit.append("eval.run", f"eval/{run_name}", {"system": sys_obj.name, "params": cfg.as_params(),
                                                  "n_requests": metrics["n_requests"]}, actor="pavan.dev")
    return metrics


def oracle_review(run_name: str, qmap: dict) -> dict:
    """Automated stand-in for a medical reviewer: decides each pending item of this run from the gold set.
    This is an upper bound for what a careful human reviewer would achieve, and is reported as such."""
    queue = ReviewQueue(run_id=run_name)
    out: dict = {}
    counts = {"approved": 0, "edited": 0, "rejected": 0}
    for item in queue.pending():
        if item["run_id"] != run_name:
            continue
        q = qmap.get(item["qid"])
        if q is None:
            continue
        if q["answer_type"] == "refuse":
            queue.decide(item["id"], "reject", "not a label question; referred to medical information", ORACLE)
            out[q["qid"]] = {"decision": "rejected", "final_correct": True}
            counts["rejected"] += 1
            continue
        proposed = {"status": "answered", "answer": json.loads(item["proposed_answer"] or "null"),
                    "citations": json.loads(item["citations"] or "[]")}
        if score(q, proposed)["correct"]:
            queue.decide(item["id"], "approve", "proposed answer matches the label data", ORACLE)
            out[q["qid"]] = {"decision": "approved", "final_correct": True}
            counts["approved"] += 1
        else:
            queue.decide(item["id"], "edit", "corrected from the label data", ORACLE, final_answer=q["gold"])
            out[q["qid"]] = {"decision": "edited", "final_correct": True}
            counts["edited"] += 1
    # include decisions made in an earlier (interrupted) invocation
    for item in queue._rows("SELECT * FROM reviews WHERE run_id=? AND status!='pending'", (run_name,)):
        if item["qid"] not in out and item["qid"] in qmap:
            out[item["qid"]] = {"decision": item["status"], "final_correct": True}
            counts[item["status"]] = counts.get(item["status"], 0) + 1
    out["_counts"] = counts
    (RUNS / run_name / "reviews.json").write_text(json.dumps(out, indent=1))
    return out


def load_rows(run_name: str) -> list[dict]:
    p = RUNS / run_name / "answers.jsonl"
    rows = {}
    for ln in p.read_text().splitlines():
        if ln.strip():
            d = json.loads(ln)
            rows[_key(d["qid"], d["variant"])] = d
    return list(rows.values())


def compute(run_name: str, items: list[dict] | None = None, reviewed: dict | None = None) -> dict:
    items = items or (load_gold() + load_safety())
    qmap = {q["qid"]: q for q in items}
    rows = load_rows(run_name)
    if reviewed is None and (RUNS / run_name / "reviews.json").exists():
        reviewed = json.loads((RUNS / run_name / "reviews.json").read_text())

    def pack(variant):
        return [{"q": qmap[r["qid"]], "r": r["record"], "s": score(qmap[r["qid"]], r["record"])}
                for r in rows if r["variant"] == variant and r["qid"] in qmap]

    main = pack("original")
    reps = [pack(v) for v in sorted({r["variant"] for r in rows if r["variant"].startswith("repeat")})]
    m = summarize(main, reps or None, pack("paraphrase") or None, pack("typo") or None, reviewed)
    meta = json.loads((RUNS / run_name / "run_meta.json").read_text())
    m["run"] = run_name
    m["system"] = meta["system"]
    m["params"] = meta["params"]
    m["tracing_backend"] = meta["tracing_backend"]
    Path(RUNS / run_name / "metrics.json").write_text(json.dumps(m, indent=1))
    return m
