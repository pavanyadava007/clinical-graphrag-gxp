# Databricks notebook source
# MAGIC %md
# MAGIC # 01 Medallion pipeline (bronze -> silver -> gold)
# MAGIC Same code as `cgg ingest` locally. Provided for Databricks deployment; **not run on a Databricks
# MAGIC workspace** in this project (the measured run used local PySpark 3.5.3 + delta-spark 3.2.1).
# MAGIC On Databricks the raw openFDA files would land in a Unity Catalog volume and `config.LAKE`
# MAGIC would point at `/Volumes/<catalog>/cgg/lake` or be replaced with managed tables.

# COMMAND ----------

dbutils.widgets.text("catalog", "cgg_dev")  # noqa: F821
catalog = dbutils.widgets.get("catalog")  # noqa: F821

# COMMAND ----------

import os  # noqa: E402

os.environ["CGG_LAKE"] = f"/Volumes/{catalog}/cgg/lake"  # must be set before cgg is imported

from cgg.pipeline.medallion import export_serving, run  # noqa: E402

report = run()  # uses the active `spark` session provided by Databricks
export_serving(spark)  # noqa: F821
displayHTML(f"<pre>{report}</pre>")  # noqa: F821
