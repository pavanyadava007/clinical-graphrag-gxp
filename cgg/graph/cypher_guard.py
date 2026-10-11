"""Read-only Cypher allowlist validator used before any LLM-written query reaches Neo4j.

Checks (in this order): single statement, no write/admin clause, no procedure calls except the
allowlisted full-text lookup, only known node labels / relationship types / property keys,
MATCH + RETURN present, LIMIT enforced. Queries are additionally executed in a READ access-mode
transaction with a timeout, so a validator gap still cannot write.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

NODE_LABELS = {"Label", "PharmClass", "MoA", "Route", "Substance", "Manufacturer", "Section"}
REL_TYPES = {"IN_CLASS", "HAS_MOA", "HAS_ROUTE", "CONTAINS", "MADE_BY", "HAS_SECTION", "MENTIONS_INTERACTION_WITH"}
PROPERTIES = {
    "set_id", "label_id", "version", "effective_date", "brand_name", "generic_name", "manufacturer",
    "has_boxed_warning", "application_number", "name", "key", "n_chars", "text_sha256", "extracted", "method",
    "source",
}
ALLOWED_PROCEDURES = {"db.index.fulltext.querynodes"}
FORBIDDEN = [
    r"\bCREATE\b", r"\bMERGE\b", r"\bDELETE\b", r"\bDETACH\b", r"\bSET\b", r"\bREMOVE\b", r"\bDROP\b",
    r"\bLOAD\s+CSV\b", r"\bFOREACH\b", r"\bapoc\.", r"\bdbms\.", r"\bIN\s+TRANSACTIONS\b", r"\bPERIODIC\b",
    r"\bGRANT\b", r"\bREVOKE\b", r"\bDENY\b", r"\bALTER\b", r"\bSTART\b", r"\bSTOP\b", r"\bTERMINATE\b",
    r"\bSHOW\b", r"\bUSE\b",
]
MAX_LIMIT = 500


@dataclass
class GuardResult:
    ok: bool
    query: str
    reasons: list[str] = field(default_factory=list)


def _strip_literals(q: str) -> str:
    q = re.sub(r"'(?:[^'\\]|\\.)*'", "''", q)
    q = re.sub(r'"(?:[^"\\]|\\.)*"', '""', q)
    return q


def _strip_comments(q: str) -> str:
    q = re.sub(r"/\*.*?\*/", " ", q, flags=re.S)
    return re.sub(r"//[^\n]*", " ", q)


def extract_cypher(text: str) -> str:
    """Take the query out of an LLM reply (code fences, 'cypher' prefix, trailing prose)."""
    m = re.search(r"```(?:cypher)?\s*(.*?)```", text, flags=re.S | re.I)
    q = m.group(1) if m else text
    q = re.sub(r"^\s*cypher\s*[:\n]", "", q, flags=re.I).strip()
    return q.strip().rstrip(";").strip()


def validate(query: str) -> GuardResult:
    reasons: list[str] = []
    q = _strip_comments(query).strip().rstrip(";").strip()
    bare = _strip_literals(q)
    if ";" in bare:
        reasons.append("multiple statements")
    for pat in FORBIDDEN:
        if re.search(pat, bare, flags=re.I):
            reasons.append(f"forbidden clause {pat.strip(chr(92) + 'b')}")
    for proc in re.findall(r"\bCALL\s+([A-Za-z_][\w.]*)", bare, flags=re.I):
        if proc.lower() not in ALLOWED_PROCEDURES:
            reasons.append(f"procedure not allowed: {proc}")
    if re.search(r"\bCALL\s*\{", bare, flags=re.I):
        reasons.append("subquery CALL not allowed")
    if not re.search(r"\bMATCH\b", bare, flags=re.I) or not re.search(r"\bRETURN\b", bare, flags=re.I):
        reasons.append("query must MATCH and RETURN")
    # Node labels: '(' optional var ':' Label  (also handles multi-labels a:B:C)
    for grp in re.findall(r"\(\s*\w*\s*((?::\s*`?\w+`?\s*)+)", bare):
        for lab in re.findall(r":\s*`?(\w+)`?", grp):
            if lab not in NODE_LABELS:
                reasons.append(f"unknown node label {lab}")
    for grp in re.findall(r"\[\s*\w*\s*:\s*([\w|`:\s]+?)\s*(?:\*[\d.]*)?\s*(?:\{[^}]*\})?\s*\]", bare):
        for rel in re.split(r"[|:]", grp):
            rel = rel.strip(" `")
            if rel and rel not in REL_TYPES:
                reasons.append(f"unknown relationship type {rel}")
    for prop in re.findall(r"\b[A-Za-z_]\w*\.(\w+)\b", bare):
        if prop not in PROPERTIES and not prop.lower().startswith("fulltext"):
            # function namespaces like db.index are checked above
            if not re.search(rf"\b\w+\.{prop}\s*\(", bare):
                reasons.append(f"unknown property {prop}")
    for inline in re.findall(r"\{\s*(\w+)\s*:", bare):
        if inline not in PROPERTIES:
            reasons.append(f"unknown property {inline}")
    m = re.search(r"\bLIMIT\s+(\d+)\s*$", bare, flags=re.I)
    if m:
        if int(m.group(1)) > MAX_LIMIT:
            q = re.sub(r"\bLIMIT\s+\d+\s*$", f"LIMIT {MAX_LIMIT}", q, flags=re.I)
    elif not re.search(r"\bLIMIT\b", bare, flags=re.I):
        q = f"{q} LIMIT {MAX_LIMIT}"
    return GuardResult(ok=not reasons, query=q, reasons=sorted(set(reasons)))
