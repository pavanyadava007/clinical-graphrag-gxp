# Results

Generated 2026-10-11T06:25:27+00:00 by `scripts/make_results.py` from `results/*.json`. Do not edit by hand. Host: NVIDIA L4 24 GB, models served by Ollama at temperature 0, seed 7. Judge: deterministic comparison with gold values derived from structured openFDA fields (no LLM judge); quotes are checked by string containment in the cited label section.

## 1. Data pipeline (local PySpark + Delta Lake, not Databricks)

| Item | Value | Source |
|---|---|---|
| Raw label records (bronze) | 374 | pipeline_report.json |
| Duplicate records removed (same set_id) | 31 | pipeline_report.json |
| Labels passed / quarantined | 321 / 22 | pipeline_report.json |
| Sections passed / quarantined | 3923 / 7 | pipeline_report.json |
| Retrieval chunks | 13128 | pipeline_report.json |
| Graph nodes / edges | 4491 / 5964 | pipeline_report.json |
| Neo4j snapshot hash equals gold tables | True | graph_load_report.json |
| Embeddings | 13128 x 768 (nomic-embed-text) | embedding_report.json |
| Pipeline duration | 30.4 s | pipeline_report.json |

Quarantined by expectation: epc_in_scope 22, section_text_not_empty 7. Warnings only (kept in silver): has_indications_section 2.

## 2. Evaluation set

179 normal questions from 13 templates (gold sha256 `2163918b0acb8667`), 30 hand-written unsafe / out-of-scope questions, and a subset of 52 questions used for 2 extra repeat runs, paraphrases and typo variants.

## 3. System comparison

| Metric | n | A vector RAG (llama3.1:8b) |
|---|---|---|
| Accuracy, all normal questions (auto-released answers) | 179 | 40.8 % |
| Accuracy without template S3 (EPC vocabulary, see note) | 164 | 44.5 % |
| - single-label facts | 60 | 66.7 % |
| - quote with citation | 30 | 83.3 % |
| - aggregate, template in few-shot | 59 | 13.6 % |
| - aggregate, held-out template | 30 | 0.0 % |
| Set-answer F1 (mean) | 104 | 0.462 |
| Precision of auto-released answers |  | 40.8 % |
| Escalated to human review | 179 | 0.0 % |
| Silent errors (released and wrong) | 179 | 59.2 % |
| Accuracy after review (oracle reviewer, upper bound) | 179 | 40.8 % |
| Citation precision (quote found in cited section) |  | 88.4 % |
| - citations checked | | 423 |
| Ungrounded released answers |  | 9.5 % |
| Repeat agreement (3 runs, T=0) | 52 | 100.0 % |
| Paraphrase agreement | 52 | 84.6 % |
| Typo accuracy drop (points) | 52 | 17.3 % |
| Unsafe / out-of-scope handled (refused or escalated) | 30 | 43.3 % |
| - harmful | 4 | 100.0 % |
| - injection | 8 | 37.5 % |
| - off_label | 6 | 50.0 % |
| - out_of_domain | 4 | 75.0 % |
| - patient_specific | 8 | 0.0 % |
| False refusals on normal questions | 179 | 0.6 % |
| Error rate (all requests) | 417 | 0.0 % |
| Latency p50 (s) |  | 4.81 |
| Latency p95 (s) |  | 14.62 |
| LLM calls per request (mean) |  | 1.00 |

Accuracy by template: see `results/runs/<run>/metrics.json` (`accuracy_by_template`).

Note on template S3 ("established pharmacologic class"): the gold value is the openFDA EPC term (for example "Angiotensin Converting Enzyme Inhibitor"), while label text often says "ACE inhibitor", and for some combination products openFDA lists only one class. The graph systems read the same openFDA field as the gold set, so S3 favours them; the row without S3 removes that effect.

## 8. Validation evidence

- IQ: pass (16 checks, results/iq_report.json)

