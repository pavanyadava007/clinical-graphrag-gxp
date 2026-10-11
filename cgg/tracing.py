"""Tracing: every question becomes one Langfuse trace with spans (route, cypher, retrieve, generate, guard).

Backend selection: Langfuse (self-hosted v2) when LANGFUSE_HOST and keys are set and the server answers,
otherwise spans are only kept in memory and written to the per-question results (no silent claim of Langfuse).
"""

from __future__ import annotations

import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SpanRecord:
    name: str
    start: float
    end: float = 0.0
    input: Any = None
    output: Any = None
    metadata: dict = field(default_factory=dict)
    level: str = "DEFAULT"

    @property
    def ms(self) -> float:
        return round((self.end - self.start) * 1000, 1)


class Trace:
    def __init__(self, tracer: "Tracer", name: str, input: Any, metadata: dict, tags: list[str]):
        self.tracer = tracer
        self.id = uuid.uuid4().hex
        self.spans: list[SpanRecord] = []
        self._lf = None
        if tracer.langfuse is not None:
            self._lf = tracer.langfuse.trace(id=self.id, name=name, input=input, metadata=metadata, tags=tags)

    @contextmanager
    def span(self, name: str, input: Any = None, **metadata):
        rec = SpanRecord(name=name, start=time.time(), input=input, metadata=dict(metadata))
        lf_span = self._lf.span(name=name, input=input, metadata=metadata) if self._lf else None
        try:
            yield rec
        except Exception as e:  # recorded, then re-raised
            rec.level = "ERROR"
            rec.output = rec.output or {"error": str(e)}
            raise
        finally:
            rec.end = time.time()
            self.spans.append(rec)
            if lf_span is not None:
                lf_span.end(output=rec.output, level=rec.level, metadata=rec.metadata)

    def generation(self, name: str, model: str, system: str, user: str, output: str, usage: dict,
                   latency_s: float, params: dict, prompt_version: str | None = None):
        now = time.time()
        rec = SpanRecord(name=name, start=now - latency_s, end=now, input={"user": user[:4000]}, output=output,
                         metadata={"model": model, "usage": usage, "prompt_version": prompt_version})
        self.spans.append(rec)
        if self._lf:
            from datetime import datetime, timezone

            self._lf.generation(
                name=name, model=model, model_parameters=params,
                input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                output=output, usage={"input": usage.get("prompt_tokens", 0), "output": usage.get("completion_tokens", 0)},
                start_time=datetime.fromtimestamp(now - latency_s, tz=timezone.utc),
                end_time=datetime.fromtimestamp(now, tz=timezone.utc),
                metadata={"prompt_version": prompt_version})

    def end(self, output: Any, metadata: dict | None = None):
        if self._lf:
            self._lf.update(output=output, metadata=metadata or {})

    def score(self, name: str, value: float, comment: str | None = None):
        if self.tracer.langfuse is not None:
            self.tracer.langfuse.score(trace_id=self.id, name=name, value=value, comment=comment)

    def to_dict(self) -> list[dict]:
        return [{"name": s.name, "ms": s.ms, "level": s.level, "metadata": s.metadata} for s in self.spans]


class Tracer:
    def __init__(self, enabled: bool = True):
        self.langfuse = None
        self.backend = "none"
        if enabled and os.environ.get("LANGFUSE_HOST") and os.environ.get("LANGFUSE_PUBLIC_KEY"):
            try:
                from langfuse import Langfuse

                lf = Langfuse(host=os.environ["LANGFUSE_HOST"], public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
                              secret_key=os.environ["LANGFUSE_SECRET_KEY"], release=os.environ.get("CGG_RELEASE"))
                if lf.auth_check():
                    self.langfuse, self.backend = lf, "langfuse"
            except Exception as e:  # pragma: no cover - depends on a running server
                print(f"[tracing] Langfuse unavailable ({e}); traces kept in results only")

    def trace(self, name: str, input: Any, metadata: dict | None = None, tags: list[str] | None = None) -> Trace:
        return Trace(self, name, input, metadata or {}, tags or [])

    def score(self, trace_id: str, name: str, value: float, comment: str | None = None):
        if self.langfuse is not None:
            self.langfuse.score(trace_id=trace_id, name=name, value=value, comment=comment)

    def flush(self):
        if self.langfuse is not None:
            self.langfuse.flush()
