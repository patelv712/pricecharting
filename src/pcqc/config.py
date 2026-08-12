"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    pricecharting_api_token: str | None
    llm_api_key: str | None
    llm_base_url: str
    llm_model: str | None
    finish_llm_model: str | None
    cache_dir: Path
    random_seed: str

    @classmethod
    def from_env(cls, *, load_file: bool = True) -> "Settings":
        if load_file:
            load_dotenv()
        return cls(
            pricecharting_api_token=os.getenv("PRICECHARTING_API_TOKEN") or None,
            llm_api_key=os.getenv("LLM_API_KEY") or None,
            llm_base_url=os.getenv(
                "LLM_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta/openai",
            ).rstrip("/"),
            llm_model=os.getenv("LLM_MODEL") or None,
            finish_llm_model=(
                os.getenv("FINISH_LLM_MODEL")
                or os.getenv("LLM_MODEL")
                or None
            ),
            cache_dir=Path(os.getenv("PCQC_CACHE_DIR", "cache")),
            random_seed=os.getenv("PCQC_RANDOM_SEED", "pricecharting-poc-v1"),
        )
