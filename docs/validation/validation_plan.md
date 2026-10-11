# Validation Plan

Document ID: VP-CGG-001, version 1. Status statement: GxP-style validation exercise on a public-data demo.
It is aligned with GAMP 5 (second edition) and the FDA Computer Software Assurance (CSA) guidance in approach
only. It is **not** a validated system and makes no claim of regulatory compliance.

## 1. System and intended use

`clinical-graphrag-gxp` answers questions from medical-information and pharmacovigilance staff about FDA drug
labels (openFDA Structured Product Labels, cardiometabolic scope). It reports what labels state, with citations.
It does not give treatment advice. Answers it cannot verify go to a human reviewer.

## 2. GAMP 5 categorisation

| Component | Category | Reason |
|---|---|---|
| Python package `cgg` (pipeline, graph load, QA systems, guards, release gate) | 5 (custom) | Written for this use |
| Prompts (`cgg/prompts/*.yaml`) | 5 (custom configuration with code-like effect) | Change behaviour like code; versioned and registered |
| Llama 3.1 8B / Qwen 2.5 7B via Ollama | 3 (non-configured, used as supplied) with model-specific PQ | Fixed weights, pinned digest |
| Neo4j 5 Community, PostgreSQL 16, Langfuse 2, MLflow 3, Spark 3.5 + Delta 3.2 | 1 / 3 (infrastructure and standard software) | Installed versions recorded by IQ |

## 3. Risk-based approach (CSA)

Effort follows risk. Requirements with GxP impact High (could change the label information a user receives)
get automated scripted tests (OQ) **and** a quantitative acceptance criterion in the PQ evaluation. Medium and
Low items get unscripted or single-test assurance. The risk assessment (FMEA, `risk_assessment.md`) links
every hazard to controls (URS) and the matrix links every URS to evidence.

## 4. Roles (segregation of duties)

| Role | Identity (demo) | Responsibilities |
|---|---|---|
| Developer / system owner | `pavan.dev` | Builds, ingests data, runs evaluations, registers candidates |
| QA approver | `qa.approver` | Reviews evidence, signs the approval on a model version; cannot be the author |
| Release manager | `release.manager` | Runs the release gate; cannot override failed gates |
| Medical reviewer | `med.reviewer`, `oracle-reviewer` (automated stand-in for the measured run) | Decides escalated answers |

Identities are not authenticated in this demo (deviation DEV-02).

## 5. Deliverables

| Deliverable | File | Produced by |
|---|---|---|
| User Requirements Specification | `urs.md` (from `urs.yaml`) | generated |
| Functional Specification | `functional_spec.md` | written |
| Risk Assessment (FMEA) | `risk_assessment.md` (from `risks.yaml`) | generated |
| Test protocol (IQ/OQ/PQ) | `test_protocol.md` | written |
| IQ evidence | `results/iq_report.json` | `scripts/iq_check.py` |
| OQ evidence | `results/oq_results.json` | `pytest` with `CGG_OQ_RECORD=1` |
| PQ evidence | `results/runs/pq-C-*/metrics.json`, MLflow runs, Langfuse traces | `cgg eval` |
| Traceability matrix | `traceability_matrix.md`, `results/traceability.json` | `cgg validation-report` |
| Validation Summary Report | `validation_summary_report.md` | `cgg validation-report` |
| Data integrity mapping | `alcoa_plus.md` | written |
| Change and deviation records | `deviations.yaml`, `docs/rca/RCA-001.md`, `results/release_decisions.json` | written / generated |

## 6. Acceptance

Release requires all release gates (`cgg release`): PQ acceptance criteria met
(`config/acceptance_criteria.yaml`, frozen in git before the PQ run), traceability complete, a valid
approval by a QA approver who is not the author, complete lineage tags, and an intact audit trail.

## 7. Change control

Any change to code, prompts, model, data snapshot or acceptance criteria produces a new candidate model
version that goes through PQ and the release gate again. RCA-001 shows a prompt change blocked by the gate.
