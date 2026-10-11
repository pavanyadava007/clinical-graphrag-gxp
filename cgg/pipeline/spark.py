"""Local Spark session with Delta Lake (delta-spark). The same code runs on Databricks, where
`spark` already exists and the Delta jars are provided by the runtime."""

from __future__ import annotations

import os

from cgg import config


def get_spark(app: str = "cgg-pipeline"):
    from pyspark.sql import SparkSession

    active = SparkSession.getActiveSession()
    if active is not None:
        return active
    from delta import configure_spark_with_delta_pip

    os.environ.setdefault("PYSPARK_PYTHON", os.sys.executable)
    builder = (
        SparkSession.builder.appName(app)
        .master(os.environ.get("CGG_SPARK_MASTER", "local[8]"))
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .config("spark.driver.memory", os.environ.get("CGG_SPARK_DRIVER_MEM", "6g"))
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.warehouse.dir", str(config.DATA / "spark-warehouse"))
        .config("spark.databricks.delta.schema.autoMerge.enabled", "false")
    )
    spark = configure_spark_with_delta_pip(builder).getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    return spark


def table_path(layer: str, name: str) -> str:
    return str(config.LAKE / layer / name)


def delta_version(spark, path: str) -> int:
    from delta.tables import DeltaTable

    return int(DeltaTable.forPath(spark, path).history(1).collect()[0]["version"])
