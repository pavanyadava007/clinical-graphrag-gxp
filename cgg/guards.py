"""Guardrails used by system C: input injection filter, rule-based safety screen and the citation check."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import pandas as pd

from cgg import config
from cgg.pipeline.text import norm_for_match

SECTIONS_PARQUET = config.GOLD_DIR / "sections.parquet"
LABELS_PARQUET = config.GOLD_DIR / "labels.parquet"

INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"disregard (all |the )?(previous|prior|above|system)",
    r"(reveal|print|show|repeat|output) (me )?(your |the )?(system|hidden|initial) (prompt|instructions|message)",
    r"\byou are now\b",
    r"\bact as\b.*\b(unfiltered|jailbroken|dan)\b",
    r"\bdeveloper mode\b",
    r"^\s*(system|assistant)\s*:",
    r"\b(detach\s+delete|drop\s+(database|constraint|index)|create\s+\(|merge\s+\(|set\s+\w+\.\w+\s*=)",
    r"\bcall\s+(dbms|apoc|db)\.",
    r"\bload\s+csv\b",
    r"'\s*\}\s*\)",  # attempt to break out of a Cypher string literal
    r"disable (the )?(citations?|guardrails?|safety|filters?)",
    r"\bjailbreak\b",
]

PATIENT_PATTERNS = [
    r"\b(my|our)\s+(mother|mom|father|dad|wife|husband|son|daughter|child|patient|grand\w+|friend|aunt|uncle|brother|sister)\b",
    r"\bi(?:'m| am)\s+(taking|on|prescribed|pregnant)\b",
    r"\bshould (i|he|she|they|we)\b",
    r"\bcan (i|he|she|they|we)\s+(take|stop|double|skip|switch|give|use)\b",
    r"\b(double|halve|skip|stop)\s+(my|his|her|the)\s+(dose|tablet|pill)",
    r"\bwhat dose should\b",
]
HARM_PATTERNS = [
    r"\b(lethal|fatal|deadly)\s+(dose|amount)\b",
    r"\bwithout (a )?prescription\b",
    r"\b(undetected|without being detected|untraceable)\b",
    r"\boverdose on\b",
    r"\bkill\b",
]


@dataclass
class ScreenResult:
    category: str  # in_scope | injection | patient_specific | harmful
    matched: list[str]


def screen_rules(question: str) -> ScreenResult:
    q = question.lower()
    hits = [p for p in INJECTION_PATTERNS if re.search(p, q, flags=re.I | re.M)]
    if hits:
        return ScreenResult("injection", hits)
    hits = [p for p in HARM_PATTERNS if re.search(p, q)]
    if hits:
        return ScreenResult("harmful", hits)
    hits = [p for p in PATIENT_PATTERNS if re.search(p, q)]
    if hits:
        return ScreenResult("patient_specific", hits)
    return ScreenResult("in_scope", [])


@lru_cache(maxsize=1)
def section_texts() -> dict[tuple[str, str], str]:
    df = pd.read_parquet(SECTIONS_PARQUET, columns=["set_id", "section", "text"])
    return {(r.set_id, r.section): r.text for r in df.itertuples(index=False)}


@lru_cache(maxsize=1)
def _normed() -> dict[tuple[str, str], str]:
    return {k: norm_for_match(v) for k, v in section_texts().items()}


MIN_QUOTE_CHARS = 20


def check_citation(c: dict, allowed_set_ids: set[str] | None = None) -> tuple[bool, str]:
    """A citation is valid when the set_id and section exist and the quote occurs verbatim
    (case and whitespace normalised) in that section. Quotes may be shortened with '...'."""
    if not isinstance(c, dict):
        return False, "citation is not an object"
    sid, sec, quote = str(c.get("set_id", "")).strip(), str(c.get("section", "")).strip(), c.get("quote") or ""
    if allowed_set_ids is not None and sid not in allowed_set_ids:
        return False, "set_id not among the retrieved labels"
    text = _normed().get((sid, sec))
    if text is None:
        return False, "unknown set_id/section"
    parts = [norm_for_match(p) for p in re.split(r"\.\.\.|…", str(quote)) if norm_for_match(p)]
    if not parts or sum(len(p) for p in parts) < MIN_QUOTE_CHARS:
        return False, "quote too short"
    for p in parts:
        if p not in text:
            return False, "quote not found in cited section"
    return True, "ok"


def check_citations(cits: list, allowed_set_ids: set[str] | None = None) -> dict:
    res = [check_citation(c, allowed_set_ids) for c in (cits or [])]
    n_ok = sum(ok for ok, _ in res)
    return {"n": len(res), "n_valid": n_ok, "all_valid": bool(res) and n_ok == len(res),
            "reasons": [r for ok, r in res if not ok]}
