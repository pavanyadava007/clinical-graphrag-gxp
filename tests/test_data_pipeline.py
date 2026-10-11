"""Fetch manifest checks (no network) and the Spark medallion pipeline on a small synthetic fixture."""

import hashlib
import json
import shutil

import pytest

from cgg import fetch
from cgg.pipeline.expectations import LABEL_EXPECTATIONS, split_sql


def _label(set_id, version, generic, epc, boxed=True, eff="20250101", contraind="Do not use in active bleeding."):
    rec = {"set_id": set_id, "id": f"id-{set_id[:4]}-{version}", "version": str(version), "effective_time": eff,
           "openfda": {"brand_name": [generic.upper()], "generic_name": [generic.upper()],
                       "manufacturer_name": ["Maker Inc."], "route": ["ORAL"],
                       "pharm_class_epc": [f"{epc} [EPC]"], "pharm_class_moa": ["Factor Xa Inhibitors [MoA]"],
                       "substance_name": [generic.upper()], "product_type": ["HUMAN PRESCRIPTION DRUG"]},
           "indications_and_usage": ["1 INDICATIONS AND USAGE The drug is indicated to reduce the risk of stroke."],
           "contraindications": [contraind],
           "drug_interactions": ["Avoid use with other drugs. Concomitant use with warfarin increases bleeding."]}
    if boxed:
        rec["boxed_warning"] = ["WARNING: BLEEDING RISK. The drug can cause serious and fatal bleeding."]
    return rec


def _write_fixture(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    sid = lambda n: f"{n:08d}-0000-0000-0000-000000000000"  # noqa: E731
    files = {
        "a.json": [_label(sid(1), 1, "apixaban", "Factor Xa Inhibitor"),
                   _label(sid(1), 3, "apixaban", "Factor Xa Inhibitor"),  # newer version of the same label
                   _label(sid(2), 1, "warfarin", "Factor Xa Inhibitor", boxed=False, contraind="None.")],
        "b.json": [_label(sid(3), 2, "nifedipine", "Dihydropyridine Calcium Channel Blocker")],  # out of scope
    }
    entries = []
    for name, recs in files.items():
        b = json.dumps({"results": recs}, sort_keys=True).encode()
        (raw / name).write_bytes(b)
        entries.append({"file": name, "epc": "Factor Xa Inhibitor", "request": {"search": "x"},
                        "sha256": hashlib.sha256(b).hexdigest()})
    man = tmp_path / "manifest.json"
    man.write_text(json.dumps({"fetched_at_utc": "2026-10-11T00:00:00+00:00", "files": entries}))
    return raw, man


@pytest.mark.req("URS-001")
@pytest.mark.req("URS-002")
def test_manifest_detects_changed_raw_file(tmp_path, monkeypatch):
    raw, man = _write_fixture(tmp_path)
    monkeypatch.setattr(fetch, "MANIFEST", man)
    assert fetch.verify(raw) == []
    (raw / "a.json").write_bytes(b'{"results": []}')
    assert fetch.verify(raw) == ["a.json"]


@pytest.mark.req("URS-001")
def test_committed_manifest_records_query_time_and_hashes():
    m = json.loads(fetch.MANIFEST.read_text())
    assert m["fetched_at_utc"] and m["n_files"] == len(m["files"]) > 0
    for e in m["files"]:
        assert len(e["sha256"]) == 64 and e["request"]["search"] and e["request"]["url"].startswith("https://")


@pytest.mark.req("URS-004")
def test_expectation_sql_lists_failed_names():
    pass_sql, failed_sql = split_sql(LABEL_EXPECTATIONS)
    assert "epc_in_scope" in failed_sql and "has_indications_section" not in failed_sql  # warn-only
    assert pass_sql.count("coalesce") == sum(e.action == "quarantine" for e in LABEL_EXPECTATIONS)


@pytest.fixture(scope="module")
def spark():
    if shutil.which("java") is None:
        pytest.skip("Java not installed")
    from cgg.pipeline.spark import get_spark

    return get_spark("cgg-tests")


@pytest.mark.spark
@pytest.mark.req("URS-002")
@pytest.mark.req("URS-003")
@pytest.mark.req("URS-004")
@pytest.mark.req("URS-005")
@pytest.mark.req("URS-006")
def test_medallion_on_fixture(spark, tmp_path, monkeypatch):
    from cgg.pipeline import medallion
    from cgg.pipeline.spark import delta_version

    raw, man = _write_fixture(tmp_path)
    for k in list(medallion.TABLES):
        layer, name = k.split(".")
        monkeypatch.setitem(medallion.TABLES, k, str(tmp_path / "lake" / layer / name))
    assert medallion.bronze(spark, "run1", raw, man)["rows"] == 4
    s = medallion.silver(spark, "run1")
    assert s["duplicate_records_removed"] == 1 and s["labels_passed"] == 2 and s["labels_quarantined"] == 1
    assert s["expectations"]["epc_in_scope"]["failed"] == 1
    assert s["sections_quarantined"] == 1  # the too-short "None." contraindications section
    labels = {r.set_id: r for r in spark.read.format("delta").load(medallion.TABLES["silver.labels"]).collect()}
    assert labels["00000001-0000-0000-0000-000000000000"].version == 3
    q = spark.read.format("delta").load(medallion.TABLES["silver.quarantine"]).collect()
    assert {tuple(r.failed_expectations) for r in q} == {("epc_in_scope",), ("section_text_not_empty",)}
    g = medallion.gold(spark, "run1")
    edges = spark.read.format("delta").load(medallion.TABLES["gold.kg_edges"]).collect()
    ext = [e for e in edges if e.rel == "MENTIONS_INTERACTION_WITH"]
    assert ext and all(json.loads(e.props)["extracted"] and json.loads(e.props)["method"] for e in ext)
    assert all(not json.loads(e.props)["extracted"] for e in edges if e.rel != "MENTIONS_INTERACTION_WITH")
    assert g["kg_snapshot_sha256"] == medallion.kg_snapshot_hash(spark)
    # second ingest: bronze is append-only, earlier versions stay readable (time travel)
    medallion.bronze(spark, "run2", raw, man)
    assert delta_version(spark, medallion.TABLES["bronze.labels"]) == 1
    v0 = spark.read.format("delta").option("versionAsOf", 0).load(medallion.TABLES["bronze.labels"])
    assert v0.count() == 4 and spark.read.format("delta").load(medallion.TABLES["bronze.labels"]).count() == 8
    # tampered raw file is refused before anything is written
    (raw / "b.json").write_bytes(b'{"results": []}')
    with pytest.raises(RuntimeError, match="sha256"):
        medallion.bronze(spark, "run3", raw, man)


def test_snapshot_hash_is_order_independent():
    from cgg.pipeline.medallion import snapshot_hash

    n = [("Label", "a"), ("Route", "ORAL")]
    e = [("Label", "a", "HAS_ROUTE", "Route", "ORAL")]
    assert snapshot_hash(n, e) == snapshot_hash(list(reversed(n)), e)
    assert snapshot_hash(n, e) != snapshot_hash(n, [])
