def chat(client, sid, msg, headers=None, **extra):
    return client.post("/chat", json={"session_id": sid, "message": msg, **extra}, headers=headers or {})


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_chat_live_then_cache_in_new_session(client):
    a = chat(client, "s1", "What is the capital of France?").json()
    b = chat(client, "s2", "What is the capital of France?").json()
    assert a["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert a["metadata"]["key_id"] == "key_1" and a["metadata"]["fallback_attempts"] == 0
    assert b["metadata"]["resolution_source"] == "LLM_CACHE"
    assert b["reply"] == a["reply"]
    assert b["metadata"]["key_id"] is None and b["metadata"]["fallback_attempts"] == 0
    assert b["metadata"]["input_tokens"] == a["metadata"]["input_tokens"]


def test_different_message_not_cached(client):
    chat(client, "s1", "hello")
    assert chat(client, "s2", "different").json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_multi_turn_history_and_isolation(client):
    chat(client, "s1", "one")
    r = chat(client, "s1", "two").json()
    assert "turns=4" in r["reply"]  # system + user + assistant + user
    assert "turns=2" in chat(client, "other", "one-x").json()["reply"]
    msgs = client.get("/sessions/s1/messages").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert "metadata" in msgs[1] and "metadata" not in msgs[0]
    assert all(m["role"] != "system" for m in msgs)


def test_token_usage_is_per_request(client):
    chat(client, "s1", "a b c")
    second = chat(client, "s1", "a b c d").json()["metadata"]["input_tokens"]
    fresh = chat(client, "s9", "a b c d").json()["metadata"]["input_tokens"]
    assert second > fresh  # history adds to the prompt, but it is not a running total of outputs


def test_system_prompt_override_persists_but_is_hidden(client):
    chat(client, "s1", "hi", system_prompt="Be a pirate")
    msgs = client.get("/sessions/s1/messages").json()["messages"]
    assert len(msgs) == 2 and "Be a pirate" not in str(msgs)


def test_failover_single_key(client):
    for h in ("key_1=429", "key_1=500"):
        r = chat(client, "s-" + h, "msg " + h, {"X-Simulate-Failure": h})
        assert r.status_code == 200
        m = r.json()["metadata"]
        assert m["key_id"] == "key_2" and m["fallback_attempts"] == 1
        assert m["resolution_source"] == "LIVE_INFERENCE"


def test_all_keys_fail_503_not_stored(client):
    r = chat(client, "sx", "boom", {"X-Simulate-Failure": "*=429"})
    assert r.status_code == 503 and r.json() == {"detail": "all providers unavailable"}
    assert client.get("/sessions/sx/messages").status_code == 404


def test_real_provider_errors_fail_over(client, fake):
    fake.fail_keys = {"k1": 429}
    assert chat(client, "s1", "x").json()["metadata"]["key_id"] == "key_2"
    fake.fail_keys = {"k1": 500, "k2": 503}
    assert chat(client, "s2", "y").status_code == 503


def test_simulation_disabled_ignores_header(client, tmp_path):
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app
    s = Settings(llm_api_keys=["k1", "k2"], database_url=f"sqlite:///{tmp_path}/o.db",
                 enable_failure_simulation=False, cache_type="local")
    c = TestClient(create_app(s))
    r = chat(c, "s", "hi", {"X-Simulate-Failure": "*=429"})
    assert r.status_code == 200


def test_validation_errors(client):
    assert client.post("/chat", json={"session_id": "s", "message": "   "}).status_code == 422
    assert client.post("/chat", json={"session_id": "", "message": "hi"}).status_code == 422
    assert client.post("/chat", json={"message": "hi"}).status_code == 422
    assert chat(client, "s", "x" * 4001).status_code == 422
    r = client.post("/chat", content="{bad json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and "detail" in r.json()


def test_unknown_session_404(client):
    r = client.get("/sessions/nope/messages")
    assert r.status_code == 404 and r.json() == {"detail": "session not found"}
