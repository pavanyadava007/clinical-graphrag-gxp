#!/usr/bin/env bash
# Lifecycle after the PQ runs: MLflow logging, registration, approvals (incl. a refused self-approval),
# OQ evidence, traceability, release of the baseline and the blocked RCA-001 candidate, trace export, reports.
set -uo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
CGG="$PY -m cgg.cli"
export CGG_USER=pavan.dev
for r in pq-A-llama3.1-8b pq-B-llama3.1-8b pq-C-llama3.1-8b pq-C-qwen2.5-7b pq-C-llama3.1-8b-answer-v2; do
  [ -f "results/runs/$r/mlflow_run_id.txt" ] || $CGG log-run "$r"
done
$CGG register --run pq-C-llama3.1-8b --as pavan.dev                  # -> version 1, alias candidate
$CGG approve 1 --as pavan.dev || echo "expected: developer cannot approve"
$CGG approve 1 --as qa.approver --meaning "PQ evidence reviewed; approved for production release"
$PY scripts/iq_check.py > /dev/null
CGG_OQ_RECORD=1 $PY -m pytest -q -p no:warnings
$CGG validation-report
$CGG release 1 --as release.manager
$CGG register --run pq-C-llama3.1-8b-answer-v2 --as pavan.dev        # -> version 2 (RCA-001 candidate)
$CGG approve 2 --as qa.approver --meaning "approved for production release, pending PQ gate"
$CGG release 2 --as release.manager || echo "expected: release of version 2 blocked"
$CGG trace-export pq-C-llama3.1-8b
$PY scripts/rca_001.py
$CGG validation-report
$CGG audit verify
$PY scripts/make_results.py
