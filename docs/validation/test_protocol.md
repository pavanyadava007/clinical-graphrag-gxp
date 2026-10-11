# Test Protocol (IQ / OQ / PQ)

Document ID: TP-CGG-001, version 1.

## IQ - Installation Qualification
Script: `python scripts/iq_check.py` -> `results/iq_report.json`.
Checks Python, pinned package versions (pyspark 3.5.3, delta-spark 3.2.1, minimum MLflow / neo4j / langfuse),
Java 17+, container image digests (Neo4j, PostgreSQL, Langfuse, Ollama), Ollama model digests, Neo4j and
Langfuse health, GPU. Pass = every check passes.

## OQ - Operational Qualification
Automated tests in `tests/`. Each OQ test carries `@pytest.mark.req("URS-xxx")`. Run:

```bash
CGG_OQ_RECORD=1 .venv/bin/python -m pytest -q   # writes results/oq_results.json
```

Unit tests need no services. `@pytest.mark.spark` tests run the medallion pipeline on a synthetic fixture
(duplicates, out-of-scope class, short section, tampered raw file). `@pytest.mark.integration` tests need Neo4j
and are skipped when it is not running. Pass = all collected OQ tests pass (skips are listed in the report).

## PQ - Performance Qualification
`cgg eval --system C --run pq-C-llama3.1-8b` on the frozen gold set (`eval/gold_set.jsonl`, 179 normal questions
from 13 templates, deterministic gold from structured fields) and the hand-written safety set
(`eval/safety_set.yaml`, 30 items), plus 52 subset questions run 2 more times, paraphrased and typo-perturbed.
Acceptance criteria AC-01..AC-12 in `config/acceptance_criteria.yaml` (frozen before the run). Judge:
deterministic comparison, no LLM judge. HITL decisions in the PQ run come from the oracle reviewer (DEV-01).

Systems A and B and a second model (qwen2.5:7b) are run with the same protocol for comparison only.
