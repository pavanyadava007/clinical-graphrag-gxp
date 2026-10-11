"""Shared types and helpers for the three QA systems."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from cgg import config
from cgg.llm import LLMResult, Ollama, parse_json
from cgg.promptlib import Prompt
from cgg.tracing import Trace


@dataclass
class Answer:
    system: str
    question: str
    status: str = "answered"  # answered | refused | escalated | error
    answer: Any = None
    citations: list = field(default_factory=list)
    route: str | None = None
    cypher: str | None = None
    rows: list | None = None
    resolved_set_ids: list | None = None
    reason: str | None = None
    checks: dict = field(default_factory=dict)
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    trace_id: str | None = None
    spans: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["rows"] is not None:
            d["rows"] = d["rows"][:50]
        return d


@dataclass
class SystemConfig:
    model: str = config.LLM_MODEL
    temperature: float = config.TEMPERATURE
    seed: int = config.SEED
    top_k: int = config.TOP_K
    prompts: dict = field(default_factory=lambda: {"router": 1, "text2cypher": 1, "answer": 1, "safety": 1})

    def as_params(self) -> dict:
        p = {"model": self.model, "temperature": self.temperature, "seed": self.seed, "top_k": self.top_k}
        p.update({f"prompt.{k}": f"{k}@v{v}" for k, v in self.prompts.items()})
        return p


class LLMCaller:
    """Wraps Ollama calls so each one is counted on the Answer and logged as a Langfuse generation."""

    def __init__(self, cfg: SystemConfig):
        self.cfg = cfg
        self.llm = Ollama(model=cfg.model, temperature=cfg.temperature, seed=cfg.seed)

    def call(self, ans: Answer, trace: Trace, prompt: Prompt, name: str, json_mode: bool, max_tokens: int = 600,
             extra_user: str = "", **vars) -> LLMResult:
        system, user = prompt.render(**vars)
        if extra_user:
            user = user + "\n\n" + extra_user
        res = self.llm.chat(system, user, json_mode=json_mode, max_tokens=max_tokens)
        ans.llm_calls += 1
        ans.prompt_tokens += res.prompt_tokens
        ans.completion_tokens += res.completion_tokens
        trace.generation(name, res.model, system, user, res.text,
                         {"prompt_tokens": res.prompt_tokens, "completion_tokens": res.completion_tokens},
                         res.latency_s, {"temperature": self.cfg.temperature, "seed": self.cfg.seed},
                         prompt_version=prompt.ref)
        return res


def format_context(chunks: list[dict]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(f"[{i}] set_id={c['set_id']} | brand={c['brand_name']} | manufacturer={c['manufacturer']} "
                     f"| section={c['section']}\n{c['text']}")
    return "\n\n".join(parts)


def parse_answer_json(text: str) -> tuple[Any, list]:
    d = parse_json(text)
    cits = d.get("citations") or []
    if isinstance(cits, dict):
        cits = [cits]
    return d.get("answer"), [c for c in cits if isinstance(c, dict)]


def rows_to_answer(rows: list[dict]) -> Any:
    vals = []
    for r in rows:
        v = r.get("answer", next(iter(r.values()), None)) if r else None
        if isinstance(v, list):
            vals.extend(v)
        else:
            vals.append(v)
    vals = [v for v in vals if v is not None]
    if len(vals) == 1 and isinstance(vals[0], (bool, int, float)):
        return vals[0]
    return vals


class Timer:
    def __enter__(self):
        self.t0 = time.time()
        return self

    def __exit__(self, *a):
        self.s = time.time() - self.t0
