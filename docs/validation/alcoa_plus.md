# Data Integrity: ALCOA+ mapping

| Principle | How it is met in this project | Evidence |
|---|---|---|
| Attributable | Every audit event records the actor and roles; review decisions record reviewer and role; approvals record approver; MLflow versions record author | `audit/audit_trail.jsonl`, `data/hitl/queue.db`, model version tags |
| Legible | JSON / JSONL / Delta / Markdown, human readable; generated reports | `results/`, `docs/validation/` |
| Contemporaneous | Timestamps written by code at the time of the action (UTC) | audit `ts_utc`, `decided_utc`, MLflow run times, Langfuse trace times |
| Original | Raw openFDA responses kept byte for byte with sha256; bronze is append-only | `data/manifest/fetch_manifest.json`, bronze Delta history |
| Accurate | Data-quality expectations with quarantine; snapshot hash Neo4j vs gold; citations checked against source text | `results/pipeline_report.json`, `results/graph_load_report.json` |
| Complete | Quarantined rows are kept with reasons, not deleted; every evaluation request (including errors) is stored | silver `quarantine`, `results/runs/*/answers.jsonl` |
| Consistent | Deterministic gold set, T=0 and fixed seed, repeat agreement measured | `eval/gold_manifest.json`, metrics `repeat_agreement` |
| Enduring | Delta time travel, git history, MLflow store, committed evidence files | Delta `_delta_log`, `git log` |
| Available | All evidence is in the repository or reproducible with the documented commands | README "Reproduce" |

Limits: identities are not authenticated (DEV-02); the audit trail is tamper-evident, not tamper-proof (a user with
file access can rewrite the whole chain). Each release decision stores the audit head hash at that moment in
`results/release_decisions.json` and the MLflow deployment record, which anchors the chain outside the log file.
