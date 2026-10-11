"""Build the static Hugging Face Space in site/ and (only with --upload) publish it.

    python scripts/publish_hf.py            # build site/ from results/
    python scripts/publish_hf.py --upload   # build, then upload to spaces/pavanyadava07/clinical-graphrag-gxp

Everything on the page is read from results/*.json and docs/ written by the code; nothing is typed by hand
except headings and explanations.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
SPACE_ID = "pavanyadava07/clinical-graphrag-gxp"
REPO = "https://github.com/pavanyadava007/clinical-graphrag-gxp"
RELEASED = "pq-C-llama3.1-8b-cypher-v2"  # eval run of the released model version

SPACE_README = """---
title: Clinical GraphRAG GxP
emoji: "\\U0001F48A"
colorFrom: blue
colorTo: gray
sdk: static
pinned: false
license: mit
short_description: Drug-label GraphRAG with guardrails, HITL and GxP evidence
---

Static results page of https://github.com/pavanyadava007/clinical-graphrag-gxp.
All numbers come from results/*.json written by the evaluation code (NVIDIA L4, local models, T=0).
Public openFDA data. GxP-style demo, not a validated system. Not run on Databricks.
"""


def _j(p: Path, default=None):
    return json.loads(p.read_text()) if p.exists() else default


def examples(run: str, n_per: int = 2) -> list[dict]:
    """Real answers of system C from the PQ run, one or two per outcome kind, with question and evidence."""
    rows = [json.loads(ln) for ln in (ROOT / "results" / "runs" / run / "answers.jsonl").read_text().splitlines()
            if ln.strip()]
    gold = {json.loads(ln)["qid"]: json.loads(ln) for ln in (ROOT / "eval" / "gold_set.jsonl").read_text()
            .splitlines() if ln.strip()}
    rows = [r for r in rows if r["variant"] == "original"]
    picks: list[dict] = []
    kinds = [
        ("graph answer", lambda r: r["record"]["route"] == "graph" and r["record"]["status"] == "answered"
         and r["qid"].startswith("A") and r["score"]["correct"]),
        ("verified quote", lambda r: r["record"]["route"] == "text" and r["record"]["status"] == "answered"
         and r["score"]["correct"]),
        ("escalated to review", lambda r: r["record"]["status"] == "escalated" and not r["qid"].startswith("U")),
        ("refused", lambda r: r["record"]["status"] == "refused"),
        ("released but wrong", lambda r: r["record"]["status"] == "answered" and not r["score"]["correct"]
         and not r["qid"].startswith("U")),
    ]
    for kind, f in kinds:
        for r in [x for x in rows if f(x)][:n_per]:
            rec = r["record"]
            g = gold.get(r["qid"], {})
            picks.append({
                "kind": kind, "qid": r["qid"], "question": r["question"], "status": rec["status"],
                "route": rec["route"], "answer": rec["answer"], "gold": g.get("gold"),
                "citations": [{k: c.get(k) for k in ("set_id", "section", "quote")} for c in rec["citations"][:2]],
                "cypher": rec["cypher"], "reason": rec["reason"], "latency_s": rec["latency_s"],
                "trace_id": rec["trace_id"], "spans": [{"name": s["name"], "ms": s["ms"]} for s in rec["spans"]],
                "correct": r["score"]["correct"]})
    return picks


def build() -> None:
    R = ROOT / "results"
    summary = _j(R / "summary.json")
    if not summary:
        raise SystemExit("run scripts/make_results.py first")
    data = {
        "summary": summary,
        "traceability": _j(R / "traceability.json"),
        "langfuse": _j(R / "langfuse_sample.json"),
        "examples": examples(RELEASED) if (R / "runs" / RELEASED).exists() else [],
        "criteria": None,
        "repo": REPO,
    }
    sys.path.insert(0, str(ROOT))
    from cgg.release import evaluate_criteria

    data["criteria"] = [{"run": r, "label": summary["runs"][r]["label"], "criteria": evaluate_criteria(
        summary["runs"][r]["m"])} for r in ("pq-C-llama3.1-8b", RELEASED) if r in summary["runs"]]
    shutil.rmtree(SITE, ignore_errors=True)
    SITE.mkdir()
    (SITE / "README.md").write_text(SPACE_README)
    html = (ROOT / "scripts" / "space_template.html").read_text()
    blob = json.dumps(data, default=str).replace("</", "<\\/")
    (SITE / "index.html").write_text(html.replace("/*__DATA__*/null", blob))
    for f in ("demo.mp4", "demo.webm"):
        if (ROOT / "docs" / f).exists():
            shutil.copy(ROOT / "docs" / f, SITE / f)
    print(f"built {SITE}")


def upload() -> None:
    from huggingface_hub import HfApi

    api = HfApi()
    api.create_repo(SPACE_ID, repo_type="space", space_sdk="static", exist_ok=True)
    api.upload_folder(folder_path=str(SITE), repo_id=SPACE_ID, repo_type="space",
                      commit_message="Update clinical-graphrag-gxp results page")
    print(f"uploaded to https://huggingface.co/spaces/{SPACE_ID}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upload", action="store_true")
    args = ap.parse_args()
    build()
    if args.upload:
        upload()
    return 0


if __name__ == "__main__":
    sys.exit(main())
