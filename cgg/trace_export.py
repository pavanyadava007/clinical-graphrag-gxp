"""Export a sample of Langfuse traces of an evaluation run (read back through the Langfuse API)."""

from __future__ import annotations

import json
import os

from cgg import config
from cgg.evaluate import load_rows


def _trunc(v, n=600):
    s = v if isinstance(v, str) else json.dumps(v, default=str)
    return s if len(s) <= n else s[:n] + " ...[truncated]"


def pick(rows: list[dict], n: int) -> list[dict]:
    """One example per outcome kind first (graph answer, text answer with citations, escalation, refusal)."""
    orig = [r for r in rows if r["variant"] == "original"]
    kinds = [
        lambda r: r["record"]["status"] == "answered" and r["record"]["route"] == "graph" and r["score"]["correct"],
        lambda r: r["record"]["status"] == "answered" and r["record"]["route"] == "text" and r["score"]["correct"],
        lambda r: r["record"]["status"] == "escalated" and r["qid"].startswith(("S", "A", "Q")),
        lambda r: r["record"]["status"] == "refused",
        lambda r: r["record"]["status"] == "escalated" and r["qid"].startswith("U"),
        lambda r: r["record"]["status"] == "answered" and not r["score"]["correct"],
    ]
    out, seen = [], set()
    for k in kinds:
        for r in orig:
            if r["qid"] not in seen and k(r):
                out.append(r)
                seen.add(r["qid"])
                break
    return out[:n]


def export(run: str, n: int = 6) -> dict:
    from langfuse import Langfuse

    lf = Langfuse(host=os.environ["LANGFUSE_HOST"], public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
                  secret_key=os.environ["LANGFUSE_SECRET_KEY"])
    traces = []
    for r in pick(load_rows(run), n):
        t = lf.fetch_trace(r["record"]["trace_id"]).data
        obs = sorted(t.observations, key=lambda o: o.start_time)
        traces.append({
            "qid": r["qid"], "trace_id": t.id, "name": t.name, "timestamp": str(t.timestamp),
            "input": t.input, "output": t.output, "latency_s": t.latency, "tags": t.tags,
            "scores": [{"name": s.name, "value": s.value, "comment": s.comment} for s in t.scores],
            "observations": [{
                "name": o.name, "type": o.type, "level": str(o.level),
                "start": str(o.start_time), "end": str(o.end_time),
                "ms": round((o.end_time - o.start_time).total_seconds() * 1000, 1) if o.end_time else None,
                "model": o.model, "usage": {"input": o.usage.input, "output": o.usage.output} if o.usage else None,
                "metadata": o.metadata,
                "input": _trunc(o.input), "output": _trunc(o.output)} for o in obs],
        })
    totals = lf.client.trace.list(limit=1)
    out = {"run": run, "langfuse": "self-hosted langfuse/langfuse:2 on 127.0.0.1 (keys not exported)",
           "total_traces_in_project": totals.meta.total_items, "sample": traces}
    p = config.RESULTS / "langfuse_sample.json"
    p.write_text(json.dumps(out, indent=1, default=str))
    return {"file": str(p.relative_to(config.ROOT)), "n": len(traces),
            "total_traces_in_project": out["total_traces_in_project"]}
