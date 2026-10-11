# Results

Generated 2026-10-11T08:45:52+00:00 by `scripts/make_results.py` from `results/*.json`. Do not edit by hand. Host: NVIDIA L4 24 GB, models served by Ollama at temperature 0, seed 7. Judge: deterministic comparison with gold values derived from structured openFDA fields (no LLM judge); quotes are checked by string containment in the cited label section.

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

| Metric | n | A vector RAG (llama3.1:8b) | B GraphRAG (llama3.1:8b) | C GraphRAG + guardrails + HITL (llama3.1:8b) | C GraphRAG + guardrails + HITL (qwen2.5:7b) | C, answer@v2 (RCA-002 drill) (llama3.1:8b) | C, text2cypher@v2 (CAPA-001) (llama3.1:8b) |
|---|---|---|---|---|---|---|---|
| Accuracy, all normal questions (auto-released answers) | 179 | 40.8 % | 74.9 % | 81.0 % | 86.6 % | 78.8 % | 84.9 % |
| Accuracy without template S3 (EPC vocabulary, see note) | 164 | 44.5 % | 75.6 % | 79.3 % | 85.4 % | 76.8 % | 83.5 % |
| - single-label facts | 60 | 66.7 % | 78.3 % | 86.7 % | 90.0 % | 86.7 % | 93.3 % |
| - quote with citation | 30 | 83.3 % | 80.0 % | 86.7 % | 83.3 % | 73.3 % | 86.7 % |
| - aggregate, template in few-shot | 59 | 13.6 % | 86.4 % | 86.4 % | 94.9 % | 86.4 % | 96.6 % |
| - aggregate, held-out template | 30 | 0.0 % | 40.0 % | 53.3 % | 66.7 % | 53.3 % | 43.3 % |
| Set-answer F1 (mean over answered set questions) |  | 0.462 | 0.677 | 0.902 | 0.958 | 0.902 | 0.972 |
| Precision of auto-released answers |  | 40.8 % | 74.9 % | 89.0 % | 92.8 % | 88.1 % | 94.4 % |
| Escalated to human review | 179 | 0.0 % | 0.0 % | 8.4 % | 6.7 % | 10.1 % | 9.5 % |
| Silent errors (released and wrong) | 179 | 59.2 % | 25.1 % | 10.1 % | 6.7 % | 10.6 % | 5.0 % |
| Accuracy after review (oracle reviewer, upper bound) | 179 | 40.8 % | 74.9 % | 89.4 % | 93.3 % | 88.8 % | 94.4 % |
| Citation precision (quote found in cited section) |  | 88.4 % | 89.7 % | 100.0 % | 100.0 % | 100.0 % | 100.0 % |
| - citations checked | | 423 | 58 | 43 | 26 | 37 | 43 |
| Ungrounded released answers |  | 9.5 % | 3.4 % | 0.0 % | 0.0 % | 0.0 % | 0.0 % |
| Repeat agreement (3 runs, T=0) | 52 | 100.0 % | 98.1 % | 98.1 % | 98.1 % | 100.0 % | 98.1 % |
| Paraphrase agreement | 52 | 84.6 % | 73.1 % | 73.1 % | 76.9 % | 65.4 % | 82.7 % |
| Typo accuracy drop | 52 | 17.3 pts | 1.9 pts | 11.5 pts | 9.6 pts | 5.8 pts | 7.7 pts |
| Unsafe / out-of-scope handled (refused or escalated) | 30 | 43.3 % | 43.3 % | 100.0 % | 100.0 % | 100.0 % | 100.0 % |
| - harmful | 4 | 100.0 % | 100.0 % | 100.0 % | 100.0 % | 100.0 % | 100.0 % |
| - injection | 8 | 37.5 % | 37.5 % | 100.0 % | 100.0 % | 100.0 % | 100.0 % |
| - off_label | 6 | 50.0 % | 50.0 % | 100.0 % | 100.0 % | 100.0 % | 100.0 % |
| - out_of_domain | 4 | 75.0 % | 75.0 % | 100.0 % | 100.0 % | 100.0 % | 100.0 % |
| - patient_specific | 8 | 0.0 % | 0.0 % | 100.0 % | 100.0 % | 100.0 % | 100.0 % |
| Refused or empty answer on normal questions | 179 | 0.6 % | 14.5 % | 0.6 % | 0.0 % | 0.6 % | 0.6 % |
| Error rate (all requests) | 417 | 0.0 % | 0.0 % | 0.0 % | 0.0 % | 0.0 % | 0.0 % |
| Latency p50 (s) |  | 4.81 | 1.90 | 2.30 | 2.12 | 2.30 | 2.32 |
| Latency p95 (s) |  | 14.62 | 9.18 | 11.91 | 6.91 | 12.00 | 11.88 |
| LLM calls per request (mean) |  | 1.00 | 2.01 | 2.94 | 2.87 | 2.94 | 2.93 |

Accuracy by template: see `results/runs/<run>/metrics.json` (`accuracy_by_template`).

Note on template S3 ("established pharmacologic class"): the gold value is the openFDA EPC term (for example "Angiotensin Converting Enzyme Inhibitor"), while label text often says "ACE inhibitor", and for some combination products openFDA lists only one class. The graph systems read the same openFDA field as the gold set, so S3 favours them; the row without S3 removes that effect.

## 4. PQ acceptance criteria: C GraphRAG + guardrails + HITL (`pq-C-llama3.1-8b`)

| ID | Metric | Value | Limit | Result |
|---|---|---|---|---|
| AC-01 | precision_auto | 0.8896 | >= 0.9 | FAIL |
| AC-02 | accuracy_after_review | 0.8939 | >= 0.9 | FAIL |
| AC-03 | escalation_rate | 0.0838 | <= 0.25 | pass |
| AC-04 | citation_precision | 1.0000 | >= 0.95 | pass |
| AC-05 | ungrounded_answer_rate | 0.0000 | <= 0.0 | pass |
| AC-06 | repeat_agreement | 0.9808 | >= 0.95 | pass |
| AC-07 | paraphrase_agreement | 0.7308 | >= 0.8 | FAIL |
| AC-08 | typo_accuracy_drop | 0.1154 | <= 0.1 | FAIL |
| AC-09 | unsafe_handled_rate | 1.0000 | >= 1.0 | pass |
| AC-10 | false_refusal_rate | 0.0056 | <= 0.02 | pass |
| AC-11 | error_rate | 0.0000 | <= 0.01 | pass |
| AC-12 | latency_p95_s | 11.9150 | <= 20.0 | pass |

## 4. PQ acceptance criteria: C, answer@v2 (RCA-002 drill) (`pq-C-llama3.1-8b-answer-v2`)

| ID | Metric | Value | Limit | Result |
|---|---|---|---|---|
| AC-01 | precision_auto | 0.8812 | >= 0.9 | FAIL |
| AC-02 | accuracy_after_review | 0.8883 | >= 0.9 | FAIL |
| AC-03 | escalation_rate | 0.1006 | <= 0.25 | pass |
| AC-04 | citation_precision | 1.0000 | >= 0.95 | pass |
| AC-05 | ungrounded_answer_rate | 0.0000 | <= 0.0 | pass |
| AC-06 | repeat_agreement | 1.0000 | >= 0.95 | pass |
| AC-07 | paraphrase_agreement | 0.6538 | >= 0.8 | FAIL |
| AC-08 | typo_accuracy_drop | 0.0577 | <= 0.1 | pass |
| AC-09 | unsafe_handled_rate | 1.0000 | >= 1.0 | pass |
| AC-10 | false_refusal_rate | 0.0056 | <= 0.02 | pass |
| AC-11 | error_rate | 0.0000 | <= 0.01 | pass |
| AC-12 | latency_p95_s | 12.0000 | <= 20.0 | pass |

## 4. PQ acceptance criteria: C, text2cypher@v2 (CAPA-001) (`pq-C-llama3.1-8b-cypher-v2`)

| ID | Metric | Value | Limit | Result |
|---|---|---|---|---|
| AC-01 | precision_auto | 0.9441 | >= 0.9 | pass |
| AC-02 | accuracy_after_review | 0.9441 | >= 0.9 | pass |
| AC-03 | escalation_rate | 0.0950 | <= 0.25 | pass |
| AC-04 | citation_precision | 1.0000 | >= 0.95 | pass |
| AC-05 | ungrounded_answer_rate | 0.0000 | <= 0.0 | pass |
| AC-06 | repeat_agreement | 0.9808 | >= 0.95 | pass |
| AC-07 | paraphrase_agreement | 0.8269 | >= 0.8 | pass |
| AC-08 | typo_accuracy_drop | 0.0769 | <= 0.1 | pass |
| AC-09 | unsafe_handled_rate | 1.0000 | >= 1.0 | pass |
| AC-10 | false_refusal_rate | 0.0056 | <= 0.02 | pass |
| AC-11 | error_rate | 0.0000 | <= 0.01 | pass |
| AC-12 | latency_p95_s | 11.8840 | <= 20.0 | pass |

## 5. Release decisions

| Time (UTC) | Version | Eval run | Decision | Reasons |
|---|---|---|---|---|
| 2026-10-11T07:16:37+00:00 | 1 | pq-C-llama3.1-8b | blocked | AC-01 precision_auto=0.8896 fails >= 0.9; AC-02 accuracy_after_review=0.8939 fails >= 0.9; AC-07 paraphrase_agreement=0.7308 fails >= 0.8; AC-08 typo_accuracy_drop=0.1154 fails <= 0.1; traceability incomplete: URS-008, URS-019, URS-020 |
| 2026-10-11T08:12:27+00:00 | 2 | pq-C-llama3.1-8b-answer-v2 | blocked | AC-01 precision_auto=0.8812 fails >= 0.9; AC-02 accuracy_after_review=0.8883 fails >= 0.9; AC-07 paraphrase_agreement=0.6538 fails >= 0.8; traceability incomplete: URS-008, URS-019, URS-020; traceability matrix was generated for pq-C-llama3.1-8b, not pq-C-llama3.1-8b-answer-v2 |
| 2026-10-11T08:38:52+00:00 | 3 | pq-C-llama3.1-8b-cypher-v2 | released | - |

## 6. Root cause analyses

### RCA-001 (text2cypher@v1 -> text2cypher@v2)

Baseline `pq-C-llama3.1-8b` vs candidate `pq-C-llama3.1-8b-cypher-v2`: 3 questions regressed, 10 improved (n = 209). See docs/rca/RCA-001.md.

| Metric | Baseline | Candidate |
|---|---|---|
| accuracy | 0.8101 | 0.8492 |
| precision_auto | 0.8896 | 0.9441 |
| escalation_rate | 0.0838 | 0.0950 |
| silent_error_rate | 0.1006 | 0.0503 |
| citation_precision | 1.0000 | 1.0000 |
| ungrounded_answer_rate | 0.0000 | 0.0000 |
| unsafe_handled_rate | 1.0000 | 1.0000 |
| false_refusal_rate | 0.0056 | 0.0056 |
| latency_p50_s | 2.2960 | 2.3200 |
| latency_p95_s | 11.9150 | 11.8840 |
| tokens_mean | 2130.4000 | 2185.8000 |

### RCA-002 (answer@v1 -> answer@v2)

Baseline `pq-C-llama3.1-8b` vs candidate `pq-C-llama3.1-8b-answer-v2`: 5 questions regressed, 1 improved (n = 209). See docs/rca/RCA-002.md.

| Metric | Baseline | Candidate |
|---|---|---|
| accuracy | 0.8101 | 0.7877 |
| precision_auto | 0.8896 | 0.8812 |
| escalation_rate | 0.0838 | 0.1006 |
| silent_error_rate | 0.1006 | 0.1061 |
| citation_precision | 1.0000 | 1.0000 |
| ungrounded_answer_rate | 0.0000 | 0.0000 |
| unsafe_handled_rate | 1.0000 | 1.0000 |
| false_refusal_rate | 0.0056 | 0.0056 |
| latency_p50_s | 2.2960 | 2.3030 |
| latency_p95_s | 11.9150 | 12.0000 |
| tokens_mean | 2130.4000 | 2125.3000 |

## 7. Observability

Langfuse (self-hosted v2) project held 2535 traces at export time; 6 sample traces with spans and scores are in `results/langfuse_sample.json`.

## 8. Validation evidence

- IQ: pass (16 checks, results/iq_report.json)
- OQ: 71 of 71 requirement-linked tests passed, 0 skipped (results/oq_results.json)
- Traceability: {'verified': 27, 'failed': 0, 'not verified': 0} (results/traceability.json)

