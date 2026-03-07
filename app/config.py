from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://faceme:faceme@localhost:5432/faceme")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "super-secret-change-me-in-production-09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7",
)

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_FILE_SIZE = 20 * 1024 * 1024

IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
MIME_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "faceme_session")
SESSION_COOKIE_DOMAIN = os.getenv("SESSION_COOKIE_DOMAIN") or None
SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "lax")
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
SESSION_MAX_AGE_SECONDS = int(os.getenv("SESSION_MAX_AGE_SECONDS", str(60 * 60 * 24 * 30)))
GOOGLE_OAUTH_CLIENT_IDS = [
    client_id.strip()
    for client_id in os.getenv("GOOGLE_OAUTH_CLIENT_IDS", "").split(",")
    if client_id.strip()
]

RATE_LIMIT_AUTH_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_AUTH_MAX_REQUESTS", "10"))
RATE_LIMIT_AUTH_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_AUTH_WINDOW_SECONDS", "60"))
RATE_LIMIT_WRITE_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_WRITE_MAX_REQUESTS", "120"))
RATE_LIMIT_WRITE_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WRITE_WINDOW_SECONDS", "60"))

SIGNED_URL_TTL_SECONDS = int(os.getenv("SIGNED_URL_TTL_SECONDS", "900"))
PHOTO_ENCRYPTION_KEY = os.getenv("PHOTO_ENCRYPTION_KEY", SECRET_KEY)

STORAGE_PROVIDER = os.getenv("STORAGE_PROVIDER", "local")
LOCAL_STORAGE_ROOT = Path(os.getenv("LOCAL_STORAGE_ROOT", str(BASE_DIR / "storage")))
LOCAL_UPLOAD_DIR = LOCAL_STORAGE_ROOT / "uploads"
LOCAL_FACES_DIR = LOCAL_STORAGE_ROOT / "faces"

AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
AZURE_STORAGE_ACCOUNT_URL = os.getenv("AZURE_STORAGE_ACCOUNT_URL", "")
AZURE_UPLOADS_CONTAINER = os.getenv("AZURE_UPLOADS_CONTAINER", "uploads")
AZURE_FACES_CONTAINER = os.getenv("AZURE_FACES_CONTAINER", "faces")

QUEUE_PROVIDER = os.getenv("QUEUE_PROVIDER", "database")
AZURE_QUEUE_CONNECTION_STRING = os.getenv("AZURE_QUEUE_CONNECTION_STRING", "")
AZURE_QUEUE_ACCOUNT_URL = os.getenv("AZURE_QUEUE_ACCOUNT_URL", "")
AZURE_QUEUE_NAME = os.getenv("AZURE_QUEUE_NAME", "face-pipeline")
WORKER_POLL_INTERVAL_SECONDS = float(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "2"))
QUEUE_VISIBILITY_TIMEOUT = int(os.getenv("QUEUE_VISIBILITY_TIMEOUT", "300"))

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

INSIGHTFACE_MODEL_NAME = os.getenv("INSIGHTFACE_MODEL_NAME", "buffalo_l")
INSIGHTFACE_DET_WIDTH = int(os.getenv("INSIGHTFACE_DET_WIDTH", "640"))
INSIGHTFACE_DET_HEIGHT = int(os.getenv("INSIGHTFACE_DET_HEIGHT", "640"))
INSIGHTFACE_MODEL_ROOT = os.getenv("INSIGHTFACE_MODEL_ROOT", "")
