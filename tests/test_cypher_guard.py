import pytest

from cgg.graph.cypher_guard import extract_cypher, validate

pytestmark = pytest.mark.req("URS-009")

OK = [
    "MATCH (l:Label)-[:IN_CLASS]->(:PharmClass {name: 'Loop Diuretic'}) RETURN count(DISTINCT l) AS answer",
    "MATCH (l:Label)-[:MADE_BY]->(m:Manufacturer) WHERE l.generic_name = 'torsemide' RETURN DISTINCT m.name AS answer",
    "MATCH (l:Label) WHERE toLower(l.brand_name) = toLower('Set Me Free') RETURN l.has_boxed_warning AS answer",
]
BAD = [
    ("MATCH (n) DETACH DELETE n", "forbidden"),
    ("MATCH (l:Label) SET l.has_boxed_warning = false RETURN l", "forbidden"),
    ("CREATE (x:Label {set_id: '1'}) RETURN x", "forbidden"),
    ("MATCH (l:Label) RETURN l; MATCH (n) DELETE n", "multiple"),
    ("CALL dbms.listConfig() YIELD name RETURN name", "procedure"),
    ("MATCH (l:Patient) RETURN l", "unknown node label"),
    ("MATCH (l:Label)-[:TREATS]->(x) RETURN x", "unknown relationship"),
    ("MATCH (l:Label) RETURN l.ssn AS answer", "unknown property"),
    ("LOAD CSV FROM 'http://x' AS row MATCH (l:Label) RETURN row", "forbidden"),
    ("MATCH (l:Label) CALL { WITH l MATCH (l)-[:MADE_BY]->(m) RETURN m } RETURN m", "subquery"),
    ("RETURN 1", "MATCH"),
]


@pytest.mark.parametrize("q", OK)
def test_allowed_queries_pass_and_get_limit(q):
    r = validate(q)
    assert r.ok, r.reasons
    assert r.query.endswith("LIMIT 500")


def test_literal_text_does_not_trigger_keywords():
    r = validate("MATCH (l:Label) WHERE l.brand_name = 'SET DELETE CREATE' RETURN l.set_id AS answer")
    assert r.ok, r.reasons


@pytest.mark.parametrize("q,why", BAD)
def test_rejected_queries(q, why):
    r = validate(q)
    assert not r.ok
    assert any(why.lower() in x.lower() for x in r.reasons), r.reasons


def test_limit_is_capped():
    assert validate("MATCH (l:Label) RETURN l.set_id AS answer LIMIT 100000").query.endswith("LIMIT 500")


def test_extract_from_fenced_reply():
    assert extract_cypher("```cypher\nMATCH (l:Label) RETURN l\n```\nThis query...") == "MATCH (l:Label) RETURN l"
