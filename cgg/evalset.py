"""Deterministic gold set built from structured label fields (no LLM involved).

Every normal question is generated from a template and its gold answer is computed from the silver
snapshot (openFDA structured fields, or the identity of the label section for quote questions).
Entities used in the prompt few-shot examples are excluded. Templates A5 and A6 are held out from the
few-shot examples on purpose, to show performance on unseen question shapes.
The safety / out-of-scope set is hand written (eval/safety_set.yaml).
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections import defaultdict

import pandas as pd
import yaml

from cgg import config

GOLD_FILE = config.EVAL_DIR / "gold_set.jsonl"
SAFETY_FILE = config.EVAL_DIR / "safety_set.yaml"
SEED = 20261011

# (template, entity) pairs used in few-shot prompts -> excluded from the gold set
FEWSHOT_CLASSES = {"A1": {"Loop Diuretic"}, "A2": {"Factor Xa Inhibitor"}, "A3": {"Aldosterone Antagonist"}}
FEWSHOT_GENERICS = {"torsemide"}
FEWSHOT_LABELS = {("xarelto", "janssen pharmaceuticals, inc."), ("torsemide", "avkare")}

TEMPLATES = {
    "S1": ("single_fact", "bool", "Does the {brand} label from {mfr} carry a boxed warning?",
           "Is there a boxed warning in the prescribing information for {brand} by {mfr}?"),
    "S2": ("single_fact", "set", "What is the route of administration of {brand} from {mfr}?",
           "By which route is {brand} made by {mfr} given?"),
    "S3": ("single_fact", "set", "What is the established pharmacologic class of {brand} from {mfr}?",
           "Which pharmacologic class does {brand} by {mfr} belong to?"),
    "S4": ("single_fact", "set", "What are the active ingredients of {brand} from {mfr}?",
           "Which active substances does {brand} by {mfr} contain?"),
    "Q1": ("quote", "quote", "Quote the boxed warning of {brand} from {mfr}.",
           "What does the boxed warning of {brand} by {mfr} say? Quote it."),
    "Q2": ("quote", "quote", "Quote the contraindications listed on the {brand} label from {mfr}.",
           "What contraindications does the {brand} label by {mfr} state? Quote the label."),
    "Q3": ("quote", "quote", "Quote the indications and usage of {brand} from {mfr}.",
           "What is {brand} by {mfr} indicated for, according to its label? Quote it."),
    "A1": ("aggregate_seen", "int", "How many labels in the corpus have the pharmacologic class {epc}?",
           "What is the number of {epc} labels in the corpus?"),
    "A2": ("aggregate_seen", "set",
           "Which generic drugs in the class {epc} have a boxed warning on at least one label?",
           "List the generic drugs of class {epc} that carry a boxed warning on any label."),
    "A3": ("aggregate_seen", "int", "How many {epc} labels have the route {route}?",
           "Count the labels in class {epc} that are given by the {route} route."),
    "A4": ("aggregate_seen", "set", "Which manufacturers have a label for {generic} in the corpus?",
           "List the manufacturers with a {generic} label in the corpus."),
    "A5": ("aggregate_heldout", "set",
           "Which other generic drugs in the corpus share a mechanism of action with {brand} from {mfr}?",
           "List the generic drugs, other than {brand} by {mfr} itself, that have the same mechanism of action."),
    "A6": ("aggregate_heldout", "set", "Which pharmacologic classes does {mfr} have labels in?",
           "In which established pharmacologic classes does {mfr} have labels?"),
}
PER_TEMPLATE = {"S1": 15, "S2": 15, "S3": 15, "S4": 15, "Q1": 10, "Q2": 10, "Q3": 10,
                "A1": 15, "A2": 15, "A3": 15, "A4": 15, "A5": 15, "A6": 15}
QUOTE_SECTION = {"Q1": "boxed_warning", "Q2": "contraindications", "Q3": "indications_and_usage"}
SUBSET_PER_TEMPLATE = 4  # consistency / paraphrase / robustness subset


def _pick(rng: random.Random, items: list, n: int) -> list:
    items = sorted(items, key=lambda x: json.dumps(x, sort_keys=True, default=str))
    return rng.sample(items, min(n, len(items)))


def build(labels: pd.DataFrame | None = None, sections: pd.DataFrame | None = None, seed: int = SEED) -> list[dict]:
    labels = labels if labels is not None else pd.read_parquet(config.GOLD_DIR / "labels.parquet")
    sections = sections if sections is not None else pd.read_parquet(config.GOLD_DIR / "sections.parquet")
    rng = random.Random(seed)
    L = labels.copy()
    for c in ("routes", "epc", "moa", "substances", "sections_present"):
        L[c] = L[c].map(lambda v: sorted(set(v)) if v is not None else [])
    pair_n = L.groupby(["brand_name", "manufacturer"]).set_id.transform("count")
    uniq = L[(pair_n == 1)]
    uniq = uniq[~uniq.apply(lambda r: (r.brand_name.lower(), r.manufacturer.lower()) in FEWSHOT_LABELS, axis=1)]
    sec_set = set(zip(sections.set_id, sections.section, strict=False))
    qs: list[dict] = []

    def add(tid: str, ents: dict, gold, extra: dict | None = None):
        cat, atype, q, p = TEMPLATES[tid]
        qs.append({"template": tid, "category": cat, "answer_type": atype, "entities": ents,
                   "question": _tidy(q.format(**ents)), "paraphrase": _tidy(p.format(**ents)), "gold": gold,
                   **(extra or {})})

    # ---- single-label facts
    rows = [r for r in uniq.itertuples(index=False)]
    yes = [r for r in rows if r.has_boxed_warning]
    no = [r for r in rows if not r.has_boxed_warning]
    for r in _pick(rng, yes, 8) + _pick(rng, no, PER_TEMPLATE["S1"] - 8):
        add("S1", {"brand": r.brand_name, "mfr": r.manufacturer}, bool(r.has_boxed_warning), {"set_id": r.set_id})
    non_oral = [r for r in rows if r.routes and r.routes != ["ORAL"]]
    oral = [r for r in rows if r.routes == ["ORAL"]]
    for r in _pick(rng, non_oral, 6) + _pick(rng, oral, PER_TEMPLATE["S2"] - 6):
        add("S2", {"brand": r.brand_name, "mfr": r.manufacturer}, list(r.routes), {"set_id": r.set_id})
    for r in _pick(rng, [r for r in rows if r.epc], PER_TEMPLATE["S3"]):
        add("S3", {"brand": r.brand_name, "mfr": r.manufacturer}, list(r.epc), {"set_id": r.set_id})
    multi = [r for r in rows if len(r.substances) > 1]
    single = [r for r in rows if len(r.substances) == 1]
    for r in _pick(rng, multi, 7) + _pick(rng, single, PER_TEMPLATE["S4"] - 7):
        add("S4", {"brand": r.brand_name, "mfr": r.manufacturer}, list(r.substances), {"set_id": r.set_id})
    for tid, sec in QUOTE_SECTION.items():
        cand = [r for r in rows if (r.set_id, sec) in sec_set]
        for r in _pick(rng, cand, PER_TEMPLATE[tid]):
            add(tid, {"brand": r.brand_name, "mfr": r.manufacturer}, {"set_id": r.set_id, "section": sec},
                {"set_id": r.set_id})

    # ---- aggregates
    by_class = defaultdict(list)
    for r in L.itertuples(index=False):
        for c in r.epc:
            by_class[c].append(r)
    classes = sorted(c for c, v in by_class.items() if len(v) >= 2)
    for c in _pick(rng, [c for c in classes if c not in FEWSHOT_CLASSES["A1"]], PER_TEMPLATE["A1"]):
        add("A1", {"epc": c}, len({r.set_id for r in by_class[c]}))
    a2 = []
    for c in classes:
        if c in FEWSHOT_CLASSES["A2"]:
            continue
        g = sorted({r.generic_name for r in by_class[c] if r.has_boxed_warning})
        if 1 <= len(g) <= 8:
            a2.append((c, g))
    for c, g in _pick(rng, a2, PER_TEMPLATE["A2"]):
        add("A2", {"epc": c}, g)
    a3 = []
    for c in classes:
        if c in FEWSHOT_CLASSES["A3"]:
            continue
        routes = sorted({rt for r in by_class[c] for rt in r.routes})
        for rt in routes:
            a3.append((c, rt, len({r.set_id for r in by_class[c] if rt in r.routes})))
    a3_non_oral = [x for x in a3 if x[1] != "ORAL"]
    a3_oral = [x for x in a3 if x[1] == "ORAL"]
    for c, rt, n in _pick(rng, a3_non_oral, 5) + _pick(rng, a3_oral, PER_TEMPLATE["A3"] - 5):
        add("A3", {"epc": c, "route": rt}, n)
    by_generic = defaultdict(set)
    for r in L.itertuples(index=False):
        by_generic[r.generic_name].add(r.manufacturer)
    a4 = [(g, sorted(m)) for g, m in by_generic.items() if 2 <= len(m) <= 6 and g not in FEWSHOT_GENERICS]
    for g, m in _pick(rng, a4, PER_TEMPLATE["A4"]):
        add("A4", {"generic": g}, m)
    by_moa = defaultdict(set)
    for r in L.itertuples(index=False):
        for m in r.moa:
            by_moa[m].add(r.generic_name)
    a5 = []
    for r in rows:
        if not r.moa:
            continue
        others = sorted(set().union(*[by_moa[m] for m in r.moa]) - {r.generic_name})
        if 1 <= len(others) <= 8:
            a5.append((r.brand_name, r.manufacturer, r.set_id, others))
    for b, m, sid, others in _pick(rng, a5, PER_TEMPLATE["A5"]):
        add("A5", {"brand": b, "mfr": m}, others, {"set_id": sid})
    by_mfr = defaultdict(set)
    for r in L.itertuples(index=False):
        by_mfr[r.manufacturer].update(r.epc)
    a6 = [(m, sorted(c)) for m, c in by_mfr.items() if 2 <= len(c) <= 6]
    for m, c in _pick(rng, a6, PER_TEMPLATE["A6"]):
        add("A6", {"mfr": m}, c)

    # ---- ids, perturbations, subset flags
    by_t = defaultdict(list)
    for q in qs:
        by_t[q["template"]].append(q)
    out = []
    for tid in TEMPLATES:
        for i, q in enumerate(by_t[tid], 1):
            q["qid"] = f"{tid}-{i:02d}"
            q["typo"] = typo_variant(q["question"], q["entities"], seed=q["qid"])
            q["in_subset"] = i <= SUBSET_PER_TEMPLATE
            out.append(q)
    return out


def _tidy(s: str) -> str:
    return s.replace("..", ".").replace(".?", "?")


def typo_variant(question: str, entities: dict, seed: str, n_words: int = 2) -> str:
    """Swap two inner letters in n non-entity words (length >= 5). Entity strings stay intact."""
    protected = set()
    for v in entities.values():
        protected.update(w.lower() for w in re.findall(r"\w+", str(v)))
    words = question.split(" ")
    cand = [i for i, w in enumerate(words) if len(re.sub(r"\W", "", w)) >= 5
            and re.sub(r"\W", "", w).lower() not in protected]
    rng = random.Random(hashlib.sha256(seed.encode()).hexdigest())
    for i in sorted(rng.sample(cand, min(n_words, len(cand)))):
        w = words[i]
        core = re.sub(r"\W", "", w)
        j = rng.randrange(1, len(core) - 2)
        swapped = core[:j] + core[j + 1] + core[j] + core[j + 2:]
        words[i] = w.replace(core, swapped, 1)
    return " ".join(words)


def load_gold() -> list[dict]:
    return [json.loads(ln) for ln in GOLD_FILE.read_text().splitlines() if ln.strip()]


def load_safety() -> list[dict]:
    items = yaml.safe_load(SAFETY_FILE.read_text())["items"]
    for i, it in enumerate(items, 1):
        it.setdefault("qid", f"U-{i:02d}")
        it["category"] = "unsafe"
        it["answer_type"] = "refuse"
    return items


def write(questions: list[dict]) -> dict:
    config.EVAL_DIR.mkdir(exist_ok=True)
    GOLD_FILE.write_text("".join(json.dumps(q, sort_keys=True) + "\n" for q in questions))
    serving = json.loads((config.GOLD_DIR / "serving_manifest.json").read_text())
    man = {"n_questions": len(questions), "seed": SEED, "sha256": hashlib.sha256(GOLD_FILE.read_bytes()).hexdigest(),
           "by_template": {t: sum(q["template"] == t for q in questions) for t in TEMPLATES},
           "subset_size": sum(q["in_subset"] for q in questions),
           "source": {"silver.labels": serving["labels"], "silver.sections": serving["sections"]},
           "method": "deterministic templates over structured openFDA fields; no LLM"}
    (config.EVAL_DIR / "gold_manifest.json").write_text(json.dumps(man, indent=1))
    return man


DEV_FILE = config.EVAL_DIR / "dev_set.jsonl"
DEV_SEED = 7


def write_dev() -> int:
    """Development set (different seed, gold questions removed) used for prompt work instead of the gold set."""
    gold_q = {q["question"] for q in load_gold()}
    dev = [q for q in build(seed=DEV_SEED) if q["question"] not in gold_q]
    for q in dev:
        q["qid"] = "dev-" + q["qid"]
    DEV_FILE.write_text("".join(json.dumps(q, sort_keys=True) + "\n" for q in dev))
    return len(dev)


if __name__ == "__main__":
    print(json.dumps(write(build()), indent=1))
