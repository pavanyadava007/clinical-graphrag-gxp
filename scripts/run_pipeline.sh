#!/usr/bin/env bash
# Full data refresh: Spark medallion pipeline -> serving snapshot -> Neo4j load -> embeddings.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
$PY -m cgg.cli ingest
$PY -m cgg.cli build-graph
$PY -m cgg.cli embed
