"""Append-only, hash-chained audit trail (JSONL) and role-based access control.

Each event stores the sha256 of the previous event, so any edit, deletion or reordering breaks the chain
and `cgg audit verify` reports the first broken sequence number. This is a Part 11-style audit trail for a
demo: identities come from config/roles.yaml and are not authenticated (no SSO, no e-signature PIN).
"""

from __future__ import annotations

import fcntl
import getpass
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

from cgg import config

ROLES_FILE = config.ROOT / "config" / "roles.yaml"
GENESIS = "0" * 64

PERMISSIONS = {
    "register_model": {"developer"},
    "approve_release": {"qa_approver"},
    "promote": {"release_manager"},
    "review_answer": {"medical_reviewer"},
    "run_eval": {"developer", "qa_approver"},
    "ingest": {"developer"},
}


class AccessDenied(PermissionError):
    pass


def current_user() -> str:
    return os.environ.get("CGG_USER") or getpass.getuser()


def roles_of(user: str) -> set[str]:
    data = yaml.safe_load(ROLES_FILE.read_text()) if ROLES_FILE.exists() else {}
    return set((data.get("users") or {}).get(user, {}).get("roles", []))


def require(action: str, user: str | None = None) -> str:
    user = user or current_user()
    allowed = PERMISSIONS[action]
    if not roles_of(user) & allowed:
        raise AccessDenied(f"user '{user}' lacks a role for '{action}' (needs one of {sorted(allowed)})")
    return user


def _hash(rec: dict) -> str:
    body = {k: v for k, v in rec.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def append(action: str, obj: str, details: dict | None = None, actor: str | None = None,
           path: Path = config.AUDIT_LOG) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
        prev = json.loads(lines[-1]) if lines else None
        actor = actor or current_user()
        rec = {
            "seq": (prev["seq"] + 1) if prev else 1,
            "ts_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "actor": actor,
            "roles": sorted(roles_of(actor)),
            "action": action,
            "object": obj,
            "details": details or {},
            "prev_hash": prev["hash"] if prev else GENESIS,
        }
        rec["hash"] = _hash(rec)
        f.seek(0, os.SEEK_END)
        f.write(json.dumps(rec, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
        fcntl.flock(f, fcntl.LOCK_UN)
    return rec


def read(path: Path = config.AUDIT_LOG) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def verify(path: Path = config.AUDIT_LOG) -> dict:
    events = read(path)
    prev = GENESIS
    for i, e in enumerate(events, 1):
        if e.get("seq") != i:
            return {"ok": False, "n_events": len(events), "first_bad_seq": i, "reason": "sequence gap or reorder"}
        if e.get("prev_hash") != prev:
            return {"ok": False, "n_events": len(events), "first_bad_seq": i, "reason": "prev_hash mismatch"}
        if _hash(e) != e.get("hash"):
            return {"ok": False, "n_events": len(events), "first_bad_seq": i, "reason": "content hash mismatch"}
        prev = e["hash"]
    return {"ok": True, "n_events": len(events), "head_hash": prev}
