"""Create infra/.env with random local secrets (never committed). Existing file is kept."""

from __future__ import annotations

import secrets
from pathlib import Path

ENV = Path(__file__).resolve().parent.parent / "infra" / ".env"


def main() -> None:
    if ENV.exists():
        print(f"{ENV} exists, leaving it unchanged")
        return
    vals = {
        "CGG_NEO4J_PASSWORD": secrets.token_urlsafe(18),
        "LANGFUSE_DB_PASSWORD": secrets.token_urlsafe(18),
        "LANGFUSE_NEXTAUTH_SECRET": secrets.token_urlsafe(32),
        "LANGFUSE_SALT": secrets.token_urlsafe(32),
        "LANGFUSE_PUBLIC_KEY": "pk-lf-" + secrets.token_hex(12),
        "LANGFUSE_SECRET_KEY": "sk-lf-" + secrets.token_hex(16),
        "LANGFUSE_ADMIN_PASSWORD": secrets.token_urlsafe(14),
        "OLLAMA_VOLUME": "cgg_ollama",
    }
    ENV.write_text("".join(f"{k}={v}\n" for k, v in vals.items()))
    ENV.chmod(0o600)
    print(f"wrote {ENV}")


if __name__ == "__main__":
    main()
