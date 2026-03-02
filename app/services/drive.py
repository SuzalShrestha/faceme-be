from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

import gdown
from googleapiclient.discovery import build

from app.config import (
    ALLOWED_EXTENSIONS,
    GOOGLE_API_KEY,
    IMAGE_MIME_TYPES,
    MIME_TO_EXT,
    UPLOAD_DIR,
)

log = logging.getLogger(__name__)


def _is_folder_link(url: str) -> bool:
    return "drive.google.com/drive/folders" in url


def _extract_folder_id(url: str) -> str | None:
    m = re.search(r"drive\.google\.com/drive/folders/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else None


def _extract_file_id(url: str) -> str | None:
    patterns = [
        r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)",
        r"drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)",
        r"id=([a-zA-Z0-9_-]+)",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


def _list_folder_files_api(folder_id: str) -> list[dict]:
    """List all image files in a Drive folder using the Google Drive API v3.

    Paginates automatically so there is no file-count limit.
    """
    service = build("drive", "v3", developerKey=GOOGLE_API_KEY, cache_discovery=False)

    all_files: list[dict] = []
    page_token: str | None = None
    query = f"'{folder_id}' in parents and trashed = false"

    while True:
        resp = (
            service.files()
            .list(
                q=query,
                fields="nextPageToken, files(id, name, mimeType)",
                pageSize=1000,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        for f in resp.get("files", []):
            if f.get("mimeType") in IMAGE_MIME_TYPES:
                all_files.append(f)

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return all_files


def _download_file_gdown(file_id: str, original_name: str) -> tuple[str, str] | None:
    """Download a single file by ID using gdown. Returns (uuid_filename, original_name) or None."""
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        ext = ".jpg"  # fallback; gdown may correct it
    new_name = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / new_name
    try:
        out = gdown.download(id=file_id, output=str(dest), quiet=True)
        if out and Path(out).exists():
            actual = Path(out)
            # gdown may have written to a slightly different path; handle rename
            if actual != dest:
                final_ext = actual.suffix.lower()
                if final_ext not in ALLOWED_EXTENSIONS:
                    actual.unlink(missing_ok=True)
                    return None
                new_name = f"{uuid.uuid4().hex}{final_ext}"
                final_dest = UPLOAD_DIR / new_name
                actual.rename(final_dest)
            return (new_name, original_name)
        return None
    except Exception:
        dest.unlink(missing_ok=True)
        return None


def _download_folder_api(url: str) -> list[tuple[str, str]]:
    """Download all images from a Drive folder.

    Uses the Google Drive API to list files (no 50-file limit),
    then gdown to download each file (avoids API key 403 on get_media).
    """
    folder_id = _extract_folder_id(url)
    if not folder_id:
        raise ValueError("Could not parse folder ID from the URL.")

    files = _list_folder_files_api(folder_id)
    if not files:
        raise ValueError("No images found in the folder (or folder is not publicly shared).")

    saved: list[tuple[str, str]] = []
    for f in files:
        result = _download_file_gdown(f["id"], f["name"])
        if result:
            saved.append(result)
        else:
            log.warning("Skipping file %s (%s): download failed", f["name"], f["id"])

    return saved


def _download_folder_gdown(url: str) -> list[tuple[str, str]]:
    """Fallback: download folder with gdown (limited to ~50 files)."""
    saved: list[tuple[str, str]] = []
    temp_dir = UPLOAD_DIR / f"_tmp_{uuid.uuid4().hex}"
    temp_dir.mkdir(exist_ok=True)
    try:
        gdown.download_folder(url, output=str(temp_dir), quiet=True)
        for f in temp_dir.iterdir():
            if f.is_file() and f.suffix.lower() in ALLOWED_EXTENSIONS:
                new_name = f"{uuid.uuid4().hex}{f.suffix.lower()}"
                dest = UPLOAD_DIR / new_name
                f.rename(dest)
                saved.append((new_name, f.name))
    finally:
        for leftover in temp_dir.iterdir():
            leftover.unlink(missing_ok=True)
        temp_dir.rmdir()
    return saved


def download_from_drive(url: str) -> list[tuple[str, str]]:
    """Download images from a Google Drive link.

    Returns list of (uuid_filename, original_name) tuples for each valid image.
    Uses the Google Drive API to list folder contents when GOOGLE_API_KEY is set
    (no file-count limit), then gdown to download each file.
    Falls back to gdown for everything if no API key is configured.
    """
    if _is_folder_link(url):
        if GOOGLE_API_KEY:
            return _download_folder_api(url)

        log.warning(
            "GOOGLE_API_KEY not set — using gdown fallback. "
            "Folders with more than ~50 files will fail."
        )
        return _download_folder_gdown(url)

    file_id = _extract_file_id(url)
    if not file_id:
        raise ValueError("Could not parse Google Drive file ID from the URL.")

    result = _download_file_gdown(file_id, "unknown.jpg")
    if result:
        return [result]

    raise ValueError("Download failed — the file may not be publicly shared.")
