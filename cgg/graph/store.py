"""Neo4j access: idempotent load from the gold Delta tables, read-only query execution, snapshot hash."""

from __future__ import annotations

import json
import time
from functools import lru_cache

from cgg import config
from cgg.graph.cypher_guard import validate

KEY_PROP = {"Label": "set_id", "Section": "key"}  # every other node label is keyed by name

CONSTRAINTS = [
    "CREATE CONSTRAINT label_set_id IF NOT EXISTS FOR (n:Label) REQUIRE n.set_id IS UNIQUE",
    "CREATE CONSTRAINT section_key IF NOT EXISTS FOR (n:Section) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT pharmclass_name IF NOT EXISTS FOR (n:PharmClass) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT moa_name IF NOT EXISTS FOR (n:MoA) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT route_name IF NOT EXISTS FOR (n:Route) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT substance_name IF NOT EXISTS FOR (n:Substance) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT manufacturer_name IF NOT EXISTS FOR (n:Manufacturer) REQUIRE n.name IS UNIQUE",
    "CREATE INDEX label_generic IF NOT EXISTS FOR (n:Label) ON (n.generic_name)",
    "CREATE INDEX label_brand IF NOT EXISTS FOR (n:Label) ON (n.brand_name)",
    "CREATE FULLTEXT INDEX label_names IF NOT EXISTS FOR (n:Label) "
    "ON EACH [n.brand_name, n.generic_name, n.manufacturer]",
]


@lru_cache(maxsize=1)
def driver():
    from neo4j import GraphDatabase

    return GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.neo4j_password()))


def key_of(label: str) -> str:
    return KEY_PROP.get(label, "name")


def load_from_gold(spark=None, wipe: bool = True, batch: int = 2000) -> dict:
    from cgg.pipeline.medallion import TABLES
    from cgg.pipeline.spark import delta_version, get_spark

    spark = spark or get_spark()
    nodes = spark.read.format("delta").load(TABLES["gold.kg_nodes"]).collect()
    edges = spark.read.format("delta").load(TABLES["gold.kg_edges"]).collect()
    t0 = time.time()
    with driver().session() as s:
        if wipe:
            s.run("MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 5000 ROWS").consume()
        for c in CONSTRAINTS:
            s.run(c).consume()
        by_label: dict[str, list] = {}
        for r in nodes:
            by_label.setdefault(r["node_label"], []).append({"key": r["key"], "props": json.loads(r["props"])})
        for label, rows in by_label.items():
            k = key_of(label)
            for i in range(0, len(rows), batch):
                s.run(f"UNWIND $rows AS row MERGE (n:{label} {{{k}: row.key}}) SET n += row.props",
                      rows=rows[i:i + batch]).consume()
        by_rel: dict[tuple, list] = {}
        for r in edges:
            by_rel.setdefault((r["src_label"], r["rel"], r["dst_label"]), []).append(
                {"s": r["src_key"], "d": r["dst_key"], "props": json.loads(r["props"])})
        for (sl, rel, dl), rows in by_rel.items():
            for i in range(0, len(rows), batch):
                s.run(f"UNWIND $rows AS row MATCH (a:{sl} {{{key_of(sl)}: row.s}}) "
                      f"MATCH (b:{dl} {{{key_of(dl)}: row.d}}) MERGE (a)-[r:{rel}]->(b) SET r += row.props",
                      rows=rows[i:i + batch]).consume()
    snap = neo4j_snapshot_hash()
    from cgg.pipeline.medallion import kg_snapshot_hash

    gold_hash = kg_snapshot_hash(spark)
    report = {
        "nodes": len(nodes), "edges": len(edges), "load_s": round(time.time() - t0, 1),
        "neo4j_snapshot_sha256": snap, "gold_snapshot_sha256": gold_hash, "match": snap == gold_hash,
        "gold_delta_versions": {k: delta_version(spark, TABLES[k]) for k in ("gold.kg_nodes", "gold.kg_edges")},
        "counts_in_neo4j": counts(),
    }
    (config.RESULTS / "graph_load_report.json").write_text(json.dumps(report, indent=1))
    return report


def counts() -> dict:
    with driver().session() as s:
        n = {r["l"]: r["c"] for r in s.run("MATCH (n) RETURN labels(n)[0] AS l, count(*) AS c")}
        e = {r["t"]: r["c"] for r in s.run("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c")}
    return {"nodes": n, "edges": e}


def neo4j_snapshot_hash() -> str:
    from cgg.pipeline.medallion import snapshot_hash

    with driver().session() as s:
        nodes = [(r["l"], r["k"]) for r in s.run(
            "MATCH (n) RETURN labels(n)[0] AS l, CASE WHEN n:Section THEN n.key WHEN n:Label THEN n.set_id "
            "ELSE n.name END AS k")]
        edges = [tuple(r.values()) for r in s.run(
            "MATCH (a)-[r]->(b) RETURN labels(a)[0], CASE WHEN a:Section THEN a.key WHEN a:Label THEN a.set_id "
            "ELSE a.name END, type(r), labels(b)[0], CASE WHEN b:Section THEN b.key WHEN b:Label THEN b.set_id "
            "ELSE b.name END")]
    return snapshot_hash(nodes, edges)


class QueryRejected(Exception):
    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def run_read(query: str, params: dict | None = None, timeout_s: float = 10.0) -> tuple[str, list[dict]]:
    """Validate and run a query in a READ transaction. Returns (executed_query, rows)."""
    from neo4j import READ_ACCESS, unit_of_work

    g = validate(query)
    if not g.ok:
        raise QueryRejected(g.reasons)

    @unit_of_work(timeout=timeout_s)
    def work(tx):
        return [r.data() for r in tx.run(g.query, params or {})]

    with driver().session(default_access_mode=READ_ACCESS) as s:
        rows = s.execute_read(work)
    return g.query, rows


def run_trusted(query: str, params: dict | None = None) -> list[dict]:
    """Fixed, code-reviewed queries (entity resolution etc.). Still executed read-only."""
    from neo4j import READ_ACCESS

    with driver().session(default_access_mode=READ_ACCESS) as s:
        return s.execute_read(lambda tx: [r.data() for r in tx.run(query, params or {})])


def schema_lists() -> dict:
    """Value vocabularies injected into the text2cypher prompt."""
    q = {
        "pharm_classes": "MATCH (c:PharmClass) RETURN c.name AS v ORDER BY v",
        "routes": "MATCH (r:Route) RETURN r.name AS v ORDER BY v",
        "moas": "MATCH (m:MoA) RETURN m.name AS v ORDER BY v",
    }
    return {k: [r["v"] for r in run_trusted(v)] for k, v in q.items()}
