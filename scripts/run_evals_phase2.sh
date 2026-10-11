#!/usr/bin/env bash
# Second-model run of system C (qwen2.5:7b on a second Ollama container) and the RCA-001 candidate
# (system C with the shortened answer prompt v2). Resumable like run_evals.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
export CGG_USER=${CGG_USER:-pavan.dev}
QWEN_VOLUME=${QWEN_VOLUME:-cgg_ollama}
if ! docker ps --format '{{.Names}}' | grep -q '^cgg-ollama-qwen$'; then
  docker run -d --rm --name cgg-ollama-qwen --gpus all -p 127.0.0.1:11502:11434 \
    -v "$QWEN_VOLUME":/root/.ollama ollama/ollama:latest >/dev/null
  sleep 5
fi
CGG_OLLAMA_HOST=http://127.0.0.1:11502 CGG_EMBED_HOST=http://127.0.0.1:11501 \
  $PY -m cgg.cli eval --system C --model qwen2.5:7b --run pq-C-qwen2.5-7b --no-log-mlflow
docker stop cgg-ollama-qwen >/dev/null
$PY -m cgg.cli eval --system C --answer-prompt 2 --run pq-C-llama3.1-8b-answer-v2 --no-log-mlflow
