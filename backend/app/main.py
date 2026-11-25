import logging
import time
from typing import Annotated, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints

from .config import Settings
from .db import Database
from .llm import AllProvidersUnavailable, LLMGateway, ms_since, parse_simulation

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")


class ChatRequest(BaseModel):
    session_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    system_prompt: Optional[Annotated[str, Field(max_length=4000)]] = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    db = Database(settings.database_url)
    gateway = LLMGateway(
        keys=settings.llm_api_keys, model=settings.llm_model, cache_type=settings.cache_type,
        cache_dir=settings.cache_dir, timeout=settings.llm_timeout, max_tokens=settings.max_output_tokens,
    )

    app = FastAPI(title="LLM Chatbot")
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.allowed_origins,
        allow_methods=["*"], allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):  # never leak stack traces / HTML
        log.exception("unhandled error")
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    @app.get("/health")
    def health():
        if not db.ping():
            raise HTTPException(503, "database unavailable")
        return {"status": "ok", "keys_configured": len(gateway.keys), "cache_enabled": gateway.cache_enabled}

    @app.post("/chat")
    def chat(req: ChatRequest, x_simulate_failure: Optional[str] = Header(default=None)):
        start = time.perf_counter()
        sid = req.system_prompt and req.system_prompt.strip() and req.system_prompt.strip()
        system_prompt = sid or db.get_system_prompt(req.session_id) or settings.default_system_prompt
        messages = (
            [{"role": "system", "content": system_prompt}]
            + db.get_history(req.session_id)
            + [{"role": "user", "content": req.message}]
        )
        simulate = parse_simulation(x_simulate_failure) if settings.enable_failure_simulation else {}
        try:
            result = gateway.complete(messages, simulate)
        except AllProvidersUnavailable:
            raise HTTPException(503, "all providers unavailable")

        metadata = {
            "resolution_source": "LLM_CACHE" if result.cache_hit else "LIVE_INFERENCE",
            "model": result.model,
            "latency_ms": ms_since(start, time.perf_counter()),
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "key_id": result.key_id,
            "fallback_attempts": result.fallback_attempts,
        }
        db.add_exchange(req.session_id, req.message, result.reply, metadata, sid or None)
        return {"session_id": req.session_id, "reply": result.reply, "metadata": metadata}

    @app.get("/sessions/{session_id}/messages")
    def session_messages(session_id: str):
        msgs = db.get_messages(session_id)
        if msgs is None:
            raise HTTPException(404, "session not found")
        return {"session_id": session_id, "messages": msgs}

    return app


app = create_app()
