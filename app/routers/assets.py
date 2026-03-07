from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Face, Image, User
from app.services.storage import get_storage_service, guess_content_type

router = APIRouter(tags=["assets"])


@router.get("/assets/uploads/{storage_key:path}")
def get_upload_asset(
    storage_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    image = db.query(Image).filter(Image.user_id == user.id, Image.storage_key == storage_key).first()
    if not image:
        raise HTTPException(404, "Asset not found")
    data = get_storage_service().download_bytes("uploads", storage_key)
    return Response(content=data, media_type=image.content_type or guess_content_type(storage_key))


@router.get("/assets/faces/{storage_key:path}")
def get_face_asset(
    storage_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    face = (
        db.query(Face)
        .join(Image, Face.image_id == Image.id)
        .filter(Image.user_id == user.id, Face.crop_key == storage_key)
        .first()
    )
    if not face:
        raise HTTPException(404, "Asset not found")
    data = get_storage_service().download_bytes("faces", storage_key)
    return Response(content=data, media_type="image/jpeg")
