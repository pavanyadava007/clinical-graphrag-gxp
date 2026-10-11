"""Development-set check for a prompt change (never the gold set).

    python scripts/dev_check.py --name cypher-v2 --cypher-prompt 2 [--templates S1,S2,...]

Runs system C once over eval/dev_set.jsonl (different seed, gold questions removed) and writes
results/dev/<name>.json with accuracy per template. Used before spending a PQ run on a candidate.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from cgg.metrics import score
    from cgg.systems.base import SystemConfig
    from cgg.systems.qa import SYSTEMS
    from cgg.tracing import Tracer

    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--system", default="C")
    ap.add_argument("--cypher-prompt", type=int, default=1)
    ap.add_argument("--answer-prompt", type=int, default=1)
    ap.add_argument("--templates", default="S1,S2,S3,S4,A1,A2,A3,A4,A5,A6")
    a = ap.parse_args()
    cfg = SystemConfig()
    cfg.prompts["text2cypher"] = a.cypher_prompt
    cfg.prompts["answer"] = a.answer_prompt
    s = SYSTEMS[a.system](cfg, Tracer(enabled=False))
    keep = set(a.templates.split(","))
    dev = [json.loads(ln) for ln in (ROOT / "eval" / "dev_set.jsonl").read_text().splitlines() if ln.strip()]
    dev = [q for q in dev if q["template"] in keep]
    by_t: dict = collections.defaultdict(list)
    status = collections.Counter()
    for q in dev:
        r = s.ask(q["question"]).to_dict()
        by_t[q["template"]].append(score(q, r)["correct"])
        status[r["status"]] += 1
    out = {"name": a.name, "system": a.system, "params": cfg.as_params(), "n": len(dev),
           "accuracy": round(sum(sum(v) for v in by_t.values()) / len(dev), 4),
           "by_template": {k: {"acc": round(sum(v) / len(v), 4), "n": len(v)} for k, v in sorted(by_t.items())},
           "status": dict(status), "set": "eval/dev_set.jsonl"}
    d = ROOT / "results" / "dev"
    d.mkdir(exist_ok=True)
    (d / f"{a.name}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
