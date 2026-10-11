"""Minimal Ollama client (chat + embeddings) with fixed temperature and seed."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

import httpx

from cgg import config


@dataclass
class LLMResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float


class LLMError(RuntimeError):
    pass


class Ollama:
    def __init__(self, model: str = config.LLM_MODEL, host: str = config.OLLAMA_HOST,
                 temperature: float = config.TEMPERATURE, seed: int = config.SEED,
                 timeout_s: float = config.REQUEST_TIMEOUT_S, num_ctx: int = 8192):
        self.model, self.host = model, host.rstrip("/")
        self.temperature, self.seed, self.num_ctx = temperature, seed, num_ctx
        self.client = httpx.Client(timeout=timeout_s)

    def chat(self, system: str, user: str, json_mode: bool = False, max_tokens: int = 512) -> LLMResult:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "options": {"temperature": self.temperature, "seed": self.seed, "num_ctx": self.num_ctx,
                        "num_predict": max_tokens},
        }
        if json_mode:
            body["format"] = "json"
        t0 = time.time()
        try:
            r = self.client.post(f"{self.host}/api/chat", json=body)
            r.raise_for_status()
        except httpx.TimeoutException as e:
            raise LLMError(f"timeout: {e}") from e
        except httpx.HTTPError as e:
            raise LLMError(str(e)) from e
        d = r.json()
        return LLMResult(d["message"]["content"], self.model, d.get("prompt_eval_count", 0),
                         d.get("eval_count", 0), time.time() - t0)

    def model_digest(self) -> str:
        r = self.client.post(f"{self.host}/api/show", json={"model": self.model})
        r.raise_for_status()
        d = r.json()
        return d.get("digest") or d.get("details", {}).get("digest") or _digest_from_tags(self)


def _digest_from_tags(o: Ollama) -> str:
    r = o.client.get(f"{o.host}/api/tags")
    for m in r.json().get("models", []):
        if m["name"] == o.model or m["name"] == f"{o.model}:latest":
            return m["digest"]
    return "unknown"


def embed(texts: list[str], model: str = config.EMBED_MODEL, host: str = config.OLLAMA_HOST,
          prefix: str = "search_document: ") -> list[list[float]]:
    """nomic-embed-text expects task prefixes: search_document for chunks, search_query for questions."""
    with httpx.Client(timeout=300) as c:
        r = c.post(f"{host.rstrip('/')}/api/embed", json={"model": model, "input": [prefix + t for t in texts]})
        r.raise_for_status()
        return r.json()["embeddings"]


def parse_json(text: str) -> dict:
    """Parse a JSON object from a model reply; tolerate code fences and leading prose."""
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, flags=re.S)
    if m:
        t = m.group(1)
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else {"answer": v}
    except json.JSONDecodeError:
        a, b = t.find("{"), t.rfind("}")
        if a >= 0 and b > a:
            try:
                return json.loads(t[a:b + 1])
            except json.JSONDecodeError:
                pass
    raise ValueError("reply is not valid JSON")
