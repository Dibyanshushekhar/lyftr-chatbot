import json
import types

import pytest
from fastapi.testclient import TestClient

from app import llm
from app.config import Settings
from app.main import create_app


class FakeLiteLLM:
    """Stands in for litellm.completion; emulates its cache + provider failures."""

    def __init__(self):
        self.cache, self.calls, self.fail_keys = {}, [], {}

    def completion(self, model, messages, api_key, caching=False, cache=None, **_):
        if api_key in self.fail_keys:
            err = Exception("provider error")
            err.status_code = self.fail_keys[api_key]
            raise err
        k = json.dumps([model, messages])
        no_cache = bool(cache and cache.get("no-cache"))
        if caching and k in self.cache and not no_cache:
            return self._resp(*self.cache[k], hit=True)
        self.calls.append(api_key)
        reply = f"echo:{messages[-1]['content']}|turns={len(messages)}"
        usage = (sum(len(m["content"].split()) for m in messages), len(reply.split()))
        self.cache[k] = (reply, usage)
        return self._resp(reply, usage, hit=False)

    @staticmethod
    def _resp(reply, usage, hit):
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=reply))],
            usage=types.SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1]),
            _hidden_params={"cache_hit": hit},
        )


@pytest.fixture
def fake(monkeypatch):
    f = FakeLiteLLM()
    monkeypatch.setattr(llm.litellm, "completion", f.completion)
    return f


@pytest.fixture
def client(tmp_path, fake):
    s = Settings(
        llm_api_keys=["k1", "k2"], database_url=f"sqlite:///{tmp_path}/t.db",
        allowed_origins=["http://localhost:3000"], enable_failure_simulation=True,
        cache_type="local",
    )
    return TestClient(create_app(s), raise_server_exceptions=False)
