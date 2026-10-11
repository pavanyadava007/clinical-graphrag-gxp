#!/usr/bin/env bash
# CAPA-001: dev-set check of text2cypher@v2 against v1, then the PQ run of the CAPA candidate.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
export CGG_USER=${CGG_USER:-pavan.dev}
$PY scripts/dev_check.py --name C-cypher-v1 --cypher-prompt 1
$PY scripts/dev_check.py --name C-cypher-v2 --cypher-prompt 2
$PY -m cgg.cli eval --system C --cypher-prompt 2 --run pq-C-llama3.1-8b-cypher-v2 --no-log-mlflow
