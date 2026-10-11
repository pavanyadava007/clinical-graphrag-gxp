"""Versioned prompt templates (cgg/prompts/<name>.v<N>.yaml). Templates use {{var}} placeholders,
the same syntax as the MLflow prompt registry, so they can be registered unchanged."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    description: str
    system: str
    user: str

    @property
    def ref(self) -> str:
        return f"{self.name}@v{self.version}"

    @property
    def sha256(self) -> str:
        return hashlib.sha256((self.system + "\n---\n" + self.user).encode()).hexdigest()

    def render(self, **vars) -> tuple[str, str]:
        return render(self.system, **vars), render(self.user, **vars)


def render(template: str, **vars) -> str:
    out = template
    for k, v in vars.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out


@cache
def load(name: str, version: int) -> Prompt:
    d = yaml.safe_load((PROMPT_DIR / f"{name}.v{version}.yaml").read_text())
    return Prompt(d["name"], int(d["version"]), d.get("description", ""), d["system"], d["user"])


def all_prompts() -> list[Prompt]:
    out = []
    for p in sorted(PROMPT_DIR.glob("*.v*.yaml")):
        name, v = p.stem.rsplit(".v", 1)
        out.append(load(name, int(v)))
    return out
