# RCA-001: first PQ run of the guarded system failed the release gate

| Field | Value |
|---|---|
| Trigger | `cgg release 1` blocked model version 1 (eval run `pq-C-llama3.1-8b`) |
| Failed criteria | AC-01 precision of released answers, AC-02 accuracy after review, AC-07 paraphrase agreement, AC-08 typo robustness (values in the evidence section and results/release_decisions.json) |
| Owner | developer (`pavan.dev`); approval of the CAPA candidate by `qa.approver` |
| CAPA | CAPA-001: text2cypher prompt v2, checked on the dev set, full PQ re-run as model version 3 |
| Outcome | version 3 passed all 12 criteria and was released by `release.manager`; see deviation DEV-06 |

## Symptom

Version 1 had 100 % citation precision and handled all 30 unsafe questions, but 10.1 % of normal questions were
released with a wrong answer, which put precision of released answers below the 90 % limit. Paraphrase and typo
variants also changed outcomes more often than allowed.

## Investigation

1. **Classify every wrong or unreleased answer** (scripts/rca_report.py, rule-based categories over the
   per-question results). The two largest groups were graph answers released wrong: "other graph query error"
   (mostly the held-out multi-hop template A5) and "name split into OR conditions" (7 questions).
2. **Read the Langfuse traces** of those questions. The `cypher` span shows the pattern directly, for example
   `WHERE l.generic_name = 'telmisartan' OR l.generic_name = 'hydrochlorothiazide'` for a question about the
   combination product "telmisartan and hydrochlorothiazide". The query is valid and read-only, so the validator
   passes it, and it returns rows, so the empty-result repair loop never fires; the answer lists manufacturers of
   the single-ingredient products instead of the combination product.
3. **Check the graph and the prompt.** In the graph a combination product is one `generic_name` string
   (`'telmisartan and hydrochlorothiazide'`). Prompt v1 did not say so, and none of its examples showed a
   combination product, so the model split the name.

## Five whys

1. Why was version 1 blocked? Precision of released answers was 88.96 %, below 90 % (plus AC-02, AC-07, AC-08).
2. Why were so many wrong answers released? Graph queries returned rows for the wrong products, and the guard only
   re-checks empty or failing queries, not queries that return plausible rows.
3. Why did the queries select the wrong products? The model split combination product names into OR conditions
   on single ingredients, and sometimes matched a brand name against `generic_name`.
4. Why did it do that? The text2cypher prompt described `generic_name` but did not state that combination
   products are stored as one string or that names must be copied as written.
5. Why was this not caught before PQ? The development smoke test had few combination products, and there was no
   dev-set check step for prompt changes.

## Root cause

Missing schema convention in the text2cypher prompt: combination products are a single `generic_name` value and
a named product must be matched on `brand_name` + `manufacturer`. The guard design has a blind spot for
non-empty but wrong graph results.

## CAPA

- **Corrective (CAPA-001):** `text2cypher@v2` adds two schema rules (names copied as one string, combination
  products are one `generic_name`, never split with OR; match a named product on `brand_name`). Checked first on
  the development set (`results/dev/C-cypher-v1.json` vs `results/dev/C-cypher-v2.json`), then the full PQ was
  re-executed with unchanged acceptance criteria (`pq-C-llama3.1-8b-cypher-v2`), registered as version 3,
  approved by QA and released through the gate.
- **Preventive:** dev-set check (`scripts/dev_check.py`) before any PQ run of a prompt change; the guard blind spot
  (plausible but wrong rows) stays open as a known limitation and is listed in the README.
- **Effectiveness:** all 10 questions that improved are combination-product or brand/generic cases (templates A4,
  S1, S4). Three held-out A5 questions regressed, so the held-out multi-hop template got worse (26.7 % to 6.7 %).
  The fix was informed by gold-set failures, so the version 3 numbers are optimistic (deviation DEV-06).
