"""All configuration comes from environment variables."""
import os
from dataclasses import dataclass, field


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass
class Settings:
    llm_api_keys: list[str] = field(default_factory=list)
    llm_model: str = "gemini/gemini-2.0-flash"
    database_url: str = "sqlite:////data/app.db"
    allowed_origins: list[str] = field(default_factory=list)
    enable_failure_simulation: bool = False
    cache_type: str = "local"  # "local" (in-memory); "disk" only if the installed LiteLLM supports it
    cache_dir: str = "/data/llm_cache"
    llm_timeout: float = 30.0
    max_output_tokens: int = 1024
    default_system_prompt: str = "You are a helpful, concise assistant."

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ.get
        return cls(
            llm_api_keys=_csv(e("LLM_API_KEYS", "")),
            llm_model=e("LLM_MODEL", cls.llm_model),
            database_url=e("DATABASE_URL", cls.database_url),
            allowed_origins=_csv(e("ALLOWED_ORIGINS", "http://localhost:3000")),
            enable_failure_simulation=e("ENABLE_FAILURE_SIMULATION", "false").lower() == "true",
            cache_type=e("CACHE_TYPE", cls.cache_type),
            cache_dir=e("CACHE_DIR", cls.cache_dir),
            llm_timeout=float(e("LLM_TIMEOUT", "30")),
            max_output_tokens=int(e("MAX_OUTPUT_TOKENS", "1024")),
            default_system_prompt=e("DEFAULT_SYSTEM_PROMPT", cls.default_system_prompt),
        )
