from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import IMAGE_MIME_TYPES, MAX_FILE_SIZE, STORAGE_PROVIDER
from app.database import get_db
from app.models import Image, User
from app.services.drive import download_from_drive
from app.services.storage import (
    LocalStorageService,
    UploadInstruction,
    get_storage_service,
    resolve_extension,
)

router = APIRouter(tags=["upload"])


class UploadFileRequest(BaseModel):
    name: str
    size: int = Field(gt=0)
    content_type: str


class UploadInitiateRequest(BaseModel):
    files: list[UploadFileRequest]


class UploadTargetResponse(BaseModel):
    storage_key: str
    upload_url: str
    method: str
    headers: dict[str, str]
    original_name: str
    content_type: str
    size_bytes: int


class UploadInitiateResponse(BaseModel):
    files: list[UploadTargetResponse]


class CompleteUploadItem(BaseModel):
    storage_key: str
    original_name: str
    content_type: str
    size_bytes: int


class UploadCompleteRequest(BaseModel):
    files: list[CompleteUploadItem]


class UploadResponse(BaseModel):
    image_ids: list[int]
    count: int


class DriveImportRequest(BaseModel):
    url: str


def _validate_upload(file_data: UploadFileRequest) -> None:
    if file_data.content_type not in IMAGE_MIME_TYPES:
        raise HTTPException(400, f"Unsupported file type: {file_data.content_type}")
    if file_data.size > MAX_FILE_SIZE:
        raise HTTPException(400, f"File too large: {file_data.name}")
    try:
        resolve_extension(file_data.name, file_data.content_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _upsert_images(
    db: Session,
    *,
    user_id: int,
    files: list[CompleteUploadItem],
    source: str,
) -> UploadResponse:
    storage = get_storage_service()
    image_ids: list[int] = []
    for file_data in files:
        if not storage.object_exists("uploads", file_data.storage_key):
            raise HTTPException(400, f"Upload missing for {file_data.original_name}")

        image = db.query(Image).filter(Image.storage_key == file_data.storage_key).first()
        if image is None:
            image = Image(
                user_id=user_id,
                storage_key=file_data.storage_key,
                original_name=file_data.original_name,
                content_type=file_data.content_type,
                size_bytes=file_data.size_bytes,
                source=source,
                status="uploaded",
            )
            db.add(image)
            db.flush()
        elif image.user_id != user_id:
            raise HTTPException(409, "Upload key already belongs to another user")
        image_ids.append(image.id)

    db.commit()
    return UploadResponse(image_ids=image_ids, count=len(image_ids))


def _ensure_upload_belongs_to_user(kind: str, storage_key: str, user: User) -> None:
    if kind != "uploads":
        raise HTTPException(404, "Invalid upload target")
    if f"user-{user.id}/" not in storage_key:
        raise HTTPException(403, "Upload key does not belong to this user")


async def _store_uploaded_file(
    kind: str,
    storage_key: str,
    request: Request,
    user: User,
) -> dict[str, bool]:
    _ensure_upload_belongs_to_user(kind, storage_key, user)
    data = await request.body()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(400, "File too large")

    content_type = request.headers.get("content-type", "application/octet-stream")
    get_storage_service().upload_bytes(kind, storage_key, data, content_type)
    return {"ok": True}


@router.post("/uploads/initiate", response_model=UploadInitiateResponse)
def initiate_uploads(
    body: UploadInitiateRequest,
    user: User = Depends(get_current_user),
):
    storage = get_storage_service()
    files: list[UploadTargetResponse] = []
    for file_data in body.files:
        _validate_upload(file_data)
        target: UploadInstruction = storage.create_upload_target(
            user_id=user.id,
            original_name=file_data.name,
            content_type=file_data.content_type,
        )
        files.append(
            UploadTargetResponse(
                storage_key=target.storage_key,
                upload_url=target.upload_url,
                method=target.method,
                headers=target.headers,
                original_name=file_data.name,
                content_type=file_data.content_type,
                size_bytes=file_data.size,
            )
        )
    return UploadInitiateResponse(files=files)


@router.put("/uploads/local/{kind}/{storage_key:path}")
async def upload_local_asset(
    kind: str,
    storage_key: str,
    request: Request,
    user: User = Depends(get_current_user),
):
    if STORAGE_PROVIDER != "local":
        raise HTTPException(404, "Local upload endpoint is disabled")

    storage = get_storage_service()
    if not isinstance(storage, LocalStorageService):
        raise HTTPException(404, "Local upload endpoint is unavailable")
    return await _store_uploaded_file(kind, storage_key, request, user)


@router.put("/uploads/proxy/{kind}/{storage_key:path}")
async def upload_proxy_asset(
    kind: str,
    storage_key: str,
    request: Request,
    user: User = Depends(get_current_user),
):
    return await _store_uploaded_file(kind, storage_key, request, user)


@router.post("/uploads/complete", response_model=UploadResponse)
def complete_uploads(
    body: UploadCompleteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _upsert_images(db, user_id=user.id, files=body.files, source="upload")


@router.post("/import/drive", response_model=UploadResponse)
def import_from_drive(
    body: DriveImportRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    storage = get_storage_service()
    try:
        saved_files = download_from_drive(body.url, storage=storage, user_id=user.id)
    except Exception as exc:
        raise HTTPException(400, f"Failed to download from Google Drive: {exc}") from exc

    if not saved_files:
        raise HTTPException(400, "No valid images found at the provided link.")

    files = [CompleteUploadItem(**item) for item in saved_files]
    return _upsert_images(db, user_id=user.id, files=files, source="drive")


@router.get("/images")
def list_images(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    storage = get_storage_service()
    images = db.query(Image).filter(Image.user_id == user.id).order_by(Image.uploaded_at.desc()).all()
    return [
        {
            "id": image.id,
            "storage_key": image.storage_key,
            "original_name": image.original_name,
            "content_type": image.content_type,
            "size_bytes": image.size_bytes,
            "source": image.source,
            "status": image.status,
            "uploaded_at": image.uploaded_at.isoformat() if image.uploaded_at else None,
            "asset_url": storage.build_asset_url("uploads", image.storage_key),
        }
        for image in images
    ]
