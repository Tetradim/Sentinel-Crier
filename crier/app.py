import asyncio
from contextlib import asynccontextmanager
import hmac
from pathlib import Path
import time
from typing import Literal

import httpx
from fastapi import FastAPI, Depends, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
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
from .intake_routes import intake_router
from .screen_observations import screen_observation_router
from .monitors import start_monitor, stop_monitor
from .mirror_routes import configure_mirror, mirror_router
from .intent_relay import IntentRelay, sync_router
from .intent_routes import configure_device, device_router
from .quick_connect import ConnectionService, connection_router

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
            app.state.monitor = None
            device_stop = asyncio.Event()
            device_tasks = [asyncio.create_task(work(device_stop)) for work in
                            (app.state.device.publish_loop, app.state.device.receive_loop, app.state.device.execute_loop, app.state.device.diagnostics_loop)]
            try:
                app.state.monitor = start_monitor(config)
                yield
            finally:
                stop.set()
                device_stop.set()
                app.state.device.changed.set()
                # Long-poll and relay I/O can stop; let broker mutation reconcile durably before releasing ownership.
                for pending in device_tasks[:2] + device_tasks[3:]: pending.cancel()
                await asyncio.gather(*device_tasks, return_exceptions=True)
                await asyncio.to_thread(stop_monitor, app.state.monitor)
                # Let an in-flight HTTP request settle before releasing ownership.
                if task: await task

    app = FastAPI(title="Sentinel Crier", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.mirror = configure_mirror(config)
    app.state.relay = IntentRelay(config.data_dir / 'intent-relay.sqlite3')
    app.state.device = configure_device(config)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Do not reflect private receipts, tokens or account identifiers in errors.
        return JSONResponse(status_code=422, content={"detail": [
            {"loc": list(error["loc"]), "type": error["type"], "msg": error["msg"]}
            for error in exc.errors()]})

    def auth(authorization: str = Header(default="")):
        expected = "Bearer " + config.token
        if not hmac.compare_digest(authorization.encode(), expected.encode()):
            raise HTTPException(401, "Unlock with your Crier access token")

    app.include_router(intake_router(config, store, auth))
    app.include_router(screen_observation_router(store, auth, config.screen_upload_key))
    app.include_router(mirror_router(app.state.mirror, auth))
    app.include_router(sync_router(app.state.relay, auth))
    app.include_router(connection_router(ConnectionService(app.state.relay), config.public_pairing_enabled))
    app.include_router(device_router(app.state.device, auth))

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
                "monitor": {"selected": config.monitor, "running": bool(getattr(app.state, "monitor", None) and app.state.monitor.is_alive())},
                "intake": {"configured": bool(config.intake_key), "verified": config.intake_verified},
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

    @app.get("/mirror")
    def mirror_console(): return FileResponse(STATIC / "mirror.html")

    @app.get("/intent")
    def intent_console(): return FileResponse(STATIC / "intent.html")

    return app
