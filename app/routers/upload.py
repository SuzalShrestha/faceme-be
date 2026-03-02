from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import ALLOWED_EXTENSIONS, MAX_FILE_SIZE, UPLOAD_DIR
from app.database import get_db
from app.models import Image, User
from app.services.drive import download_from_drive
from app.auth import get_current_user

router = APIRouter(tags=["upload"])


class UploadResponse(BaseModel):
    image_ids: list[int]
    count: int


class DriveImportRequest(BaseModel):
    url: str


@router.post("/upload", response_model=UploadResponse)
async def upload_images(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    image_ids: list[int] = []

    for f in files:
        ext = Path(f.filename or "unknown.jpg").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, f"Unsupported file type: {ext}")

        data = await f.read()
        if len(data) > MAX_FILE_SIZE:
            raise HTTPException(400, f"File too large: {f.filename}")

        filename = f"{uuid.uuid4().hex}{ext}"
        (UPLOAD_DIR / filename).write_bytes(data)

        img = Image(
            user_id=user.id,
            filename=filename,
            original_name=f.filename or "unknown",
            source="upload",
        )
        db.add(img)
        db.flush()
        image_ids.append(img.id)

    db.commit()
    return UploadResponse(image_ids=image_ids, count=len(image_ids))


@router.post("/import/drive", response_model=UploadResponse)
def import_from_drive(
    body: DriveImportRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        saved_files = download_from_drive(body.url)
    except Exception as e:
        raise HTTPException(400, f"Failed to download from Google Drive: {e}")

    if not saved_files:
        raise HTTPException(400, "No valid images found at the provided link.")

    image_ids: list[int] = []
    for filename, original_name in saved_files:
        img = Image(
            user_id=user.id,
            filename=filename,
            original_name=original_name,
            source="drive",
        )
        db.add(img)
        db.flush()
        image_ids.append(img.id)

    db.commit()
    return UploadResponse(image_ids=image_ids, count=len(image_ids))


@router.get("/images")
def list_images(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    images = db.query(Image).filter(Image.user_id == user.id).order_by(Image.uploaded_at.desc()).all()
    return [
        {
            "id": img.id,
            "filename": img.filename,
            "original_name": img.original_name,
            "source": img.source,
            "uploaded_at": img.uploaded_at.isoformat() if img.uploaded_at else None,
            "processed": bool(img.processed),
        }
        for img in images
    ]
