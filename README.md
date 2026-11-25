# LLM Chatbot with Key Failover and Response Caching

React + FastAPI + SQLite, with LiteLLM handling the LLM calls and the response cache.

## 1. Live URLs

- Frontend: `<add after deploy>`
- Backend: `<add after deploy>` (try `/health`)
- Repo: https://github.com/Dibyanshushekhar/lyftr-chatbot
- Demo video: `<add link>`

## 2. Run locally

**With Docker** (needs Docker + make):

```bash
cp .env.example .env     # put at least 2 real keys in LLM_API_KEYS
make up                  # frontend http://localhost:3000, backend http://localhost:8000
make down
```

**Without Docker:**

```bash
# backend
cd backend
pip install -r requirements-dev.txt
export LLM_API_KEYS=key1,key2 DATABASE_URL=sqlite:///./app.db ENABLE_FAILURE_SIMULATION=true
uvicorn app.main:app --port 8000
python -m pytest -q      # tests (LiteLLM is faked, no keys needed)

# frontend (new terminal)
cd frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev    # http://localhost:3000
```

Environment variables: `LLM_API_KEYS`, `DATABASE_URL`, `ALLOWED_ORIGINS`, `ENABLE_FAILURE_SIMULATION`, plus `LLM_MODEL`, `CACHE_TYPE`, `LLM_TIMEOUT`, `MAX_OUTPUT_TOKENS`, `DEFAULT_SYSTEM_PROMPT`, and (frontend build-time) `VITE_API_URL`. See `.env.example`.

## 3. Design decisions

**Key fallback.** `LLM_API_KEYS` is parsed into `key_1..key_N`. For each request the gateway (`backend/app/llm.py`) calls `litellm.completion` with the first key; on any exception (429, quota, 5xx, timeout, auth error, empty completion) it moves to the next key. `fallback_attempts` counts the failures before success. If all keys fail, the API returns `503 {"detail": "all providers unavailable"}` and nothing is saved. Keys are never returned or logged, only `key_N` ids. I wrote the loop myself instead of using LiteLLM's Router so that `key_id` and `fallback_attempts` are exact and `X-Simulate-Failure` can be injected per key.

**Caching.** LiteLLM's built-in cache (`litellm.Cache(type="local")`, in-memory) is enabled with `caching=True`. LiteLLM builds the cache key from the model and the full message list (system prompt + history + new message), so the same first message in a new session hits the cache and a different message never does. A hit is detected via `_hidden_params["cache_hit"]`; the reply text and token usage are the stored ones, and `key_id` is `null`. The cache lives in process memory, so it resets on restart. The LiteLLM version I tested does not support a `disk` cache type, so in-memory is the default (the code falls back to it automatically).

**Failure simulation.** With `ENABLE_FAILURE_SIMULATION=true`, `X-Simulate-Failure` marks keys as failed for that one request only. The provider is not called for those keys. To avoid a cache hit hiding the failover, requests carrying the header skip the cache lookup (`cache={"no-cache": True}`).

**SQLite session storage.** Plain `sqlite3`, schema created on startup, file at `DATABASE_URL` (`/data/app.db`, on the `app_data` Docker volume). Tables: `messages` (the contract schema plus an index) and `sessions` (per-session system prompt). The user message and assistant reply are written in one transaction only after a successful LLM response, so 422/503 requests never touch history. Each request loads the stored history, appends the new message and sends it all to the LLM. `latency_ms` is measured server-side per request; token counts come from the provider's usage for that request only.

## 4. Verification

```bash
B=http://localhost:8000
curl $B/health
# live, then cache hit (new session, same message)
curl -s $B/chat -H 'content-type: application/json' -d '{"session_id":"a1","message":"What is the capital of France?"}'
curl -s $B/chat -H 'content-type: application/json' -d '{"session_id":"a2","message":"What is the capital of France?"}'   # LLM_CACHE, key_id null, lower latency
# multi-turn memory
curl -s $B/chat -H 'content-type: application/json' -d '{"session_id":"a1","message":"What did I just ask?"}'
curl -s $B/sessions/a1/messages
# failover
curl -s $B/chat -H 'content-type: application/json' -H 'X-Simulate-Failure: key_1=429' -d '{"session_id":"f1","message":"hello"}'   # key_id: key_2
curl -s $B/chat -H 'content-type: application/json' -H 'X-Simulate-Failure: *=429' -d '{"session_id":"f2","message":"hello"}'      # 503
# validation / 404
curl -s $B/chat -H 'content-type: application/json' -d '{"session_id":"x","message":"   "}'   # 422
curl -s $B/sessions/nope/messages                                                              # 404
```

In the UI each reply shows source, model, latency, input tokens and output tokens. The "Session settings" panel has the system prompt field and a failure-simulation dropdown for demos.

## 5. Setup Used

- Editor: `<your editor>`
- AI tools: Claude (code generation), LiteLLM docs for cache and exception behavior.

## 6. Bonus features

- Failure-simulation dropdown in the UI (sends `X-Simulate-Failure`), so failover can be shown without curl.
- Optional per-session system prompt field.
- Dark mode, Docker healthcheck, `make test` and `make logs`, non-root backend container.

## Deployment notes

- **Backend** (Render / Railway / Fly.io, Docker, root dir `backend`): set `LLM_API_KEYS`, `DATABASE_URL=sqlite:////data/app.db`, `ALLOWED_ORIGINS=<frontend URL>`, `ENABLE_FAILURE_SIMULATION=true`, and attach a persistent volume at `/data` (Render free tier has no disks, so use a paid disk, Railway or Fly volume for history to survive restarts).
- **Frontend** (Vercel / Netlify, root dir `frontend`, build `npm run build`, output `dist`): set `VITE_API_URL=<backend URL>`.
