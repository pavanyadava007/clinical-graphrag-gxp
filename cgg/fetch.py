"""Download the openFDA drug label snapshot used by the project.

For every pharmacologic class in config.SCOPE_EPC the generic names are listed with the openFDA
count endpoint, then the most recent MAX_LABELS_PER_GENERIC prescription labels per generic name are
downloaded. Each raw API response is stored unchanged with its sha256 in data/manifest/fetch_manifest.json,
which is committed (the raw JSON itself is not, it is about 100 MB).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from cgg import config

MANIFEST = config.DATA / "manifest" / "fetch_manifest.json"


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:80]


def _get(client: httpx.Client, params: dict) -> dict:
    for attempt in range(5):
        r = client.get(config.OPENFDA_URL, params=params)
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 404:
            return {"results": []}
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"openFDA kept returning 429 for {params}")


def class_query(epc: str) -> str:
    return f'openfda.pharm_class_epc:"{epc} [EPC]" AND openfda.product_type:"HUMAN PRESCRIPTION DRUG"'


def fetch(out_dir: Path = config.RAW_DIR, pause_s: float = 0.35) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with httpx.Client(timeout=60) as client:
        for epc in config.SCOPE_EPC:
            q = class_query(epc)
            counts = _get(client, {"search": q, "count": "openfda.generic_name.exact", "limit": 1000})
            generics = sorted(r["term"] for r in counts.get("results", []))
            time.sleep(pause_s)
            for g in generics:
                gq = f'{q} AND openfda.generic_name.exact:"{g}"'
                params = {"search": gq, "sort": "effective_time:desc", "limit": config.MAX_LABELS_PER_GENERIC}
                body = _get(client, params)
                time.sleep(pause_s)
                raw = json.dumps(body, sort_keys=True).encode()
                name = f"{slug(epc)}__{slug(g)[:60]}__{hashlib.sha256(g.encode()).hexdigest()[:8]}.json"
                (out_dir / name).write_bytes(raw)
                entries.append({
                    "file": name,
                    "epc": epc,
                    "generic_name": g,
                    "request": {"url": config.OPENFDA_URL, **params},
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                    "n_labels": len(body.get("results", [])),
                    "set_ids": [r.get("set_id") for r in body.get("results", [])],
                    "openfda_last_updated": body.get("meta", {}).get("last_updated"),
                })
                print(f"{epc:45s} {g[:50]:50s} {len(body.get('results', []))}")
    manifest = {
        "source": "openFDA drug/label API (public domain, https://open.fda.gov/apis/drug/label/)",
        "fetched_at_utc": started,
        "scope_epc": config.SCOPE_EPC,
        "max_labels_per_generic": config.MAX_LABELS_PER_GENERIC,
        "n_files": len(entries),
        "n_label_records": sum(e["n_labels"] for e in entries),
        "files": entries,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=1))
    return manifest


def verify(raw_dir: Path = config.RAW_DIR) -> list[str]:
    """Return the files whose sha256 differs from the manifest (empty list = intact)."""
    manifest = json.loads(MANIFEST.read_text())
    bad = []
    for e in manifest["files"]:
        p = raw_dir / e["file"]
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != e["sha256"]:
            bad.append(e["file"])
    return bad


if __name__ == "__main__":
    m = fetch()
    print(m["n_files"], "files", m["n_label_records"], "label records")
