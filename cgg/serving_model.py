"""MLflow 'models from code' definition of the guarded GraphRAG system (system C).

The model is code plus configuration (LLM, prompt versions, top-k); data dependencies (Neo4j graph,
embeddings, serving snapshot) are referenced by the lineage tags on the registered model version.
"""

from __future__ import annotations

import mlflow
import pandas as pd
from mlflow.pyfunc import PythonModel


class GuardedGraphRAGModel(PythonModel):
    def load_context(self, context):
        from cgg.systems.base import SystemConfig
        from cgg.systems.qa import SYSTEMS

        c = context.model_config or {}
        cfg = SystemConfig(model=c.get("model", "llama3.1:8b"), temperature=float(c.get("temperature", 0.0)),
                           seed=int(c.get("seed", 7)), top_k=int(c.get("top_k", 6)),
                           prompts=c.get("prompts") or {"router": 1, "text2cypher": 1, "answer": 1, "safety": 1})
        self.system = SYSTEMS[c.get("system", "C")](cfg)

    def predict(self, context, model_input: pd.DataFrame, params=None) -> list[dict]:
        out = []
        for q in model_input["question"].tolist():
            a = self.system.ask(q).to_dict()
            out.append({k: a[k] for k in ("status", "answer", "citations", "route", "cypher", "reason", "trace_id")})
        return out


mlflow.models.set_model(GuardedGraphRAGModel())
