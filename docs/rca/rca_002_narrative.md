# RCA-002: shortened answer prompt (change-control drill)

| Field | Value |
|---|---|
| Change | `answer@v1` -> `answer@v2`, proposed to shorten the composer prompt (fewer instructions, lower token cost) |
| Candidate | MLflow model version 2, eval run `pq-C-llama3.1-8b-answer-v2` |
| Baseline | model version 1, eval run `pq-C-llama3.1-8b` |
| Decision | release of version 2 **blocked** by the gate (see results/release_decisions.json) |
| Status | closed, change rejected |

## Symptom

The candidate was approved by QA on paper, but `cgg release 2` blocked it: AC-01, AC-02 and AC-07 fail, and the
traceability matrix had not been produced for this run. Compared with the baseline, accuracy dropped and more
answers went to human review, while citation precision stayed at 100 %. All numbers are in the evidence section.

## Investigation

1. **Per-question diff** (scripts/rca_report.py): every regression is a quote question on the text route; no
   graph-route answer changed. The final status of every regressed question is `escalated`, not "released and
   wrong", so the citation guard stopped the bad answers before release.
2. **Langfuse traces** of the regressed questions: the `guard_citations` span shows `quote too short` or zero
   citations for the candidate, against fully verified citations for the same questions in the baseline.
3. **Prompt diff**: v2 removed "Use ONLY the label excerpts", "a quote copied word for word ... at least
   8 words" and "Never paraphrase inside a quote", and asked for "a short supporting quote" instead.

## Five whys

1. Why was the release blocked? Accuracy-related criteria failed and more answers were escalated than for the baseline.
2. Why were more answers escalated? The citation check rejected the candidate's quotes on quote questions.
3. Why were the quotes rejected? They were shorter than the 20-character minimum or missing.
4. Why were they short? The v2 prompt asks for "a short supporting quote" and no longer requires full,
   verbatim sentences.
5. Why did the change reach a candidate at all? Prompt edits were treated as a wording change; there was no
   pre-PQ dev-set check for prompt changes.

## Root cause

The composer prompt v2 removed the verbatim-quote and context-only rules that the citation guard depends on.

## CAPA

- Corrective: reject `answer@v2`; version 1 prompt stays in use. No production change happened.
- Preventive: every prompt change gets a dev-set check (`scripts/dev_check.py`) before a PQ run, and the
  verbatim-quote rule is now named in the Functional Specification (F3) as a dependency of URS-010.

## Note on what the guard did

Because the guard escalated the unverifiable answers, the regression showed up as review workload and lower
auto-released accuracy, not as wrong answers reaching users. The baseline already failed the gate (RCA-001),
so this drill shows the per-question evidence of a change rather than a pass-to-fail flip.
