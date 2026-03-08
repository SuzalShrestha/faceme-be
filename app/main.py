import hashlib
import json

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import CORS_ORIGINS
from app.database import check_database
from app.routers import auth, faces, jobs, upload
from app.routers.assets import router as assets_router
from app.services.queue import get_queue_service
from app.services.storage import get_storage_service


class CacheControlMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add caching headers to GET requests.
    This enables frontend caching libraries like TanStack Query to work efficiently.
    """

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        # Only add cache headers to successful GET requests on API endpoints
        if request.method == "GET" and response.status_code == 200:
            path = request.url.path

            # Add cache headers to list endpoints that support search/pagination
            if any(endpoint in path for endpoint in ["/api/clusters", "/api/images", "/api/ungrouped"]):
                # For list endpoints with query params, use shorter cache
                # This supports debounced search while still caching results
                response.headers["Cache-Control"] = "private, max-age=60, must-revalidate"

                # Generate ETag based on response body for validation
                # We need to consume the response body to calculate the hash
                body_bytes = b""
                async for chunk in response.body_iterator:
                    body_bytes += chunk

                # Generate ETag
                etag = hashlib.md5(body_bytes).hexdigest()

                # Check If-None-Match header for conditional requests
                if request.headers.get("If-None-Match") == f'"{etag}"':
                    return Response(status_code=304, headers={"ETag": f'"{etag}"', "Cache-Control": response.headers["Cache-Control"]})

                # Return a new response with the consumed body and ETag
                return Response(
                    content=body_bytes,
                    status_code=response.status_code,
                    headers={**dict(response.headers), "ETag": f'"{etag}"'},
                    media_type=response.media_type,
                )

        return response


app = FastAPI(title="Face-Me", description="AI-powered face grouping SaaS")

# Add caching middleware before CORS
app.add_middleware(CacheControlMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["ETag", "Cache-Control"],  # Expose cache headers to frontend
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
