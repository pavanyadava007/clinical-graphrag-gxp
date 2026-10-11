"""The three systems compared on the same gold set.

A  VectorRAG        top-k chunks over the whole corpus -> answer prompt
B  GraphRAG         LLM router -> (graph) text2cypher + read-only validator + Neo4j
                                  (text)  graph entity resolution -> label-scoped vector retrieval -> answer prompt
C  GuardedGraphRAG  B + injection filter, safety policy, repair loop, label ambiguity check,
                    citation verification, and escalation of low-confidence answers to the HITL queue
"""

from __future__ import annotations

import re
import time

from cgg import promptlib
from cgg.embed import index
from cgg.graph import store
from cgg.graph.cypher_guard import extract_cypher
from cgg.guards import check_citations, screen_rules
from cgg.llm import LLMError, parse_json
from cgg.systems.base import Answer, LLMCaller, SystemConfig, format_context, parse_answer_json, rows_to_answer
from cgg.tracing import Trace, Tracer

REFUSAL = ("This tool only reports what FDA drug labels state. The question was not answered: {reason}. "
           "Please contact the medical information team.")


class VectorRAG:
    name = "A_vector_rag"

    def __init__(self, cfg: SystemConfig | None = None, tracer: Tracer | None = None):
        self.cfg = cfg or SystemConfig()
        self.tracer = tracer or Tracer(enabled=False)
        self.caller = LLMCaller(self.cfg)

    def ask(self, question: str, meta: dict | None = None) -> Answer:
        ans = Answer(system=self.name, question=question)
        trace = self.tracer.trace(self.name, question, metadata={**(meta or {}), **self.cfg.as_params()},
                                  tags=[self.name])
        t0 = time.time()
        try:
            self._answer(ans, trace)
        except LLMError as e:
            ans.status, ans.reason = "error", f"llm: {e}"
        except Exception as e:  # noqa: BLE001 - every failure is recorded as an error outcome
            ans.status, ans.reason = "error", f"{type(e).__name__}: {e}"
        ans.latency_s = round(time.time() - t0, 3)
        ans.trace_id, ans.spans = trace.id, trace.to_dict()
        trace.end({"status": ans.status, "answer": ans.answer}, {"route": ans.route})
        return ans

    def _retrieve(self, ans: Answer, trace: Trace, question: str, set_ids=None) -> list[dict]:
        with trace.span("retrieve", input={"question": question, "set_ids": set_ids}) as sp:
            chunks = index().search(question, k=self.cfg.top_k, set_ids=set_ids)
            sp.output = [{"chunk_id": c["chunk_id"], "score": round(c["score"], 4)} for c in chunks]
        return chunks

    def _compose(self, ans: Answer, trace: Trace, question: str, chunks: list[dict], extra: str = ""):
        p = promptlib.load("answer", self.cfg.prompts["answer"])
        res = self.caller.call(ans, trace, p, "generate", json_mode=True, max_tokens=1000, extra_user=extra,
                               question=question, context=format_context(chunks))
        try:
            ans.answer, ans.citations = parse_answer_json(res.text)
        except ValueError:
            ans.answer, ans.citations = res.text.strip(), []
            ans.checks["json_parse_failed"] = True

    def _answer(self, ans: Answer, trace: Trace):
        ans.route = "vector"
        chunks = self._retrieve(ans, trace, ans.question)
        self._compose(ans, trace, ans.question, chunks)


class GraphRAG(VectorRAG):
    name = "B_graphrag"

    def _route(self, ans: Answer, trace: Trace) -> dict:
        p = promptlib.load("router", self.cfg.prompts["router"])
        with trace.span("route", input=ans.question) as sp:
            res = self.caller.call(ans, trace, p, "router", json_mode=True, max_tokens=120, question=ans.question)
            try:
                d = parse_json(res.text)
            except ValueError:
                d = {}
            route = d.get("route") if d.get("route") in ("graph", "text") else "text"
            out = {"route": route, "brand": d.get("brand") or None, "manufacturer": d.get("manufacturer") or None}
            sp.output = out
        return out

    def _cypher(self, ans: Answer, trace: Trace, feedback: str = "") -> list[dict]:
        p = promptlib.load("text2cypher", self.cfg.prompts["text2cypher"])
        vocab = _vocab()
        res = self.caller.call(ans, trace, p, "text2cypher", json_mode=False, max_tokens=300, extra_user=feedback,
                               question=ans.question, pharm_classes=", ".join(vocab["pharm_classes"]),
                               routes=", ".join(vocab["routes"]))
        q = extract_cypher(res.text)
        with trace.span("cypher", input=q) as sp:
            try:
                executed, rows = store.run_read(q)
                ans.cypher, ans.rows = executed, rows
                sp.output = {"n_rows": len(rows), "rows": rows[:20]}
                return rows
            except store.QueryRejected as e:
                ans.cypher = q
                sp.output = {"rejected": e.reasons}
                sp.level = "WARNING"
                ans.checks.setdefault("cypher_rejections", []).append(e.reasons)
                raise
            except Exception as e:
                ans.cypher = q
                sp.output = {"neo4j_error": str(e)[:300]}
                sp.level = "WARNING"
                ans.checks.setdefault("cypher_errors", []).append(str(e)[:200])
                raise

    def _resolve(self, ans: Answer, trace: Trace, brand: str | None, mfr: str | None) -> list[str]:
        with trace.span("resolve_label", input={"brand": brand, "manufacturer": mfr}) as sp:
            ids = resolve_label(brand, mfr)
            ans.resolved_set_ids = ids
            sp.output = ids
        return ids

    def _graph_answer(self, ans: Answer, trace: Trace) -> bool:
        try:
            rows = self._cypher(ans, trace)
        except Exception:
            return False
        ans.answer = rows_to_answer(rows)
        return True

    def _text_answer(self, ans: Answer, trace: Trace, r: dict):
        ids = self._resolve(ans, trace, r["brand"], r["manufacturer"]) if r["brand"] else []
        chunks = self._retrieve(ans, trace, ans.question, set_ids=ids[:3] or None)
        self._compose(ans, trace, ans.question, chunks)

    def _answer(self, ans: Answer, trace: Trace):
        r = self._route(ans, trace)
        ans.route = r["route"]
        if r["route"] == "graph" and self._graph_answer(ans, trace):
            return
        if r["route"] == "graph":
            ans.route = "graph->text_fallback"
        self._text_answer(ans, trace, r)


class GuardedGraphRAG(GraphRAG):
    name = "C_guarded_graphrag"

    def __init__(self, cfg: SystemConfig | None = None, tracer: Tracer | None = None, queue=None):
        super().__init__(cfg, tracer)
        self.queue = queue  # cgg.hitl.ReviewQueue or None

    def _escalate(self, ans: Answer, reason: str):
        ans.status, ans.reason = "escalated", reason

    def _refuse(self, ans: Answer, reason: str):
        ans.status, ans.reason = "refused", reason
        ans.answer = REFUSAL.format(reason=reason)

    def ask(self, question: str, meta: dict | None = None) -> Answer:
        ans = super().ask(question, meta)
        if ans.status == "escalated" and self.queue is not None:
            ans.checks["review_id"] = self.queue.submit(ans, meta or {})
        return ans

    def _screen(self, ans: Answer, trace: Trace) -> bool:
        with trace.span("guard_input", input=ans.question) as sp:
            rule = screen_rules(ans.question)
            sp.output = {"rule_category": rule.category}
        if rule.category == "injection":
            self._refuse(ans, "possible prompt or query injection")
            return False
        if rule.category == "harmful":
            self._refuse(ans, "request outside safe use of label information")
            return False
        if rule.category == "patient_specific":
            self._escalate(ans, "patient-specific question, routed to a medical information specialist")
            return False
        p = promptlib.load("safety", self.cfg.prompts["safety"])
        with trace.span("guard_policy", input=ans.question) as sp:
            res = self.caller.call(ans, trace, p, "safety_policy", json_mode=True, max_tokens=80,
                                   question=ans.question)
            try:
                cat = str(parse_json(res.text).get("category", "")).strip().lower()
            except ValueError:
                cat = "unparseable"
            sp.output = {"llm_category": cat}
        ans.checks["policy_category"] = cat
        if cat in ("injection", "harmful", "out_of_domain"):
            self._refuse(ans, {"injection": "possible prompt or query injection",
                               "harmful": "request outside safe use of label information",
                               "out_of_domain": "question is not about drug label content"}[cat])
            return False
        if cat in ("patient_specific", "off_label"):
            self._escalate(ans, f"{cat.replace('_', '-')} question, routed to a medical information specialist")
            return False
        if cat != "in_scope":
            self._escalate(ans, "safety policy could not classify the question")
            return False
        return True

    def _answer(self, ans: Answer, trace: Trace):
        if not self._screen(ans, trace):
            return
        r = self._route(ans, trace)
        ans.route = r["route"]
        if r["brand"] and r["manufacturer"]:
            # a specific product is named: it must resolve to exactly one label, otherwise a human decides
            ids = self._resolve(ans, trace, r["brand"], r["manufacturer"])
            if len(ids) != 1:
                self._escalate(ans, f"named label resolves to {len(ids)} labels")
                return
        if r["route"] == "graph":
            self._guarded_graph(ans, trace)
        else:
            self._guarded_text(ans, trace)

    def _guarded_graph(self, ans: Answer, trace: Trace):
        feedback = ""
        for attempt in range(2):
            try:
                rows = self._cypher(ans, trace, feedback)
            except store.QueryRejected as e:
                feedback = (f"Your previous query was rejected by the validator: {'; '.join(e.reasons)}. "
                            "Write a corrected read-only query.")
                continue
            except Exception as e:  # noqa: BLE001
                feedback = f"Your previous query failed in Neo4j: {str(e)[:200]}. Write a corrected query."
                continue
            value = rows_to_answer(rows) if rows else None
            if value not in ([], None) and not (isinstance(value, int) and not isinstance(value, bool)
                                                and value == 0):
                ans.answer = value
                ans.checks["cypher_attempts"] = attempt + 1
                return
            # an empty list or a zero count is treated as low confidence: one repair, then a human decides
            feedback = ("Your previous query returned no rows or a count of 0. Check the relationship directions, "
                        "the class, route and name spelling against the valid values and write a corrected query.")
        ans.checks["cypher_attempts"] = 2
        self._escalate(ans, "graph query failed or returned nothing after one repair")

    def _guarded_text(self, ans: Answer, trace: Trace):
        ids = ans.resolved_set_ids or []
        if not ids:
            self._escalate(ans, "text question without an identifiable label")
            return
        chunks = self._retrieve(ans, trace, ans.question, set_ids=ids)
        extra = ""
        for attempt in range(2):
            self._compose(ans, trace, ans.question, chunks, extra=extra)
            with trace.span("guard_citations", input=ans.citations) as sp:
                chk = check_citations(ans.citations, allowed_set_ids=set(ids))
                sp.output = chk
            ans.checks["citation_check"] = chk
            if ans.answer not in (None, "", []) and chk["all_valid"]:
                ans.checks["compose_attempts"] = attempt + 1
                return
            extra = ("Your previous answer failed the citation check "
                     f"({'; '.join(chk['reasons']) or 'no citation or empty answer'}). "
                     "Copy the quote word for word from one excerpt and cite its set_id and section.")
        ans.checks["compose_attempts"] = 2
        self._escalate(ans, "answer could not be verified against the cited label text")


_VOCAB: dict | None = None


def _vocab() -> dict:
    global _VOCAB
    if _VOCAB is None:
        _VOCAB = store.schema_lists()
    return _VOCAB


def _lucene_escape(s: str) -> str:
    return re.sub(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)', r"\\\1", s)


def resolve_label(brand: str | None, mfr: str | None) -> list[str]:
    """Resolve a named product to label set_ids with fixed, reviewed queries (not LLM-written)."""
    if not brand:
        return []
    rows = store.run_trusted(
        "MATCH (l:Label) WHERE toLower(l.brand_name) = toLower($b) "
        "AND ($m IS NULL OR toLower(l.manufacturer) = toLower($m)) RETURN l.set_id AS s ORDER BY s",
        {"b": brand.strip(), "m": mfr.strip() if mfr else None})
    if rows:
        return [r["s"] for r in rows]
    q = " ".join(f"{_lucene_escape(t)}~" for t in re.findall(r"\w+", f"{brand} {mfr or ''}") if len(t) > 2)
    if not q:
        return []
    rows = store.run_trusted(
        "CALL db.index.fulltext.queryNodes('label_names', $q) YIELD node, score "
        "RETURN node.set_id AS s, score ORDER BY score DESC LIMIT 5", {"q": q})
    if not rows:
        return []
    top = rows[0]["score"]
    return [r["s"] for r in rows if r["score"] >= 0.95 * top]


SYSTEMS = {"A": VectorRAG, "B": GraphRAG, "C": GuardedGraphRAG}
