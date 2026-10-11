# Databricks notebook source
# MAGIC %md
# MAGIC # 03 Evaluate, log to MLflow and register a candidate
# MAGIC On Databricks, MLflow tracking and the Unity Catalog model registry are built in, so
# MAGIC `MLFLOW_TRACKING_URI=databricks` and the registered model name becomes `<catalog>.cgg.clinical_graphrag_qa`.
# MAGIC The LLM would be a Model Serving endpoint instead of Ollama (adapter not implemented).
# MAGIC **Not run on a Databricks workspace.**

# COMMAND ----------

import os  # noqa: E402

os.environ["MLFLOW_TRACKING_URI"] = "databricks"
scope = dbutils.widgets.get("secret_scope")  # noqa: F821
os.environ["CGG_NEO4J_PASSWORD"] = dbutils.secrets.get(scope, "neo4j-password")  # noqa: F821

# COMMAND ----------

from cgg.evaluate import run_eval  # noqa: E402
from cgg.tracking import log_eval_run, register_model  # noqa: E402

metrics = run_eval("C", "pq-C-databricks")
run_id = log_eval_run("pq-C-databricks")
register_model("pq-C-databricks")
