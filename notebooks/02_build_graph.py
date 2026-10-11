# Databricks notebook source
# MAGIC %md
# MAGIC # 02 Load the knowledge graph into Neo4j
# MAGIC Reads gold.kg_nodes / gold.kg_edges and loads them idempotently; compares snapshot hashes.
# MAGIC Credentials come from a Databricks secret scope. **Not run on a Databricks workspace.**

# COMMAND ----------

import os  # noqa: E402

scope = dbutils.widgets.get("secret_scope")  # noqa: F821
os.environ["CGG_NEO4J_URI"] = dbutils.secrets.get(scope, "neo4j-uri")  # noqa: F821
os.environ["CGG_NEO4J_PASSWORD"] = dbutils.secrets.get(scope, "neo4j-password")  # noqa: F821

# COMMAND ----------

from cgg.graph.store import load_from_gold  # noqa: E402

r = load_from_gold(spark)  # noqa: F821
assert r["match"], "Neo4j snapshot hash differs from the gold tables"
r
