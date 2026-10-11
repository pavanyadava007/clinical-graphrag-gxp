# Functional Specification

Document ID: FS-CGG-001, version 1. Maps functions to URS items.

## F1 Data acquisition and medallion pipeline (URS-001..006)
- `cgg fetch`: openFDA `drug/label` API, one request per (pharmacologic class, generic name), the 4 most recent
  prescription labels each. Raw responses stored unchanged; query, time and sha256 in
  `data/manifest/fetch_manifest.json`.
- `cgg ingest` (PySpark 3.5 + Delta Lake 3.2):
  - bronze `labels`: append-only, one row per raw record with source file sha256, record sha256 and request.
    Ingest stops if any raw file differs from its manifest hash.
  - silver `labels`: typed fields from `openfda`, one row per set_id (highest version wins), expectations from
    `cgg/pipeline/expectations.py`; quarantine expectations move rows to silver `quarantine` with the failed names.
  - silver `sections`: one row per label x section for 15 sections, cleaned text, sha256 per section.
  - gold `chunks` (1200 characters, 200 overlap, with a label/section header for embedding) and gold
    `kg_nodes` / `kg_edges`.
  - Delta versions and expectation counts written to `results/pipeline_report.json`.

## F2 Knowledge graph (URS-006, 007)
- Nodes: Label, PharmClass, MoA, Route, Substance, Manufacturer, Section. Relationships: IN_CLASS, HAS_MOA,
  HAS_ROUTE, CONTAINS, MADE_BY, HAS_SECTION from structured fields; MENTIONS_INTERACTION_WITH from a
  dictionary match in the drug_interactions section, marked `extracted=true, method=dictionary-match-v1`.
- Uniqueness constraints, indexes and a full-text index; load by MERGE (idempotent); snapshot sha256 over node keys
  and edge triples compared between Neo4j and the gold tables.

## F3 Question answering (URS-008..013)
- A vector RAG: nomic-embed-text, top 6 chunks over the corpus, answer prompt v1, JSON with citations.
- B GraphRAG: LLM router (graph / text). Graph route: schema-constrained text2cypher prompt, Cypher allowlist
  validator (`cgg/graph/cypher_guard.py`), READ transaction with 10 s timeout, answer assembled from rows.
  Text route: named label resolved with fixed Cypher (exact, then full-text), retrieval restricted to that label.
- C guarded GraphRAG: B plus input injection filter, rule and LLM safety policy, one repair attempt for rejected,
  failing, empty or zero-count graph queries, label ambiguity check, citation verification with one regeneration,
  and escalation to the review queue for anything still unverified.

## F4 Human review (URS-014)
- SQLite queue `data/hitl/queue.db`; `cgg review list`, `cgg review decide <id> approve|reject|edit --reason ...`.
  Reviewer must hold the medical_reviewer role; a reason is mandatory; every decision is audited.

## F5 Lifecycle, observability, release (URS-016..025)
- Prompts versioned as files, registered in the MLflow prompt registry with content hash.
- `cgg eval` logs params, datasets (gold set digest, silver.labels with Delta version), metrics, per-question table,
  Langfuse trace ids and lineage files to MLflow.
- `cgg register` logs system C as a pyfunc model from code and registers a version with lineage tags, alias
  `candidate`. `cgg approve` records a signature-style approval. `cgg release` runs gates G1..G5 and moves alias
  `production` with a deployment record, or records the block with reasons.
- Langfuse traces per question: spans guard_input, guard_policy, route, resolve_label, text2cypher, cypher,
  retrieve, generate, guard_citations; scores `correct` and `citation_precision` attached after evaluation.
- Hash-chained audit trail `audit/audit_trail.jsonl`; `cgg audit verify`.
