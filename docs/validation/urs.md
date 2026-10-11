# User Requirements Specification

Generated from `docs/validation/urs.yaml`. GxP impact: High = could affect the correctness of label information given to medical-information staff.

| ID | Area | GxP impact | Requirement | OQ | PQ criteria |
|---|---|---|---|---|---|
| URS-001 | Data | High | Ingest FDA drug labels from openFDA and record the query, fetch time and sha256 of every raw response. | yes | - |
| URS-002 | Data | High | Keep raw data unchanged (append-only bronze) and detect any change to raw files before ingestion. | yes | - |
| URS-003 | Data | Medium | Record Delta table versions for every pipeline run so any earlier state can be re-read (time travel). | yes | - |
| URS-004 | Data | High | Apply data-quality expectations in silver; quarantine failing records with the failed expectation names and report counts. | yes | - |
| URS-005 | Data | Medium | Resolve duplicate label records deterministically (latest version per set_id). | yes | - |
| URS-006 | Graph | High | Build the knowledge graph from structured openFDA fields only; mark any extracted edge with its method and source section. | yes | - |
| URS-007 | Graph | Medium | Load the graph idempotently and verify its content against the gold tables with a snapshot hash. | yes | - |
| URS-008 | QA | High | Answer label fact and aggregate questions; every released answer carries verified citations (set_id, section, verbatim quote) or the executed graph query as evidence. | yes | AC-01, AC-02, AC-04, AC-05 |
| URS-009 | QA | High | Validate LLM-written Cypher against a read-only allowlist and run it in read-only transactions with a timeout. | yes | - |
| URS-010 | QA | High | Verify citations: the quote must occur in the cited section of the cited label. | yes | AC-04 |
| URS-011 | Safety | High | Refuse prompt-injection and database-command attempts. | yes | AC-09 |
| URS-012 | Safety | High | Refuse or route to a human reviewer any patient-specific, off-label or harmful question. | yes | AC-09 |
| URS-013 | HITL | High | Escalate low-confidence answers (unverifiable citation, failed or empty graph query, ambiguous label) to human review instead of releasing them. | yes | AC-03 |
| URS-014 | HITL | High | Let reviewers approve, reject or edit escalated answers, recording identity, role, reason and time. | yes | - |
| URS-015 | Safety | Medium | Do not refuse normal label questions at a rate above the accepted limit. | - | AC-10 |
| URS-016 | Lifecycle | High | Version-control every prompt and register each version with a content hash. | yes | - |
| URS-017 | Lifecycle | High | Record for every evaluation run the model, parameters, prompt versions, dataset digests, Delta versions, metrics and per-question results in MLflow. | yes | - |
| URS-018 | Lifecycle | High | Tag every registered model version with lineage (git commit, eval run, gold set hash, KG snapshot hash, Delta versions, embeddings hash, prompt versions, LLM digest, author). | yes | - |
| URS-019 | Observability | Medium | Trace every question with spans for routing, query, retrieval, generation and guards, and attach evaluation scores to traces. | yes | - |
| URS-020 | Evaluation | High | Evaluate accuracy, grounding, consistency, robustness, safety and operational reliability with defined metrics, n and thresholds. | yes | AC-06, AC-07, AC-08 |
| URS-021 | Evaluation | High | Derive gold answers deterministically from structured data, without an LLM. | yes | - |
| URS-022 | Audit | High | Record GxP-relevant actions in an append-only, hash-chained audit trail and detect tampering. | yes | - |
| URS-023 | Access | High | Restrict ingest, register, approve, promote and review actions by role. | yes | - |
| URS-024 | Release | High | Prevent the author of a model version from approving it (segregation of duties). | yes | - |
| URS-025 | Release | High | Block promotion to production unless acceptance criteria, traceability, approval, lineage and audit checks all pass; record every decision. | yes | - |
| URS-026 | Security | Medium | Keep secrets (database password, tracing keys, tokens) out of the repository. | yes | - |
| URS-027 | Operations | Low | Meet the error-rate and latency targets on the reference host. | - | AC-11, AC-12 |
