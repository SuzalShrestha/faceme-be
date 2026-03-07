from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

import gdown
from googleapiclient.discovery import build

from app.config import GOOGLE_API_KEY, IMAGE_MIME_TYPES
from app.services.storage import StorageService, guess_content_type

log = logging.getLogger(__name__)


def _is_folder_link(url: str) -> bool:
    return "drive.google.com/drive/folders" in url


def _extract_folder_id(url: str) -> str | None:
    match = re.search(r"drive\.google\.com/drive/folders/([a-zA-Z0-9_-]+)", url)
    return match.group(1) if match else None


def _extract_file_id(url: str) -> str | None:
    patterns = [
        r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)",
        r"drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)",
        r"id=([a-zA-Z0-9_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _list_folder_files_api(folder_id: str) -> list[dict]:
    service = build("drive", "v3", developerKey=GOOGLE_API_KEY, cache_discovery=False)
    all_files: list[dict] = []
    page_token: str | None = None
    query = f"'{folder_id}' in parents and trashed = false"

    while True:
        response = (
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
        for file_data in response.get("files", []):
            if file_data.get("mimeType") in IMAGE_MIME_TYPES:
                all_files.append(file_data)
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return all_files


def _download_file_gdown(file_id: str, *, suffix: str) -> bytes | None:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
        temp_path = Path(temp_file.name)
    try:
        result = gdown.download(id=file_id, output=str(temp_path), quiet=True)
        if not result:
            return None
        return temp_path.read_bytes()
    except Exception:
        return None
    finally:
        temp_path.unlink(missing_ok=True)


def _upload_downloaded_file(
    *,
    storage: StorageService,
    user_id: int,
    original_name: str,
    file_id: str,
    content_type: str,
) -> dict | None:
    data = _download_file_gdown(file_id, suffix=Path(original_name).suffix or ".jpg")
    if not data:
        return None

    storage_key = storage.new_upload_key(
        user_id=user_id,
        original_name=original_name,
        content_type=content_type,
    )
    storage.upload_bytes("uploads", storage_key, data, content_type)
    return {
        "storage_key": storage_key,
        "original_name": original_name,
        "content_type": content_type or guess_content_type(storage_key),
        "size_bytes": len(data),
    }


def download_from_drive(url: str, *, storage: StorageService, user_id: int) -> list[dict]:
    if _is_folder_link(url):
        folder_id = _extract_folder_id(url)
        if not folder_id:
            raise ValueError("Could not parse folder ID from the URL.")
        if not GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY is required to import Drive folders in production mode.")

        files = _list_folder_files_api(folder_id)
        if not files:
            raise ValueError("No images found in the folder (or folder is not publicly shared).")

        saved: list[dict] = []
        for file_data in files:
            uploaded = _upload_downloaded_file(
                storage=storage,
                user_id=user_id,
                original_name=file_data["name"],
                file_id=file_data["id"],
                content_type=file_data["mimeType"],
            )
            if uploaded:
                saved.append(uploaded)
            else:
                log.warning("Skipping Drive file %s (%s)", file_data["name"], file_data["id"])
        return saved

    file_id = _extract_file_id(url)
    if not file_id:
        raise ValueError("Could not parse Google Drive file ID from the URL.")

    uploaded = _upload_downloaded_file(
        storage=storage,
        user_id=user_id,
        original_name="drive-import.jpg",
        file_id=file_id,
        content_type="image/jpeg",
    )
    if not uploaded:
        raise ValueError("Download failed — the file may not be publicly shared.")
    return [uploaded]
