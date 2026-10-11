"""Embed gold.chunks with nomic-embed-text (Ollama) and serve a small in-process cosine index."""

from __future__ import annotations

import hashlib
import json
import time
from functools import lru_cache

import numpy as np
import pandas as pd

from cgg import config
from cgg.llm import embed

EMB = config.GOLD_DIR / "embeddings.npy"
META = config.GOLD_DIR / "chunks.parquet"
MANIFEST = config.GOLD_DIR / "embedding_manifest.json"


def build(batch: int = 64) -> dict:
    from cgg.pipeline.medallion import TABLES
    from cgg.pipeline.spark import delta_version, get_spark

    spark = get_spark()
    df = spark.read.format("delta").load(TABLES["gold.chunks"]).orderBy("chunk_id").toPandas()
    version = delta_version(spark, TABLES["gold.chunks"])
    t0 = time.time()
    vecs = []
    for i in range(0, len(df), batch):
        vecs.extend(embed(df["embed_text"].iloc[i:i + batch].tolist()))
    m = np.asarray(vecs, dtype=np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-12
    config.GOLD_DIR.mkdir(parents=True, exist_ok=True)
    np.save(EMB, m)
    df.drop(columns=["embed_text"]).to_parquet(META, index=False)
    from cgg.llm import Ollama

    man = {
        "model": config.EMBED_MODEL,
        "model_digest": Ollama(model=config.EMBED_MODEL).model_digest(),
        "n_chunks": int(m.shape[0]),
        "dims": int(m.shape[1]),
        "embeddings_sha256": hashlib.sha256(EMB.read_bytes()).hexdigest(),
        "gold_chunks_delta_version": version,
        "seconds": round(time.time() - t0, 1),
    }
    MANIFEST.write_text(json.dumps(man, indent=1))
    (config.RESULTS / "embedding_report.json").write_text(json.dumps(man, indent=1))
    return man


class VectorIndex:
    def __init__(self):
        self.m = np.load(EMB)
        self.meta = pd.read_parquet(META)
        self.by_set = self.meta.groupby("set_id").indices

    def search(self, query: str, k: int = config.TOP_K, set_ids: list[str] | None = None,
               sections: list[str] | None = None) -> list[dict]:
        q = np.asarray(embed([query], prefix="search_query: ")[0], dtype=np.float32)
        q /= np.linalg.norm(q) + 1e-12
        if set_ids:
            idx = np.concatenate([self.by_set[s] for s in set_ids if s in self.by_set]) if any(
                s in self.by_set for s in set_ids) else np.array([], dtype=int)
        else:
            idx = np.arange(len(self.meta))
        if sections and len(idx):
            idx = idx[self.meta["section"].values[idx].astype(str) != ""]
            keep = np.isin(self.meta["section"].values[idx], sections)
            if keep.any():
                idx = idx[keep]
        if not len(idx):
            return []
        scores = self.m[idx] @ q
        order = np.argsort(-scores)[:k]
        out = []
        for o in order:
            r = self.meta.iloc[int(idx[o])]
            out.append({"chunk_id": r.chunk_id, "set_id": r.set_id, "section": r.section, "text": r.text,
                        "brand_name": r.brand_name, "generic_name": r.generic_name,
                        "manufacturer": r.manufacturer, "score": float(scores[o])})
        return out


@lru_cache(maxsize=1)
def index() -> VectorIndex:
    return VectorIndex()


if __name__ == "__main__":
    print(json.dumps(build(), indent=1))
