#!/usr/bin/env bash
# Lifecycle steps after the PQ runs, in the order they were executed for this repository:
#  v1 baseline (blocked by the gate), v2 answer-prompt change (RCA-002 drill, blocked),
#  v3 CAPA-001 candidate from RCA-001 (gate decides). Approvals include a refused self-approval.
set -uo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
CGG="$PY -m cgg.cli"
export CGG_USER=pavan.dev
for r in pq-A-llama3.1-8b pq-B-llama3.1-8b pq-C-llama3.1-8b pq-C-qwen2.5-7b pq-C-llama3.1-8b-answer-v2 \
         pq-C-llama3.1-8b-cypher-v2; do
  [ -f "results/runs/$r/mlflow_run_id.txt" ] || $CGG log-run "$r"
done
# v1: baseline
$CGG register --run pq-C-llama3.1-8b --as pavan.dev
$CGG approve 1 --as pavan.dev || echo "expected: a developer cannot approve"
$CGG approve 1 --as qa.approver --meaning "PQ evidence reviewed; approved for production release subject to the release gate"
$PY scripts/iq_check.py > /dev/null
CGG_OQ_RECORD=1 $PY -m pytest -q -p no:warnings
$CGG validation-report --pq-run pq-C-llama3.1-8b
$CGG release 1 --as release.manager || echo "blocked"
$CGG trace-export pq-C-llama3.1-8b
# v2: answer prompt change (RCA-002 drill)
$CGG register --run pq-C-llama3.1-8b-answer-v2 --as pavan.dev
$CGG approve 2 --as qa.approver --meaning "approved for production release subject to the release gate"
$CGG release 2 --as release.manager || echo "blocked"
# v3: CAPA-001 candidate
$CGG register --run pq-C-llama3.1-8b-cypher-v2 --as pavan.dev
$CGG approve 3 --as qa.approver --meaning "CAPA-001 evidence reviewed; approved subject to the release gate"
CGG_OQ_RECORD=1 $PY -m pytest -q -p no:warnings
$CGG validation-report --pq-run pq-C-llama3.1-8b-cypher-v2
$CGG release 3 --as release.manager || echo "blocked"
$PY scripts/rca_report.py RCA-001 pq-C-llama3.1-8b pq-C-llama3.1-8b-cypher-v2 text2cypher
$PY scripts/rca_report.py RCA-002 pq-C-llama3.1-8b pq-C-llama3.1-8b-answer-v2 answer
$CGG validation-report --pq-run pq-C-llama3.1-8b-cypher-v2
$CGG audit verify
$PY scripts/make_results.py
