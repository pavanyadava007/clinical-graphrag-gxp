import pytest

from cgg.metrics import canonical, parse_bool, parse_int, score, set_scores, summarize
from cgg.pipeline.text import chunk_text, clean_text, norm_for_match, strip_class_suffix, strip_heading


def test_chunk_text_covers_text_with_overlap():
    text = " ".join(f"word{i}" for i in range(600))
    chunks = chunk_text(text, 300, 50)
    assert chunks[0][0] == 0 and chunks[-1][1] == len(text)
    for (a0, b0, _), (a1, _, _) in zip(chunks, chunks[1:], strict=False):
        assert a1 < b0  # overlap
        assert a1 > a0
    assert all(len(c) <= 300 for _, _, c in chunks)


def test_chunk_text_rejects_bad_params():
    with pytest.raises(ValueError):
        chunk_text("abc", 10, 10)


def test_clean_and_heading():
    assert clean_text("a  b\n\n c") == "a b c"
    s = "1 INDICATIONS AND USAGE Eliquis is indicated to reduce the risk of stroke and systemic embolism in patients."
    assert strip_heading(s).startswith("Eliquis is indicated")
    assert norm_for_match("  The  Drug’s ") == "the drug's"
    assert strip_class_suffix("Factor Xa Inhibitor [EPC]") == "Factor Xa Inhibitor"


@pytest.mark.req("URS-020")
def test_set_scores_exact_and_partial():
    assert set_scores(["Apixaban", "rivaroxaban"], ["apixaban", "rivaroxaban"])["exact"]
    s = set_scores(["apixaban"], ["apixaban", "rivaroxaban"])
    assert not s["exact"] and s["precision"] == 1 and s["recall"] == 0.5
    assert set_scores("Cardinal Health 107, LLC; AvKARE", ["Cardinal Health 107 LLC", "AvKARE"])["exact"]
    # a combination product must not count as the single-ingredient gold item twice
    s = set_scores(["amlodipine and valsartan", "amlodipine"], ["amlodipine"])
    assert s["recall"] == 1 and s["precision"] == 0.5


@pytest.mark.req("URS-020")
def test_parsers():
    assert parse_bool("Yes, it carries one") is True
    assert parse_bool(False) is False
    assert parse_bool("maybe") is None
    assert parse_int("There are 12 labels") == 12
    assert parse_int(True) is None
    assert parse_int([4]) == 4


@pytest.mark.req("URS-020")
def test_score_by_type_and_refusals():
    q_bool = {"answer_type": "bool", "gold": True}
    assert score(q_bool, {"status": "answered", "answer": "yes"})["correct"]
    assert not score(q_bool, {"status": "escalated", "answer": "yes"})["correct"]
    q_int = {"answer_type": "int", "gold": 3}
    assert score(q_int, {"status": "answered", "answer": 3})["correct"]
    q_ref = {"answer_type": "refuse", "gold": None}
    assert score(q_ref, {"status": "refused", "answer": "x"})["handled"]
    assert score(q_ref, {"status": "answered", "answer": None})["handled"]
    assert not score(q_ref, {"status": "answered", "answer": "take 10 mg"})["handled"]


def _rec(qid, status="answered", answer=1, correct=True, cat="single_fact", atype="int", latency=1.0, sub=True):
    q = {"qid": qid, "answer_type": atype, "category": cat, "template": qid[:2], "in_subset": sub, "kind": "x",
         "gold": 1}
    r = {"status": status, "answer": answer, "citations": [], "route": "graph", "cypher": "MATCH", "rows": [],
         "latency_s": latency, "llm_calls": 2, "prompt_tokens": 10, "completion_tokens": 5, "reason": None}
    return {"q": q, "r": r, "s": {"correct": correct, "handled": status != "answered"}}


@pytest.mark.req("URS-020")
def test_summarize_six_dimensions():
    main = [_rec("S1-01"), _rec("S1-02", correct=False, answer=2), _rec("S1-03", status="escalated", correct=False),
            _rec("U-01", status="refused", atype="refuse", cat="unsafe", sub=False)]
    reps = [[_rec("S1-01"), _rec("S1-02", correct=False, answer=2), _rec("S1-03", status="escalated",
                                                                         correct=False)]]
    m = summarize(main, reps, para=[_rec("S1-01")], typo=[_rec("S1-01", correct=False, answer=5)],
                  reviewed={"S1-03": {"final_correct": True}, "_counts": {"edited": 1}})
    assert m["n_normal"] == 3 and m["accuracy"] == round(1 / 3, 4)
    assert m["precision_auto"] == 0.5 and m["escalation_rate"] == round(1 / 3, 4)
    assert m["accuracy_after_review"] == round(2 / 3, 4)
    assert m["repeat_agreement"] == 1.0
    assert m["paraphrase_agreement"] == 1.0 and m["typo_accuracy_drop"] == 1.0
    assert m["unsafe_handled_rate"] == 1.0 and m["false_refusal_rate"] == 0.0
    assert m["error_rate"] == 0.0 and m["latency_p95_s"] == 1.0
    assert m["ungrounded_answer_rate"] == 0.0  # graph answers carry the executed query as evidence


def test_canonical_ignores_list_order():
    a = {"status": "answered", "answer": ["b", "A"]}
    b = {"status": "answered", "answer": ["a", "B"]}
    assert canonical(a) == canonical(b)


@pytest.mark.req("URS-020")
def test_truncated_json_reply_is_unwrapped_and_adverbs_match():
    from cgg.metrics import unwrap

    raw = '{"answer": ["glyburide", "metformin hydrochloride"], "citations": [{"set_id": "x", "quo'
    assert unwrap(raw) == ["glyburide", "metformin hydrochloride"]
    q = {"answer_type": "set", "gold": ["SUBCUTANEOUS"]}
    assert score(q, {"status": "answered", "answer": "subcutaneously"})["correct"]
