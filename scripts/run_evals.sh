#!/usr/bin/env bash
# PQ evaluation runs (resumable). Needs Neo4j, Ollama (llama3.1:8b, nomic-embed-text) and optionally Langfuse.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
export CGG_USER=${CGG_USER:-pavan.dev}
for s in A B C; do
  $PY -m cgg.cli eval --system "$s" --run "pq-${s}-llama3.1-8b" --no-log-mlflow
done
