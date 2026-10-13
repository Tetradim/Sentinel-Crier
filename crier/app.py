import asyncio
from contextlib import asynccontextmanager
import hmac
from pathlib import Path
import time
from typing import Literal

import httpx
from fastapi import FastAPI, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Config
from .models import Settings
from .store import Store
from .cards import render
from .samples import sample
from .delivery import deliver_once
from .lock import single_process

STATIC = Path(__file__).parent / "static"


class Preview(BaseModel):
    scenario: Literal["option_buy", "option_sell", "stock_buy", "partial"] = "option_buy"
    settings: Settings = Settings()


def create_app(config=None):
    config = config or Config.from_env()
    store = Store(config.data_dir / "crier.sqlite3")

    async def sender(stop):
        with httpx.Client() as client:
            while not stop.is_set():
                if not store.get_settings().paused:
                    await asyncio.to_thread(deliver_once, store, config.webhook, client)
                try: await asyncio.wait_for(stop.wait(), timeout=2)
                except TimeoutError: pass

    @asynccontextmanager
    async def lifespan(app):
        with single_process(config.data_dir / "console.lock"):
            store.recover()
            stop = asyncio.Event()
            task = asyncio.create_task(sender(stop)) if config.delivery_enabled else None
            app.state.sender = task
            try: yield
            finally:
                stop.set()
                # Let an in-flight HTTP request settle before releasing ownership.
                if task: await task

    app = FastAPI(title="Sentinel Crier", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store

    def auth(authorization: str = Header(default="")):
        expected = "Bearer " + config.token
        if not hmac.compare_digest(authorization.encode(), expected.encode()):
            raise HTTPException(401, "Unlock with your Crier access token")

    @app.middleware("http")
    async def headers(request: Request, call_next):
        if request.method in ("POST", "PUT"):
            body = await request.body()
            if len(body) > 32768: return JSONResponse({"detail": "Request too large"}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.get("/health")
    def health(): return {"status": "ok"}

    @app.get("/api/status", dependencies=[Depends(auth)])
    def status():
        with store.connect() as db:
            row = db.execute("SELECT value FROM config WHERE id='observer'").fetchone()
        import json
        observer = json.loads(row[0]) if row else {"state": "not_started", "updated": 0}
        if time.time() - observer.get("updated", 0) > 90 and observer["state"] not in ("not_started", "stopped"):
            observer["state"] = "stale"
        return {"mode": "live" if config.delivery_enabled else "preview", "delivery_enabled": config.delivery_enabled,
                "sender_failed": bool(getattr(app.state, "sender", None) and app.state.sender.done()),
                "discord_configured": bool(config.webhook), "webull_verified": config.webull_verified,
                "observer": observer, "review_count": store.review_count(), "paused": store.get_settings().paused}

    @app.get("/api/settings", dependencies=[Depends(auth)])
    def settings(): return store.get_settings()

    @app.put("/api/settings", dependencies=[Depends(auth)])
    def update_settings(value: Settings):
        store.save_settings(value)
        return value

    @app.get("/api/history", dependencies=[Depends(auth)])
    def history(): return store.history()

    @app.post("/api/preview", dependencies=[Depends(auth)])
    def preview(value: Preview):
        try: return {"sample": True, "payload": render(sample(value.scenario), value.settings)}
        except ValueError as exc: raise HTTPException(422, str(exc))

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index(): return FileResponse(STATIC / "index.html")

    return app
