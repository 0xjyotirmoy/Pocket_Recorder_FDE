import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy import text

from . import config, events
from . import worker as worker_mod
from .db import SessionLocal, init_db
from .models import Recording
from .routers import chat, ingest, recordings, search
from .services.ingest import IngestError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if config.WORKER_ENABLED:
        worker_mod.worker = worker_mod.Worker()
        worker_mod.worker.start()
    yield
    if worker_mod.worker:
        worker_mod.worker.stop()
        worker_mod.worker.join(timeout=5)


app = FastAPI(title="Meeting Intelligence Platform", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"],
                   allow_headers=["*"])


@app.exception_handler(IngestError)
async def ingest_error(_: Request, exc: IngestError):
    return JSONResponse({"error": exc.message}, status_code=exc.status)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    msg = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors())
    return JSONResponse({"error": msg or "invalid request"}, status_code=422)


@app.get("/events", include_in_schema=False)
async def live_events():
    """Server-Sent Events: the dashboard updates the moment a clip arrives or finishes processing."""
    return StreamingResponse(events.stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/health")
def health():
    db_ok = True
    queue = 0
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            queue = db.query(Recording).filter(Recording.status.in_(["queued", "transcribing", "extracting"])).count()
    except Exception:  # noqa: BLE001
        db_ok = False
    w = worker_mod.worker
    return {"ok": db_ok, "db": db_ok, "worker_alive": bool(w and w.is_alive()), "queue_depth": queue,
            "processing": w.current if w else None, "asr": config.ASR_PROVIDER, "llm": config.LLM_MODEL}


for r in (ingest.router, recordings.router, search.router, chat.router):
    app.include_router(r)


# ---- dashboard: the built React app is served from /app (one server, one URL) ----------------
DIST = config.ROOT / "frontend" / "dist"


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/app/" if (DIST / "index.html").exists() else "/docs")


@app.get("/app", include_in_schema=False)
@app.get("/app/{path:path}", include_in_schema=False)
def dashboard(path: str = ""):
    if not (DIST / "index.html").exists():
        return JSONResponse({"error": "dashboard not built: frontend/dist is missing"}, status_code=404)
    f = (DIST / path).resolve()
    if path and f.is_file() and DIST.resolve() in f.parents:
        return FileResponse(f)
    return FileResponse(DIST / "index.html")  # client-side routes
