"""`cgg` command line: pipeline, QA, evaluation, review, registry, approvals, release and validation."""

from __future__ import annotations

import json
import sys

import typer

app = typer.Typer(add_completion=False, no_args_is_help=True, help="clinical-graphrag-gxp")
review_app = typer.Typer(no_args_is_help=True, help="human review queue")
audit_app = typer.Typer(no_args_is_help=True, help="audit trail")
app.add_typer(review_app, name="review")
app.add_typer(audit_app, name="audit")


def _print(d) -> None:
    typer.echo(json.dumps(d, indent=1, default=str))


@app.command()
def fetch():
    """Download the openFDA label snapshot (writes data/raw + data/manifest/fetch_manifest.json)."""
    from cgg import audit
    from cgg.fetch import fetch as _fetch

    m = _fetch()
    audit.append("data.fetch", "openfda/drug-label", {"n_files": m["n_files"], "n_labels": m["n_label_records"]})


@app.command()
def ingest():
    """Run the PySpark + Delta medallion pipeline and export the serving snapshot."""
    from cgg import audit
    from cgg.pipeline.medallion import export_serving, run

    user = audit.require("ingest")
    r = run()
    r["serving"] = export_serving()
    audit.append("data.ingest", "delta/medallion", {"ingest_run_id": r["ingest_run_id"],
                                                     "delta_versions": r["delta_versions"],
                                                     "kg_snapshot_sha256": r["gold"]["kg_snapshot_sha256"]}, user)
    _print({k: r[k] for k in ("ingest_run_id", "delta_versions", "duration_s")})


@app.command("build-graph")
def build_graph():
    """Load gold.kg_nodes / gold.kg_edges into Neo4j (idempotent) and compare snapshot hashes."""
    from cgg import audit
    from cgg.graph.store import load_from_gold

    r = load_from_gold()
    audit.append("graph.load", "neo4j", {"snapshot_sha256": r["neo4j_snapshot_sha256"], "match": r["match"]})
    _print(r)
    if not r["match"]:
        raise typer.Exit(1)


@app.command()
def embed():
    """Embed gold.chunks with nomic-embed-text."""
    from cgg.embed import build

    _print(build())


@app.command()
def gold():
    """Regenerate the deterministic gold set from the serving snapshot."""
    from cgg.evalset import build, write

    _print(write(build()))


@app.command()
def ask(question: str, system: str = typer.Option("C", help="A, B or C"),
        model: str = typer.Option(None, help="Ollama model"), answer_prompt: int = 1):
    """Ask one question and print the answer with citations, route, Cypher and trace id."""
    from cgg.systems.base import SystemConfig
    from cgg.systems.qa import SYSTEMS
    from cgg.tracing import Tracer

    cfg = SystemConfig()
    if model:
        cfg.model = model
    cfg.prompts["answer"] = answer_prompt
    tracer = Tracer()
    r = SYSTEMS[system](cfg, tracer).ask(question)
    tracer.flush()
    d = r.to_dict()
    d.pop("spans")
    d["rows"] = (d["rows"] or [])[:10] if d["rows"] is not None else None
    d["tracing_backend"] = tracer.backend
    _print(d)


@app.command("eval")
def eval_(system: str = typer.Option(..., help="A, B or C"), run: str = typer.Option(..., help="run name"),
          model: str = typer.Option(None), answer_prompt: int = 1, repeats: int = 2, variants: bool = True,
          limit: int = typer.Option(None, help="smoke test on the first N gold questions"),
          log_mlflow: bool = True):
    """Evaluate a system on the gold + safety sets (resumable) and log the run to MLflow."""
    from cgg.evaluate import run_eval
    from cgg.systems.base import SystemConfig

    cfg = SystemConfig()
    if model:
        cfg.model = model
    cfg.prompts["answer"] = answer_prompt
    m = run_eval(system, run, cfg, repeats=repeats, variants=variants, limit=limit)
    if log_mlflow:
        from cgg.tracking import log_eval_run

        m["mlflow_run_id"] = log_eval_run(run)
    _print({k: v for k, v in m.items() if not isinstance(v, dict)})


@app.command()
def metrics(run: str):
    """Recompute metrics for a finished run from its answers.jsonl."""
    from cgg.evaluate import compute

    _print(compute(run))


@review_app.command("list")
def review_list():
    from cgg.hitl import ReviewQueue

    for it in ReviewQueue().pending():
        typer.echo(f"#{it['id']} [{it['qid']}] {it['question']}\n   reason: {it['escalation_reason']}\n"
                   f"   proposed: {it['proposed_answer']}")


@review_app.command("decide")
def review_decide(review_id: int, decision: str = typer.Argument(..., help="approve | reject | edit"),
                  reason: str = typer.Option(..., help="required justification"),
                  answer: str = typer.Option(None, help="final answer for edit (JSON or text)"),
                  as_user: str = typer.Option(None, "--as", help="reviewer identity (else CGG_USER)")):
    from cgg.hitl import ReviewQueue

    final = None
    if answer is not None:
        try:
            final = json.loads(answer)
        except json.JSONDecodeError:
            final = answer
    _print(ReviewQueue().decide(review_id, decision, reason, as_user, final))


@app.command()
def register(run: str = typer.Option(..., help="evaluation run backing this version"),
             as_user: str = typer.Option(None, "--as")):
    """Register system C as a new model version (models-from-code) with full lineage; alias 'candidate'."""
    from cgg.tracking import register_model

    _print(register_model(run, as_user))


@app.command()
def approve(version: int, meaning: str = typer.Option("approved for production release"),
            as_user: str = typer.Option(None, "--as")):
    """Record a QA approval (e-signature style) on a model version. Author cannot approve."""
    from cgg.release import approve as _approve

    _print(_approve(version, meaning, as_user))


@app.command()
def release(version: int, as_user: str = typer.Option(None, "--as"), dry_run: bool = False):
    """Promote a model version to 'production' only if every release gate passes."""
    from cgg.release import release as _release

    r = _release(version, as_user, dry_run=dry_run)
    _print(r)
    if not r["released"]:
        raise typer.Exit(2)


@audit_app.command("verify")
def audit_verify():
    from cgg import audit

    r = audit.verify()
    _print(r)
    if not r["ok"]:
        raise typer.Exit(1)


@app.command("trace-export")
def trace_export(run: str, n: int = 6):
    """Export a sample of Langfuse traces (with observations and scores) of a run to results/."""
    from cgg.trace_export import export

    _print(export(run, n))


@app.command("validation-report")
def validation_report():
    """Generate traceability matrix + validation summary report from code, tests and results."""
    from cgg.validation.report import generate

    _print(generate())


@app.command("register-prompts")
def register_prompts():
    from cgg.tracking import register_prompts as _rp

    _print(_rp())


def main():  # pragma: no cover
    sys.exit(app())


if __name__ == "__main__":
    app()
