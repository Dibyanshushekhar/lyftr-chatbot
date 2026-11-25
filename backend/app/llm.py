"""LiteLLM gateway: key pool with automatic failover + built-in response cache."""
import logging
import math
from dataclasses import dataclass

import litellm

logger = logging.getLogger("llm")
litellm.suppress_debug_info = True

SIMULATABLE = {"429", "500", "502", "503"}


class AllProvidersUnavailable(Exception):
    pass


class SimulatedProviderError(Exception):
    def __init__(self, status: int):
        super().__init__(f"simulated provider status {status}")
        self.status_code = status


@dataclass
class LLMResult:
    reply: str
    cache_hit: bool
    model: str
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int


def parse_simulation(header: str | None) -> dict[str, int]:
    """'key_1=429,key_2=500' / '*=429' -> {'key_1': 429, ...}. Invalid pairs are ignored."""
    out: dict[str, int] = {}
    for part in (header or "").split(","):
        name, sep, status = part.strip().partition("=")
        if sep and name.strip() and status.strip() in SIMULATABLE:
            out[name.strip()] = int(status.strip())
    return out


class LLMGateway:
    def __init__(self, keys: list[str], model: str, cache_type: str, cache_dir: str,
                 timeout: float, max_tokens: int):
        self.keys = keys
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.cache_enabled = self._setup_cache(cache_type, cache_dir)

    @staticmethod
    def _setup_cache(cache_type: str, cache_dir: str) -> bool:
        try:
            if cache_type == "disk":
                litellm.cache = litellm.Cache(type="disk", disk_cache_dir=cache_dir)
            else:
                litellm.cache = litellm.Cache(type="local")
            return True
        except Exception as exc:  # e.g. diskcache missing / dir not writable -> fall back to memory
            logger.warning("disk cache unavailable (%s); using in-memory cache", type(exc).__name__)
            litellm.cache = litellm.Cache(type="local")
            return True

    def complete(self, messages: list[dict], simulate: dict[str, int] | None = None) -> LLMResult:
        simulate = simulate or {}
        failures = 0
        for index, api_key in enumerate(self.keys, start=1):
            key_id = f"key_{index}"
            forced = simulate.get(key_id, simulate.get("*"))
            try:
                if forced:
                    raise SimulatedProviderError(forced)
                kwargs = dict(
                    model=self.model, messages=messages, api_key=api_key,
                    caching=True, num_retries=0, timeout=self.timeout, max_tokens=self.max_tokens,
                )
                if simulate:  # failover demos must hit the provider, never the cache
                    kwargs["cache"] = {"no-cache": True}
                resp = litellm.completion(**kwargs)
                text = (resp.choices[0].message.content or "").strip()
                if not text:
                    raise ValueError("empty completion")
            except Exception as exc:  # 429 / quota / 5xx / auth / timeout -> next key
                failures += 1
                logger.warning("%s failed: %s (status=%s)", key_id, type(exc).__name__,
                               getattr(exc, "status_code", "n/a"))
                continue
            hidden = getattr(resp, "_hidden_params", None) or {}
            hit = bool(hidden.get("cache_hit"))
            return LLMResult(
                reply=text, cache_hit=hit, model=self.model,
                input_tokens=int(resp.usage.prompt_tokens or 0),
                output_tokens=int(resp.usage.completion_tokens or 0),
                key_id=None if hit else key_id,
                fallback_attempts=0 if hit else failures,
            )
        raise AllProvidersUnavailable()


def ms_since(start: float, now: float) -> int:
    return max(1, math.ceil((now - start) * 1000))
