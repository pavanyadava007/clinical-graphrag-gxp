"""Installation Qualification: record the installed environment and check it against the expected one.

Writes results/iq_report.json. Checks are factual (versions, image digests, model digests, service health);
a failed check sets ok=false.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EXPECTED_PACKAGES = {"pyspark": "3.5.3", "delta-spark": "3.2.1"}
MIN_PACKAGES = {"mlflow": "3.1", "neo4j": "5.20", "langfuse": "2.50"}
IMAGES = ["neo4j:5-community", "postgres:16-alpine", "langfuse/langfuse:2", "ollama/ollama:latest"]
MODELS = ["llama3.1:8b", "nomic-embed-text:latest"]


def _sh(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT).strip()
    except Exception as e:  # noqa: BLE001
        return f"ERROR {e}"


def main() -> int:
    import httpx

    from cgg import config

    checks: dict[str, str] = {}
    ok = True
    checks["python"] = platform.python_version()
    ok &= sys.version_info >= (3, 10)
    for p, v in EXPECTED_PACKAGES.items():
        got = version(p)
        checks[f"package {p}"] = f"{got} (expected {v})"
        ok &= got == v
    for p, v in MIN_PACKAGES.items():
        got = version(p)
        checks[f"package {p}"] = f"{got} (min {v})"
        ok &= tuple(int(x) for x in got.split(".")[:2]) >= tuple(int(x) for x in v.split("."))
    java = _sh(["java", "-version"]).splitlines()[0]
    checks["java"] = java
    ok &= '"17' in java or '"21' in java
    for img in IMAGES:
        d = _sh(["docker", "image", "inspect", "--format", "{{.Id}}", img])
        checks[f"image {img}"] = d[:19]
        ok &= d.startswith("sha256:")
    try:
        tags = httpx.get(f"{config.OLLAMA_HOST}/api/tags", timeout=5).json()["models"]
        have = {m["name"]: m["digest"][:12] for m in tags}
        for m in MODELS:
            checks[f"ollama model {m}"] = have.get(m, "MISSING")
            ok &= m in have
    except Exception as e:  # noqa: BLE001
        checks["ollama"] = f"unreachable: {e}"
        ok = False
    try:
        from cgg.graph.store import run_trusted

        v = run_trusted("CALL dbms.components() YIELD name, versions, edition RETURN versions[0] AS v, edition AS e")[0]
        checks["neo4j"] = f"{v['v']} {v['e']}"
    except Exception as e:  # noqa: BLE001
        checks["neo4j"] = f"unreachable: {e}"
        ok = False
    try:
        r = httpx.get("http://127.0.0.1:3100/api/public/health", timeout=5)
        checks["langfuse"] = f"HTTP {r.status_code} {r.json().get('version', '')}"
        ok &= r.status_code == 200
    except Exception as e:  # noqa: BLE001
        checks["langfuse"] = f"unreachable: {e}"
        ok = False
    try:
        gpu = _sh(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"])
        checks["gpu"] = gpu
    except Exception:  # noqa: BLE001
        checks["gpu"] = "none"
    out = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ok": bool(ok),
           "checks": checks}
    (ROOT / "results" / "iq_report.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
