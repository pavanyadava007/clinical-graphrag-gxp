"""Central configuration: paths, service endpoints and frozen run parameters.

Secrets (Neo4j password, Langfuse keys) are read from the environment only.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_local_env(path: Path = ROOT / "infra" / ".env") -> None:
    """Load infra/.env (gitignored, local secrets) without overriding variables already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    os.environ.setdefault("LANGFUSE_HOST", "http://127.0.0.1:3100")


if os.environ.get("CGG_NO_LOCAL_ENV") != "1":
    _load_local_env()
DATA = ROOT / "data"
RAW_DIR = DATA / "raw" / "openfda"
LAKE = Path(os.environ.get("CGG_LAKE", DATA / "lake"))  # Delta Lake tables (bronze / silver / gold)
GOLD_DIR = DATA / "gold"  # embeddings and other non-Delta gold artifacts
HITL_DIR = DATA / "hitl"
RESULTS = ROOT / "results"
EVAL_DIR = ROOT / "eval"
DOCS = ROOT / "docs"
AUDIT_LOG = ROOT / "audit" / "audit_trail.jsonl"

# openFDA scope: cardiometabolic prescription labels. Max labels kept per generic name (most recent first).
OPENFDA_URL = "https://api.fda.gov/drug/label.json"
SCOPE_EPC = [
    "Factor Xa Inhibitor",
    "Direct Thrombin Inhibitor",
    "P2Y12 Platelet Inhibitor",
    "HMG-CoA Reductase Inhibitor",
    "Angiotensin Converting Enzyme Inhibitor",
    "Angiotensin 2 Receptor Blocker",
    "beta-Adrenergic Blocker",
    "Calcium Channel Blocker",
    "Sodium-Glucose Cotransporter 2 Inhibitor",
    "Dipeptidyl Peptidase 4 Inhibitor",
    "GLP-1 Receptor Agonist",
    "Sulfonylurea",
    "Thiazide Diuretic",
    "Aldosterone Antagonist",
    "Loop Diuretic",
]
MAX_LABELS_PER_GENERIC = 4

# Label sections kept in silver (text sections used for retrieval and citations).
SECTIONS = [
    "boxed_warning",
    "indications_and_usage",
    "dosage_and_administration",
    "dosage_forms_and_strengths",
    "contraindications",
    "warnings_and_cautions",
    "warnings",
    "adverse_reactions",
    "drug_interactions",
    "use_in_specific_populations",
    "pregnancy",
    "overdosage",
    "description",
    "mechanism_of_action",
    "how_supplied",
]
CHUNK_CHARS = 1200
CHUNK_OVERLAP = 200

# Services (all bound to 127.0.0.1)
OLLAMA_HOST = os.environ.get("CGG_OLLAMA_HOST", "http://127.0.0.1:11501")
LLM_MODEL = os.environ.get("CGG_LLM_MODEL", "llama3.1:8b")
EMBED_MODEL = os.environ.get("CGG_EMBED_MODEL", "nomic-embed-text")
EMBED_HOST = os.environ.get("CGG_EMBED_HOST", OLLAMA_HOST)
NEO4J_URI = os.environ.get("CGG_NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = os.environ.get("CGG_NEO4J_USER", "neo4j")
MLFLOW_URI = os.environ.get("MLFLOW_TRACKING_URI", f"sqlite:///{ROOT / 'mlflow.db'}")
MLFLOW_ARTIFACTS = ROOT / "mlartifacts"
REGISTERED_MODEL = "clinical-graphrag-qa"

# Generation parameters frozen for the PQ run
TEMPERATURE = 0.0
SEED = 7
TOP_K = 6
REQUEST_TIMEOUT_S = 120.0


def neo4j_password() -> str:
    pw = os.environ.get("CGG_NEO4J_PASSWORD")
    if not pw:
        raise RuntimeError("set CGG_NEO4J_PASSWORD (local only, never committed)")
    return pw
