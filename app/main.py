from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import (
    CORS_ORIGINS,
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_EXEMPT_PATHS,
    RATE_LIMIT_REQUESTS_PER_MINUTE,
    RATE_LIMIT_WINDOW_SECONDS,
)
from app.database import check_database
from app.middleware.rate_limit import RateLimiterMiddleware
from app.routers import auth, faces, jobs, upload
from app.routers.assets import router as assets_router
from app.services.queue import get_queue_service
from app.services.storage import get_storage_service

app = FastAPI(title="Face-Me", description="AI-powered face grouping SaaS")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if RATE_LIMIT_ENABLED:
    app.add_middleware(
        RateLimiterMiddleware,
        max_requests=RATE_LIMIT_REQUESTS_PER_MINUTE,
        window_seconds=RATE_LIMIT_WINDOW_SECONDS,
        exempt_paths=RATE_LIMIT_EXEMPT_PATHS,
    )

app.include_router(auth.router, prefix="/api")
app.include_router(upload.router, prefix="/api")
app.include_router(faces.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(assets_router, prefix="/api")


@app.get("/api/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health/ready")
def ready() -> dict[str, str]:
    check_database()
    get_storage_service().readiness_check()
    get_queue_service().readiness_check()
    return {"status": "ready"}
