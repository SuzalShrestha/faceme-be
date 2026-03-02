import uuid
from pathlib import Path

from app.config import UPLOAD_DIR, ALLOWED_EXTENSIONS


def save_upload(file_bytes: bytes, original_name: str) -> tuple[str, str]:
    """Save uploaded file bytes and return (uuid_filename, original_name)."""
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}")
    filename = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / filename
    dest.write_bytes(file_bytes)
    return filename, original_name
