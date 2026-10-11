# Risk Assessment (FMEA)

Generated from `docs/validation/risks.yaml`. S = severity, O = occurrence, D = detectability (1 = always detected), each 1 to 5; RPN = S x O x D before mitigation. Controls link to URS items, which link to tests in the traceability matrix.

| ID | Hazard | Effect | S | O | D | RPN | Controls (URS) | Residual risk |
|---|---|---|---|---|---|---|---|---|
| R-01 | Hallucinated or wrong answer released to medical-information staff | Wrong label information passed on | 5 | 4 | 4 | 80 | URS-008, URS-010, URS-013, URS-020 | Measured by silent_error_rate on the PQ run; remaining errors are listed per question in the eval table |
| R-02 | Answer taken from the wrong label (same brand, other manufacturer or version) | Wrong product information | 4 | 4 | 3 | 48 | URS-008, URS-013 | Ambiguous names escalate; label set_id is cited in every text answer |
| R-05 | Patient-specific or off-label advice given | Potential patient harm | 5 | 3 | 3 | 45 | URS-012, URS-014 | Refused or routed to a human; measured on the safety set |
| R-08 | Unapproved change (prompt, model, data) reaches production | Unvalidated behaviour in use | 5 | 3 | 3 | 45 | URS-016, URS-018, URS-024, URS-025 | Release gate blocks; demonstrated in RCA-001 |
| R-04 | Prompt injection changes system behaviour | Unsafe or unguarded output | 4 | 3 | 3 | 36 | URS-011 | Rule filter plus policy classifier; measured on the injection subset |
| R-07 | Silent data-quality problems (missing fields, duplicates, out-of-scope records) | Incomplete or wrong graph facts | 3 | 4 | 3 | 36 | URS-004, URS-005, URS-006 | Expectations with quarantine; counts in the pipeline report |
| R-09 | Results not reproducible (unknown model, prompt or data versions) | Cannot investigate or defend a result | 3 | 3 | 4 | 36 | URS-003, URS-017, URS-018, URS-021 | Lineage tags on every run and version |
| R-12 | LLM or prompt update changes behaviour | Regression in answers | 4 | 3 | 3 | 36 | URS-020, URS-025, URS-019 | PQ re-run per candidate; second-model comparison shows sensitivity |
| R-10 | Audit trail edited or truncated | Loss of objective evidence | 4 | 2 | 4 | 32 | URS-022 | Hash chain verify in the release gate |
| R-03 | LLM-written Cypher changes or deletes graph data | Corrupted knowledge graph | 5 | 2 | 3 | 30 | URS-009, URS-007 | Allowlist plus READ transactions; snapshot hash detects any change |
| R-06 | Source data corrupted or changed without notice | Answers based on unknown data | 4 | 2 | 3 | 24 | URS-001, URS-002, URS-003 | sha256 manifest checked before every ingest |
| R-14 | Secrets leaked through the repository | Unauthorised access | 4 | 2 | 2 | 16 | URS-026, URS-023 | Secrets only in gitignored infra/.env; repository scan test |
| R-11 | Over-refusal blocks normal use | Users bypass the tool | 2 | 3 | 2 | 12 | URS-015 | False refusal rate measured on all normal questions |
| R-13 | Service outage or timeouts | Questions unanswered | 2 | 3 | 1 | 6 | URS-027 | Errors recorded as outcomes, never as answers |
