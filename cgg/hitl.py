"""Human-in-the-loop review queue (SQLite). Escalated answers wait here for a medical reviewer who
approves, rejects or edits them; every decision is recorded with reviewer, role, reason and time and is
also written to the hash-chained audit trail."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from cgg import audit, config

SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_utc TEXT NOT NULL,
  run_id TEXT,
  qid TEXT,
  system TEXT NOT NULL,
  question TEXT NOT NULL,
  proposed_answer TEXT,
  citations TEXT,
  escalation_reason TEXT,
  trace_id TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  reviewer TEXT,
  reviewer_roles TEXT,
  decision_reason TEXT,
  final_answer TEXT,
  decided_utc TEXT
);
"""

DECISIONS = {"approve": "approved", "reject": "rejected", "edit": "edited"}


class ReviewQueue:
    def __init__(self, path: Path = config.HITL_DIR / "queue.db", run_id: str | None = None):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self.run_id = path, run_id
        with self._db() as db:
            db.executescript(SCHEMA)

    def _db(self):
        return sqlite3.connect(self.path)

    def submit(self, ans, meta: dict) -> int:
        with self._db() as db:
            cur = db.execute(
                "INSERT INTO reviews (created_utc, run_id, qid, system, question, proposed_answer, citations, "
                "escalation_reason, trace_id) VALUES (?,?,?,?,?,?,?,?,?)",
                (_now(), self.run_id, meta.get("qid"), ans.system, ans.question, json.dumps(ans.answer),
                 json.dumps(ans.citations), ans.reason, ans.trace_id))
            rid = int(cur.lastrowid)
        audit.append("hitl.submit", f"review/{rid}", {"qid": meta.get("qid"), "reason": ans.reason,
                                                       "run_id": self.run_id}, actor="system:guarded-graphrag")
        return rid

    def pending(self) -> list[dict]:
        return self._rows("SELECT * FROM reviews WHERE status='pending' ORDER BY id")

    def get(self, rid: int) -> dict:
        rows = self._rows("SELECT * FROM reviews WHERE id=?", (rid,))
        if not rows:
            raise KeyError(rid)
        return rows[0]

    def decide(self, rid: int, decision: str, reason: str, reviewer: str | None = None,
               final_answer=None) -> dict:
        if decision not in DECISIONS:
            raise ValueError(f"decision must be one of {sorted(DECISIONS)}")
        if not reason or not reason.strip():
            raise ValueError("a reason is required for every review decision")
        reviewer = audit.require("review_answer", reviewer)
        item = self.get(rid)
        if item["status"] != "pending":
            raise ValueError(f"review {rid} is already {item['status']}")
        if decision == "approve":
            final = json.loads(item["proposed_answer"]) if item["proposed_answer"] else None
        elif decision == "edit":
            if final_answer is None:
                raise ValueError("edit needs a final answer")
            final = final_answer
        else:
            final = None
        with self._db() as db:
            db.execute("UPDATE reviews SET status=?, reviewer=?, reviewer_roles=?, decision_reason=?, "
                       "final_answer=?, decided_utc=? WHERE id=?",
                       (DECISIONS[decision], reviewer, ",".join(sorted(audit.roles_of(reviewer))), reason,
                        json.dumps(final), _now(), rid))
        audit.append(f"hitl.{decision}", f"review/{rid}",
                     {"qid": item["qid"], "reason": reason, "run_id": item["run_id"]}, actor=reviewer)
        return self.get(rid)

    def stats(self, run_id: str | None = None) -> dict:
        q = "SELECT status, count(*) AS n FROM reviews" + (" WHERE run_id=?" if run_id else "") + " GROUP BY status"
        return {r["status"]: r["n"] for r in self._rows(q, (run_id,) if run_id else ())}

    def _rows(self, q: str, args: tuple = ()) -> list[dict]:
        with self._db() as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute(q, args).fetchall()]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
