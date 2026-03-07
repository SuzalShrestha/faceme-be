from __future__ import annotations

from fastapi import FastAPI, HTTPException

from app.database import check_database
from app.services.queue import get_queue_service
from app.services.storage import get_storage_service
from app.worker_runtime import worker_runtime

app = FastAPI(title="Face-Me Worker", description="Background worker for face processing")


@app.on_event("startup")
def on_startup() -> None:
    worker_runtime.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    worker_runtime.stop()


@app.get("/api/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health/ready")
def ready() -> dict[str, str]:
    check_database()
    get_storage_service().readiness_check()
    get_queue_service().readiness_check()
    if not worker_runtime.ready:
        raise HTTPException(status_code=503, detail="Worker runtime is not ready")
    return {"status": "ready"}
