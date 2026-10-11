# Validation Summary Report

Generated 2026-10-11T08:45:52+00:00 by `cgg validation-report`. All values below are read from files written by code; nothing is typed by hand.

**Status statement.** This is a GxP-style validation exercise on a public-data demo, aligned with GAMP 5 (category 5, custom application) and CSA risk-based principles. It is not a validated system and makes no claim of regulatory compliance.

## 1. Scope

Drug-label question answering for medical-information and pharmacovigilance staff over a public openFDA snapshot, released as MLflow model version of system C (guarded GraphRAG).

## 2. Installation Qualification (IQ)

- python: 3.11.16
- package pyspark: 3.5.3 (expected 3.5.3)
- package delta-spark: 3.2.1 (expected 3.2.1)
- package mlflow: 3.5.1 (min 3.1)
- package neo4j: 5.28.6 (min 5.20)
- package langfuse: 2.60.10 (min 2.50)
- java: openjdk version "17.0.17" 2025-10-21 LTS
- image neo4j:5-community: sha256:5ac4722f61af
- image postgres:16-alpine: sha256:81bd698b4594
- image langfuse/langfuse:2: sha256:27c161e3979b
- image ollama/ollama:latest: sha256:2a5d04622211
- ollama model llama3.1:8b: 46e0c10c039e
- ollama model nomic-embed-text:latest: 0a109f422b47
- neo4j: 5.26.31 community
- langfuse: HTTP 200 2.95.11
- gpu: NVIDIA L4, 23034 MiB
- IQ result: **pass** (results/iq_report.json)

## 3. Operational Qualification (OQ)

- Automated tests with requirement markers: 71 collected, 71 passed, 0 skipped, 0 failed (results/oq_results.json).

## 4. Performance Qualification (PQ)

PQ run `pq-C-llama3.1-8b-cypher-v2`, MLflow run `63a20b00a1bb41879320f5d44a71e3aa`, acceptance criteria frozen in config/acceptance_criteria.yaml before the run.

| Criterion | Dimension | Metric | Value | Limit | Result |
|---|---|---|---|---|---|
| AC-01 | accuracy | precision_auto | 0.9441 | >= 0.9 | pass |
| AC-02 | accuracy | accuracy_after_review | 0.9441 | >= 0.9 | pass |
| AC-03 | accuracy | escalation_rate | 0.095 | <= 0.25 | pass |
| AC-04 | grounding | citation_precision | 1 | >= 0.95 | pass |
| AC-05 | grounding | ungrounded_answer_rate | 0 | <= 0.0 | pass |
| AC-06 | consistency | repeat_agreement | 0.9808 | >= 0.95 | pass |
| AC-07 | consistency | paraphrase_agreement | 0.8269 | >= 0.8 | pass |
| AC-08 | robustness | typo_accuracy_drop | 0.0769 | <= 0.1 | pass |
| AC-09 | safety | unsafe_handled_rate | 1 | >= 1.0 | pass |
| AC-10 | safety | false_refusal_rate | 0.0056 | <= 0.02 | pass |
| AC-11 | operational | error_rate | 0 | <= 0.01 | pass |
| AC-12 | operational | latency_p95_s | 11.88 | <= 20.0 | pass |

n: 179 normal questions, 30 unsafe questions, 52 questions x 3 runs for repeat agreement, 52 paraphrases, 52 typo variants, 417 requests in total. Judge: deterministic comparison with gold values derived from structured fields; quotes checked by string containment.

## 5. Traceability

{'verified': 27, 'failed': 0, 'not verified': 0} (traceability_matrix.md).

## 6. Deviations

- DEV-01: The measured HITL step uses an automated oracle reviewer that decides from the gold set. Accuracy after review is therefore an upper bound; no human reviewer took part in the PQ run. Impact: accuracy_after_review overstates what a human review would achieve.
- DEV-02: User identities come from config/roles.yaml and CGG_USER; they are not authenticated (no SSO, no password or PIN at signing). Approvals are Part 11-style records, not compliant electronic signatures. Impact: Segregation of duties is enforced in code but could be bypassed by setting another identity.
- DEV-03: Before the development set existed, the first prompt iteration was smoke-tested on 15 gold questions; the resulting fixes were generic (Neo4j transaction API, schema direction rule, '<>' operator). Later prompt work used eval/dev_set.jsonl only. Impact: Small optimistic bias possible on the gold set.
- DEV-04: The pipeline ran locally on PySpark + Delta Lake, not on a Databricks workspace. The Asset Bundle (databricks.yml) and notebooks are provided but were never deployed. Impact: Databricks-specific behaviour (Unity Catalog permissions, job clusters) is not verified.
- DEV-05: The corpus is a public openFDA snapshot (321 labels after quality checks), and the gold set is generated from structured fields; free-text reasoning questions are only covered by quote questions. Impact: PQ results do not cover open clinical reasoning questions.
- DEV-06: The first PQ run (model version 1) failed AC-01, AC-02, AC-07 and AC-08. CAPA-001 (prompt text2cypher@v2) was designed from the failure categories of that gold-set run (RCA-001), checked on eval/dev_set.jsonl, and then the full PQ was re-executed for model version 3 with unchanged acceptance criteria. Because gold-set failures informed the fix, the version 3 PQ result is optimistic. The held-out template A5 dropped from 26.7 % to 6.7 % with the CAPA prompt. Impact: Version 3 results should be confirmed on a fresh question set before relying on them.

## 7. Release decisions

- 2026-10-11T07:16:37+00:00 version 1 requested by release.manager: BLOCKED (AC-01 precision_auto=0.8896 fails >= 0.9; AC-02 accuracy_after_review=0.8939 fails >= 0.9; AC-07 paraphrase_agreement=0.7308 fails >= 0.8; AC-08 typo_accuracy_drop=0.1154 fails <= 0.1; traceability incomplete: URS-008, URS-019, URS-020)
- 2026-10-11T08:12:27+00:00 version 2 requested by release.manager: BLOCKED (AC-01 precision_auto=0.8812 fails >= 0.9; AC-02 accuracy_after_review=0.8883 fails >= 0.9; AC-07 paraphrase_agreement=0.6538 fails >= 0.8; traceability incomplete: URS-008, URS-019, URS-020; traceability matrix was generated for pq-C-llama3.1-8b, not pq-C-llama3.1-8b-answer-v2)
- 2026-10-11T08:38:52+00:00 version 3 requested by release.manager: RELEASED

## 8. Audit trail

- audit/audit_trail.jsonl: 270 events, hash chain verified.

## 9. Conclusion

All requirements are verified for the PQ run and no PQ criterion failed; the deviations above remain open and limit the meaning of this result to a demonstration.
