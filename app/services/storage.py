from __future__ import annotations

import mimetypes
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Literal

from app.config import (
    ALLOWED_EXTENSIONS,
    AZURE_FACES_CONTAINER,
    AZURE_STORAGE_ACCOUNT_URL,
    AZURE_STORAGE_CONNECTION_STRING,
    AZURE_UPLOADS_CONTAINER,
    LOCAL_FACES_DIR,
    LOCAL_UPLOAD_DIR,
    MIME_TO_EXT,
    SIGNED_URL_TTL_SECONDS,
    STORAGE_PROVIDER,
)

StorageKind = Literal["uploads", "faces"]


@dataclass
class UploadInstruction:
    storage_key: str
    upload_url: str
    method: str = "PUT"
    headers: dict[str, str] = field(default_factory=dict)


class StorageService:
    def create_upload_target(
        self, *, user_id: int, original_name: str, content_type: str
    ) -> UploadInstruction:
        raise NotImplementedError

    def new_upload_key(self, *, user_id: int, original_name: str, content_type: str) -> str:
        return f"user-{user_id}/{uuid.uuid4().hex}{resolve_extension(original_name, content_type)}"

    def new_face_key(self, *, user_id: int) -> str:
        return f"user-{user_id}/{uuid.uuid4().hex}.jpg"

    def upload_bytes(self, kind: StorageKind, storage_key: str, data: bytes, content_type: str) -> None:
        raise NotImplementedError

    def download_bytes(self, kind: StorageKind, storage_key: str) -> bytes:
        raise NotImplementedError

    def delete_bytes(self, kind: StorageKind, storage_key: str) -> None:
        raise NotImplementedError

    def object_exists(self, kind: StorageKind, storage_key: str) -> bool:
        raise NotImplementedError

    def build_asset_url(self, kind: StorageKind, storage_key: str) -> str:
        raise NotImplementedError

    def readiness_check(self) -> None:
        raise NotImplementedError


def resolve_extension(original_name: str, content_type: str) -> str:
    ext = Path(original_name).suffix.lower()
    if ext in ALLOWED_EXTENSIONS:
        return ext
    if content_type in MIME_TO_EXT:
        return MIME_TO_EXT[content_type]
    raise ValueError(f"Unsupported file type: {original_name}")


def guess_content_type(storage_key: str) -> str:
    content_type = mimetypes.guess_type(storage_key)[0]
    return content_type or "application/octet-stream"


class LocalStorageService(StorageService):
    def __init__(self) -> None:
        self.roots = {
            "uploads": LOCAL_UPLOAD_DIR,
            "faces": LOCAL_FACES_DIR,
        }

    def _ensure_dirs(self) -> None:
        for root in self.roots.values():
            root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, kind: StorageKind, storage_key: str) -> Path:
        root = self.roots[kind].resolve()
        path = (root / storage_key).resolve()
        if root not in path.parents and path != root:
            raise ValueError("Invalid storage key")
        return path

    def create_upload_target(
        self, *, user_id: int, original_name: str, content_type: str
    ) -> UploadInstruction:
        storage_key = self.new_upload_key(
            user_id=user_id,
            original_name=original_name,
            content_type=content_type,
        )
        return UploadInstruction(
            storage_key=storage_key,
            upload_url=f"/api/uploads/local/uploads/{storage_key}",
        )

    def upload_bytes(self, kind: StorageKind, storage_key: str, data: bytes, content_type: str) -> None:
        self._ensure_dirs()
        path = self._path_for(kind, storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def download_bytes(self, kind: StorageKind, storage_key: str) -> bytes:
        return self._path_for(kind, storage_key).read_bytes()

    def delete_bytes(self, kind: StorageKind, storage_key: str) -> None:
        path = self._path_for(kind, storage_key)
        if path.exists():
            path.unlink()

    def object_exists(self, kind: StorageKind, storage_key: str) -> bool:
        return self._path_for(kind, storage_key).exists()

    def build_asset_url(self, kind: StorageKind, storage_key: str) -> str:
        return f"/api/assets/{kind}/{storage_key}"

    def readiness_check(self) -> None:
        self._ensure_dirs()


class AzureBlobStorageService(StorageService):
    def __init__(self) -> None:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        if AZURE_STORAGE_CONNECTION_STRING:
            self.service_client = BlobServiceClient.from_connection_string(
                AZURE_STORAGE_CONNECTION_STRING
            )
            self.account_name = self.service_client.account_name
            self.account_key = _parse_connection_value(
                AZURE_STORAGE_CONNECTION_STRING,
                "AccountKey",
            )
        elif AZURE_STORAGE_ACCOUNT_URL:
            self.service_client = BlobServiceClient(
                account_url=AZURE_STORAGE_ACCOUNT_URL,
                credential=DefaultAzureCredential(),
            )
            self.account_name = self.service_client.account_name
            self.account_key = None
        else:
            raise RuntimeError("Azure storage configuration is missing")

        self.containers = {
            "uploads": AZURE_UPLOADS_CONTAINER,
            "faces": AZURE_FACES_CONTAINER,
        }
        self._delegation_key = None
        self._delegation_key_expiry: datetime | None = None

    def _blob_client(self, kind: StorageKind, storage_key: str):
        container = self.containers[kind]
        return self.service_client.get_blob_client(container=container, blob=storage_key)

    def _get_user_delegation_key(self):
        now = datetime.now(timezone.utc)
        if self._delegation_key and self._delegation_key_expiry and now < self._delegation_key_expiry:
            return self._delegation_key

        start = now - timedelta(minutes=5)
        expiry = now + timedelta(hours=1)
        self._delegation_key = self.service_client.get_user_delegation_key(
            key_start_time=start,
            key_expiry_time=expiry,
        )
        self._delegation_key_expiry = expiry - timedelta(minutes=5)
        return self._delegation_key

    def _generate_sas(self, kind: StorageKind, storage_key: str, *, write: bool) -> str:
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        expires_on = datetime.now(timezone.utc) + timedelta(seconds=SIGNED_URL_TTL_SECONDS)
        permissions = BlobSasPermissions(read=not write, create=write, write=write)
        kwargs: dict[str, object] = {
            "account_name": self.account_name,
            "container_name": self.containers[kind],
            "blob_name": storage_key,
            "permission": permissions,
            "expiry": expires_on,
        }
        if self.account_key:
            kwargs["account_key"] = self.account_key
        else:
            kwargs["user_delegation_key"] = self._get_user_delegation_key()
        return generate_blob_sas(**kwargs)

    def create_upload_target(
        self, *, user_id: int, original_name: str, content_type: str
    ) -> UploadInstruction:
        storage_key = self.new_upload_key(
            user_id=user_id,
            original_name=original_name,
            content_type=content_type,
        )
        blob_client = self._blob_client("uploads", storage_key)
        sas = self._generate_sas("uploads", storage_key, write=True)
        return UploadInstruction(
            storage_key=storage_key,
            upload_url=f"{blob_client.url}?{sas}",
            headers={
                "x-ms-blob-type": "BlockBlob",
                "Content-Type": content_type,
            },
        )

    def upload_bytes(self, kind: StorageKind, storage_key: str, data: bytes, content_type: str) -> None:
        from azure.storage.blob import ContentSettings

        self._blob_client(kind, storage_key).upload_blob(
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )

    def download_bytes(self, kind: StorageKind, storage_key: str) -> bytes:
        return self._blob_client(kind, storage_key).download_blob().readall()

    def delete_bytes(self, kind: StorageKind, storage_key: str) -> None:
        self._blob_client(kind, storage_key).delete_blob(delete_snapshots="include")

    def object_exists(self, kind: StorageKind, storage_key: str) -> bool:
        return self._blob_client(kind, storage_key).exists()

    def build_asset_url(self, kind: StorageKind, storage_key: str) -> str:
        blob_client = self._blob_client(kind, storage_key)
        return f"{blob_client.url}?{self._generate_sas(kind, storage_key, write=False)}"

    def readiness_check(self) -> None:
        for container_name in self.containers.values():
            self.service_client.get_container_client(container_name).get_container_properties()


def _parse_connection_value(connection_string: str, key: str) -> str | None:
    prefix = f"{key}="
    for item in connection_string.split(";"):
        if item.startswith(prefix):
            return item[len(prefix):]
    return None


@lru_cache(maxsize=1)
def get_storage_service() -> StorageService:
    if STORAGE_PROVIDER == "azure":
        return AzureBlobStorageService()
    return LocalStorageService()
