"""Bronze -> silver -> gold pipeline on PySpark + Delta Lake.

bronze/labels      one row per downloaded label record, raw JSON + sha256 + fetch metadata (append-only history)
silver/labels      one row per label (set_id), typed and de-duplicated, passed all quarantine expectations
silver/sections    one row per label x section, cleaned text
silver/quarantine  rows that failed an expectation, with the failed expectation names
gold/chunks        retrieval chunks with a context header for embedding
gold/kg_nodes      knowledge graph nodes derived from structured openFDA fields
gold/kg_edges      knowledge graph edges (structured, plus dictionary-extracted interaction mentions with provenance)
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone

import pandas as pd

from cgg import config
from cgg.fetch import MANIFEST
from cgg.pipeline.expectations import LABEL_EXPECTATIONS, SECTION_EXPECTATIONS, split_sql
from cgg.pipeline.spark import delta_version, get_spark, table_path

TABLES = {
    "bronze.labels": table_path("bronze", "labels"),
    "silver.labels": table_path("silver", "labels"),
    "silver.sections": table_path("silver", "sections"),
    "silver.quarantine": table_path("silver", "quarantine"),
    "gold.chunks": table_path("gold", "chunks"),
    "gold.kg_nodes": table_path("gold", "kg_nodes"),
    "gold.kg_edges": table_path("gold", "kg_edges"),
}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# --------------------------------------------------------------------------- bronze
def bronze(spark, run_id: str, raw_dir=config.RAW_DIR, manifest_path=MANIFEST) -> dict:
    from pyspark.sql import types as T

    manifest = json.loads(manifest_path.read_text())
    rows = []
    for e in manifest["files"]:
        raw = (raw_dir / e["file"]).read_bytes()
        if _sha(raw) != e["sha256"]:
            raise RuntimeError(f"raw file {e['file']} does not match its manifest sha256")
        for rec in json.loads(raw).get("results", []):
            rj = json.dumps(rec, sort_keys=True)
            rows.append((run_id, manifest["fetched_at_utc"], e["file"], e["sha256"], e["epc"],
                         json.dumps(e["request"], sort_keys=True), rec.get("set_id"), rec.get("id"),
                         _sha(rj.encode()), rj))
    schema = T.StructType([T.StructField(n, T.StringType()) for n in (
        "ingest_run_id", "fetched_at_utc", "source_file", "source_file_sha256", "query_epc", "request",
        "set_id", "label_id", "record_sha256", "raw_json")])
    df = spark.createDataFrame(rows, schema).withColumn("ingested_at_utc", _now_col())
    # Append-only: earlier ingests stay queryable with Delta time travel.
    df.write.format("delta").mode("append").save(TABLES["bronze.labels"])
    return {"rows": len(rows)}


def _now_col():
    from pyspark.sql import functions as F

    return F.lit(datetime.now(timezone.utc).isoformat(timespec="seconds"))


# --------------------------------------------------------------------------- silver
def _label_schema():
    from pyspark.sql import types as T

    arr = T.ArrayType(T.StringType())
    openfda = T.StructType([T.StructField(f, arr) for f in (
        "brand_name", "generic_name", "manufacturer_name", "route", "pharm_class_epc", "pharm_class_moa",
        "pharm_class_pe", "substance_name", "product_type", "application_number")])
    fields = [T.StructField(f, T.StringType()) for f in ("set_id", "id", "version", "effective_time")]
    fields.append(T.StructField("openfda", openfda))
    fields += [T.StructField(s, arr) for s in config.SECTIONS]
    return T.StructType(fields)


def silver(spark, run_id: str) -> dict:
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    b = spark.read.format("delta").load(TABLES["bronze.labels"]).where(F.col("ingest_run_id") == run_id)
    p = b.select("set_id", "record_sha256", "source_file_sha256", "query_epc",
                 F.from_json("raw_json", _label_schema()).alias("r"))
    scope = F.array(*[F.lit(c) for c in config.SCOPE_EPC])
    strip = "transform({col}, x -> regexp_replace(x, '\\\\s*\\\\[(EPC|MoA|PE|CS)\\\\]$', ''))"
    sections_present = F.filter(
        F.array(*[F.when(F.size(F.col(f"r.{s}")) > 0, F.lit(s)) for s in config.SECTIONS]),
        lambda x: x.isNotNull())
    labels = p.select(
        "set_id", "record_sha256", "source_file_sha256",
        F.col("r.id").alias("label_id"),
        F.col("r.version").cast("int").alias("version"),
        F.to_date("r.effective_time", "yyyyMMdd").alias("effective_date"),
        F.col("r.openfda.brand_name")[0].alias("brand_name"),
        F.lower(F.col("r.openfda.generic_name")[0]).alias("generic_name"),
        F.col("r.openfda.manufacturer_name")[0].alias("manufacturer"),
        F.coalesce(F.col("r.openfda.route"), F.array()).alias("routes"),
        F.coalesce(F.expr(strip.format(col="r.openfda.pharm_class_epc")), F.array()).alias("epc"),
        F.coalesce(F.expr(strip.format(col="r.openfda.pharm_class_moa")), F.array()).alias("moa"),
        F.coalesce(F.transform("r.openfda.substance_name", F.lower), F.array()).alias("substances"),
        F.col("r.openfda.product_type")[0].alias("product_type"),
        F.col("r.openfda.application_number")[0].alias("application_number"),
        (F.size(F.coalesce(F.col("r.boxed_warning"), F.array())) > 0).alias("has_boxed_warning"),
        sections_present.alias("sections_present"),
    ).withColumn("epc_in_scope", F.array_intersect("epc", scope))

    n_records = labels.count()
    w = Window.partitionBy("set_id").orderBy(F.desc("version"), F.desc("effective_date"), "record_sha256")
    ranked = labels.withColumn("_rn", F.row_number().over(w))
    dedup = ranked.where("_rn = 1").drop("_rn")
    n_dupes = n_records - dedup.count()

    pass_sql, failed_sql = split_sql(LABEL_EXPECTATIONS)
    checked = dedup.withColumn("_failed", F.expr(failed_sql))
    good = checked.where(F.expr(pass_sql)).drop("_failed").withColumn("ingest_run_id", F.lit(run_id))
    bad = checked.where(~F.expr(pass_sql))
    exp_counts = {}
    for e in LABEL_EXPECTATIONS:
        exp_counts[e.name] = {"action": e.action, "urs": e.urs,
                              "failed": dedup.where(~F.coalesce(F.expr(e.sql), F.lit(False))).count()}

    good.write.format("delta").mode("overwrite").option("overwriteSchema", "true").save(TABLES["silver.labels"])
    q_labels = bad.select(F.lit("silver.labels").alias("target_table"), F.col("set_id").alias("record_key"),
                          F.col("_failed").alias("failed_expectations"),
                          F.to_json(F.struct(*[c for c in dedup.columns])).alias("payload"))

    # sections: one row per label x section, from the de-duplicated passing labels only
    keep = good.select("set_id", "record_sha256")
    sec_struct = F.array(*[F.struct(F.lit(s).alias("section"),
                                    F.concat_ws("\n", F.col(f"r.{s}")).alias("raw_text")) for s in config.SECTIONS])
    secs = (p.dropDuplicates(["set_id", "record_sha256"]).join(keep, ["set_id", "record_sha256"], "inner")
            .select("set_id", F.explode(sec_struct).alias("s"))
            .select("set_id", "s.section", "s.raw_text")
            .where(F.length("raw_text") > 0))
    secs = secs.withColumn("text", _clean_udf()("raw_text")).drop("raw_text")
    spass, sfailed = split_sql(SECTION_EXPECTATIONS)
    secs_checked = secs.withColumn("_failed", F.expr(sfailed))
    secs_good = (secs_checked.where(F.expr(spass)).drop("_failed")
                 .withColumn("text_sha256", F.sha2("text", 256)).withColumn("n_chars", F.length("text"))
                 .withColumn("ingest_run_id", F.lit(run_id)))
    secs_bad = secs_checked.where(~F.expr(spass))
    for e in SECTION_EXPECTATIONS:
        exp_counts[e.name] = {"action": e.action, "urs": e.urs,
                              "failed": secs.where(~F.coalesce(F.expr(e.sql), F.lit(False))).count()}
    secs_good.write.format("delta").mode("overwrite").option("overwriteSchema", "true").save(
        TABLES["silver.sections"])
    q_secs = secs_bad.select(F.lit("silver.sections").alias("target_table"),
                             F.concat_ws(":", "set_id", "section").alias("record_key"),
                             F.col("_failed").alias("failed_expectations"),
                             F.to_json(F.struct("set_id", "section", F.substring("text", 1, 500).alias("text"))
                                       ).alias("payload"))
    quarantine = q_labels.unionByName(q_secs).withColumn("ingest_run_id", F.lit(run_id)).withColumn(
        "quarantined_at_utc", _now_col())
    quarantine.write.format("delta").mode("append").save(TABLES["silver.quarantine"])
    return {
        "label_records_in": n_records,
        "duplicate_records_removed": n_dupes,
        "labels_passed": good.count(),
        "labels_quarantined": bad.count(),
        "sections_passed": secs_good.count(),
        "sections_quarantined": secs_bad.count(),
        "expectations": exp_counts,
    }


def _clean_series(s: pd.Series) -> pd.Series:
    from cgg.pipeline.text import clean_text, strip_heading

    return s.map(lambda x: strip_heading(clean_text(x)))


def _clean_udf():
    from pyspark.sql.functions import PandasUDFType, pandas_udf

    return pandas_udf(_clean_series, "string", PandasUDFType.SCALAR)


# --------------------------------------------------------------------------- gold
def gold(spark, run_id: str) -> dict:
    from pyspark.sql import functions as F

    labels = spark.read.format("delta").load(TABLES["silver.labels"])
    secs = spark.read.format("delta").load(TABLES["silver.sections"])
    meta = labels.select("set_id", "brand_name", "generic_name", "manufacturer")
    joined = secs.join(meta, "set_id")
    size, overlap = config.CHUNK_CHARS, config.CHUNK_OVERLAP

    def chunker(it):
        from cgg.pipeline.text import chunk_text

        for pdf in it:
            out = []
            for r in pdf.itertuples(index=False):
                for i, (a, b, t) in enumerate(chunk_text(r.text, size, overlap)):
                    header = f"{r.brand_name} ({r.generic_name}), {r.manufacturer}, section {r.section}: "
                    out.append((f"{r.set_id}:{r.section}:{i}", r.set_id, r.section, i, a, b, t, header + t,
                                r.brand_name, r.generic_name, r.manufacturer))
            yield pd.DataFrame(out, columns=["chunk_id", "set_id", "section", "chunk_index", "char_start",
                                             "char_end", "text", "embed_text", "brand_name", "generic_name",
                                             "manufacturer"])

    chunk_schema = ("chunk_id string, set_id string, section string, chunk_index int, char_start int, "
                    "char_end int, text string, embed_text string, brand_name string, generic_name string, "
                    "manufacturer string")
    chunks = joined.mapInPandas(chunker, chunk_schema).withColumn("ingest_run_id", F.lit(run_id))
    chunks.write.format("delta").mode("overwrite").option("overwriteSchema", "true").save(TABLES["gold.chunks"])

    # ---- knowledge graph tables (deterministic, from structured openFDA fields)
    lab_props = F.to_json(F.struct("set_id", "label_id", "version", F.col("effective_date").cast("string").alias(
        "effective_date"), "brand_name", "generic_name", "manufacturer", "has_boxed_warning", "application_number"))
    nodes = [labels.select(F.lit("Label").alias("node_label"), F.col("set_id").alias("key"),
                           lab_props.alias("props"))]
    edges = []
    rels = [("epc", "PharmClass", "IN_CLASS"), ("moa", "MoA", "HAS_MOA"), ("routes", "Route", "HAS_ROUTE"),
            ("substances", "Substance", "CONTAINS")]
    for col, nlabel, rel in rels:
        ex = labels.select("set_id", F.explode(col).alias("v")).where(F.col("v").isNotNull()).distinct()
        nodes.append(ex.select(F.lit(nlabel).alias("node_label"), F.col("v").alias("key"),
                               F.to_json(F.struct(F.col("v").alias("name"))).alias("props")).distinct())
        edges.append(ex.select(F.lit("Label").alias("src_label"), F.col("set_id").alias("src_key"),
                               F.lit(rel).alias("rel"), F.lit(nlabel).alias("dst_label"), F.col("v").alias("dst_key"),
                               F.lit('{"source":"openfda","extracted":false}').alias("props")))
    mf = labels.select("set_id", "manufacturer").distinct()
    nodes.append(mf.select(F.lit("Manufacturer").alias("node_label"), F.col("manufacturer").alias("key"),
                           F.to_json(F.struct(F.col("manufacturer").alias("name"))).alias("props")).distinct())
    edges.append(mf.select(F.lit("Label").alias("src_label"), F.col("set_id").alias("src_key"),
                           F.lit("MADE_BY").alias("rel"), F.lit("Manufacturer").alias("dst_label"),
                           F.col("manufacturer").alias("dst_key"),
                           F.lit('{"source":"openfda","extracted":false}').alias("props")))
    sec_nodes = secs.select(F.lit("Section").alias("node_label"),
                            F.concat_ws(":", "set_id", "section").alias("key"),
                            F.to_json(F.struct("set_id", F.col("section").alias("name"), "n_chars",
                                               "text_sha256")).alias("props"))
    nodes.append(sec_nodes)
    edges.append(secs.select(F.lit("Label").alias("src_label"), F.col("set_id").alias("src_key"),
                             F.lit("HAS_SECTION").alias("rel"), F.lit("Section").alias("dst_label"),
                             F.concat_ws(":", "set_id", "section").alias("dst_key"),
                             F.lit('{"source":"openfda","extracted":false}').alias("props")))

    # Dictionary-extracted interaction mentions (not LLM): substance names of the corpus found as whole words in
    # another label's drug_interactions section. Marked extracted=true with method and section as provenance.
    subs = labels.select(F.explode("substances").alias("sub")).distinct().where(F.length("sub") >= 5)
    di = secs.where(F.col("section") == "drug_interactions").select("set_id", F.lower("text").alias("t"))
    own = labels.select("set_id", "substances")
    hits = (di.crossJoin(subs).where(F.expr("t rlike concat('\\\\b', sub, '\\\\b')"))
            .join(own, "set_id").where(~F.array_contains("substances", F.col("sub"))))
    edges.append(hits.select(F.lit("Label").alias("src_label"), F.col("set_id").alias("src_key"),
                             F.lit("MENTIONS_INTERACTION_WITH").alias("rel"), F.lit("Substance").alias("dst_label"),
                             F.col("sub").alias("dst_key"),
                             F.lit('{"source":"drug_interactions","extracted":true,"method":"dictionary-match-v1"}'
                                   ).alias("props")))
    nodes.append(hits.select(F.lit("Substance").alias("node_label"), F.col("sub").alias("key"),
                             F.to_json(F.struct(F.col("sub").alias("name"))).alias("props")))

    all_nodes = nodes[0]
    for n in nodes[1:]:
        all_nodes = all_nodes.unionByName(n)
    all_nodes = all_nodes.dropDuplicates(["node_label", "key"]).withColumn("ingest_run_id", F.lit(run_id))
    all_edges = edges[0]
    for e in edges[1:]:
        all_edges = all_edges.unionByName(e)
    all_edges = all_edges.dropDuplicates(["src_label", "src_key", "rel", "dst_label", "dst_key"]).withColumn(
        "ingest_run_id", F.lit(run_id))
    all_nodes.write.format("delta").mode("overwrite").option("overwriteSchema", "true").save(TABLES["gold.kg_nodes"])
    all_edges.write.format("delta").mode("overwrite").option("overwriteSchema", "true").save(TABLES["gold.kg_edges"])
    n_nodes = spark.read.format("delta").load(TABLES["gold.kg_nodes"])
    n_edges = spark.read.format("delta").load(TABLES["gold.kg_edges"])
    return {
        "chunks": spark.read.format("delta").load(TABLES["gold.chunks"]).count(),
        "kg_nodes": n_nodes.count(),
        "kg_edges": n_edges.count(),
        "kg_nodes_by_label": {r["node_label"]: r["count"] for r in n_nodes.groupBy("node_label").count().collect()},
        "kg_edges_by_rel": {r["rel"]: r["count"] for r in n_edges.groupBy("rel").count().collect()},
        "kg_snapshot_sha256": kg_snapshot_hash(spark),
    }


def kg_snapshot_hash(spark) -> str:
    """sha256 over the sorted node keys and edge triples (structure only), comparable with the Neo4j side."""
    nodes = spark.read.format("delta").load(TABLES["gold.kg_nodes"]).select("node_label", "key").collect()
    edges = spark.read.format("delta").load(TABLES["gold.kg_edges"]).select(
        "src_label", "src_key", "rel", "dst_label", "dst_key").collect()
    return snapshot_hash([(r[0], r[1]) for r in nodes], [tuple(r) for r in edges])


def snapshot_hash(nodes: list[tuple], edges: list[tuple]) -> str:
    h = hashlib.sha256()
    for n in sorted(nodes):
        h.update(("N|" + "|".join(map(str, n)) + "\n").encode())
    for e in sorted(edges):
        h.update(("E|" + "|".join(map(str, e)) + "\n").encode())
    return h.hexdigest()


# --------------------------------------------------------------------------- orchestration
def run() -> dict:
    spark = get_spark()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    t0 = time.time()
    report: dict = {"ingest_run_id": run_id, "spark_version": spark.version}
    report["bronze"] = bronze(spark, run_id)
    report["silver"] = silver(spark, run_id)
    report["gold"] = gold(spark, run_id)
    report["delta_versions"] = {k: delta_version(spark, v) for k, v in TABLES.items()}
    report["duration_s"] = round(time.time() - t0, 1)
    import delta

    report["delta_spark_version"] = getattr(delta, "__version__", "3.2.1")
    report["raw_manifest_sha256"] = _sha(MANIFEST.read_bytes())
    config.RESULTS.mkdir(exist_ok=True)
    (config.RESULTS / "pipeline_report.json").write_text(json.dumps(report, indent=1, default=str))
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=1, default=str))


def export_serving(spark=None) -> dict:
    """Snapshot silver labels/sections to parquet for the serving and evaluation processes (no JVM needed there).
    The Delta versions they were read from are recorded next to them."""
    spark = spark or get_spark()
    config.GOLD_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, key in (("labels", "silver.labels"), ("sections", "silver.sections")):
        pdf = spark.read.format("delta").load(TABLES[key]).toPandas()
        p = config.GOLD_DIR / f"{name}.parquet"
        pdf.to_parquet(p, index=False)
        out[name] = {"rows": len(pdf), "delta_table": key, "delta_version": delta_version(spark, TABLES[key]),
                     "sha256": _sha(p.read_bytes())}
    (config.GOLD_DIR / "serving_manifest.json").write_text(json.dumps(out, indent=1))
    return out
