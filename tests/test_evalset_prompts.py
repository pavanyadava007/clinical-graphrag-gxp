import json
import re

import pandas as pd
import pytest

from cgg import evalset, promptlib


def _labels():
    rows = []
    for i in range(12):
        rows.append({"set_id": f"{i:036d}", "brand_name": f"Brand{i}", "generic_name": f"gen{i % 4}",
                     "manufacturer": f"Maker {i % 3}", "routes": ["ORAL"] if i % 2 else ["SUBCUTANEOUS"],
                     "epc": [f"Class {i % 3}"], "moa": [f"MoA {i % 3}"], "substances": [f"gen{i % 4}"],
                     "has_boxed_warning": i % 2 == 0, "sections_present": ["boxed_warning"]})
    return pd.DataFrame(rows)


def _sections(labels):
    return pd.DataFrame([{"set_id": s, "section": sec} for s in labels.set_id
                         for sec in ("boxed_warning", "contraindications", "indications_and_usage")])


@pytest.mark.req("URS-021")
def test_gold_set_is_deterministic_and_derived_from_fields():
    L = _labels()
    a = evalset.build(L, _sections(L))
    b = evalset.build(L, _sections(L))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    by = {q["qid"]: q for q in a}
    for q in a:
        if q["template"] == "S1":
            row = L[L.set_id == q["set_id"]].iloc[0]
            assert q["gold"] == bool(row.has_boxed_warning)
        if q["template"] == "A1":
            epc = q["entities"]["epc"]
            assert q["gold"] == int(sum(epc in e for e in L.epc))
    assert any(q["in_subset"] for q in by.values())


@pytest.mark.req("URS-021")
def test_gold_builder_uses_no_llm():
    src = open(evalset.__file__).read()
    assert not re.search(r"import .*(llm|ollama|httpx)|from cgg\.llm", src)


def test_typo_variant_keeps_entities():
    q = "How many labels in the corpus have the pharmacologic class Loop Diuretic?"
    t = evalset.typo_variant(q, {"epc": "Loop Diuretic"}, seed="A1-01")
    assert t != q and "Loop Diuretic" in t and len(t) == len(q)


@pytest.mark.req("URS-016")
def test_prompts_versioned_and_hashed():
    ps = promptlib.all_prompts()
    refs = [p.ref for p in ps]
    assert len(refs) == len(set(refs))
    assert {"router@v1", "text2cypher@v1", "answer@v1", "answer@v2", "safety@v1"} <= set(refs)
    p = promptlib.load("answer", 1)
    assert len(p.sha256) == 64 and p.sha256 == promptlib.load("answer", 1).sha256
    assert p.sha256 != promptlib.load("answer", 2).sha256
    s, u = p.render(question="Q1", context="C1")
    assert "Q1" in u and "C1" in u and "{{" not in u
