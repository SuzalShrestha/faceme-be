from __future__ import annotations

import json
import logging

import cv2
import numpy as np
from sqlalchemy.orm import Session

from app.config import INSIGHTFACE_DET_HEIGHT, INSIGHTFACE_DET_WIDTH, INSIGHTFACE_MODEL_NAME
from app.models import Face, Image
from app.services.storage import StorageService

log = logging.getLogger(__name__)

_face_app = None


def _get_face_app():
    global _face_app
    if _face_app is None:
        from insightface.app import FaceAnalysis

        _face_app = FaceAnalysis(
            name=INSIGHTFACE_MODEL_NAME,
            providers=["CPUExecutionProvider"],
        )
        _face_app.prepare(
            ctx_id=0,
            det_size=(INSIGHTFACE_DET_WIDTH, INSIGHTFACE_DET_HEIGHT),
        )
    return _face_app


def warm_face_engine() -> None:
    _get_face_app()


def _decode_image(data: bytes):
    image_array = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(image_array, cv2.IMREAD_COLOR)


def _clear_existing_faces(image: Image, db: Session, storage: StorageService) -> None:
    existing_faces = db.query(Face).filter(Face.image_id == image.id).all()
    for face in existing_faces:
        try:
            storage.delete_bytes("faces", face.crop_key)
        except Exception:
            log.warning("Failed to delete stale face asset %s", face.crop_key, exc_info=True)
    db.query(Face).filter(Face.image_id == image.id).delete(synchronize_session=False)
    db.flush()


def process_image(image: Image, db: Session, storage: StorageService) -> int:
    raw_bytes = storage.download_bytes("uploads", image.storage_key)
    img_bgr = _decode_image(raw_bytes)
    if img_bgr is None:
        raise ValueError(f"Could not decode image {image.original_name}")

    _clear_existing_faces(image, db, storage)

    app = _get_face_app()
    detected = app.get(img_bgr)

    count = 0
    for face_obj in detected:
        bbox = face_obj.bbox.astype(int).tolist()
        embedding = face_obj.normed_embedding.astype(np.float32)
        det_score = float(face_obj.det_score) if hasattr(face_obj, "det_score") else 0.0

        x1, y1, x2, y2 = bbox
        height, width = img_bgr.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(width, x2), min(height, y2)
        crop = img_bgr[y1:y2, x1:x2]
        if crop.size == 0:
            continue

        crop_resized = cv2.resize(crop, (160, 160))
        success, encoded = cv2.imencode(".jpg", crop_resized)
        if not success:
            continue

        crop_key = storage.new_face_key(user_id=image.user_id)
        storage.upload_bytes("faces", crop_key, encoded.tobytes(), "image/jpeg")
        db.add(
            Face(
                image_id=image.id,
                embedding=embedding.tobytes(),
                bbox=json.dumps(bbox),
                crop_key=crop_key,
                det_score=str(det_score),
            )
        )
        count += 1

    image.status = "processed"
    image.processing_error = None
    image.processed_at = image.processed_at or image.uploaded_at
    db.flush()
    return count


def process_images(
    image_ids: list[int] | None,
    db: Session,
    storage: StorageService,
    *,
    user_id: int,
) -> dict:
    if image_ids:
        images = (
            db.query(Image)
            .filter(Image.id.in_(image_ids), Image.user_id == user_id)
            .order_by(Image.uploaded_at.asc())
            .all()
        )
    else:
        images = (
            db.query(Image)
            .filter(Image.user_id == user_id, Image.status != "processed")
            .order_by(Image.uploaded_at.asc())
            .all()
        )

    total_faces = 0
    processed_count = 0
    failed_count = 0
    for image in images:
        image.status = "processing"
        image.processing_error = None
        db.commit()
        try:
            total_faces += process_image(image, db, storage)
            processed_count += 1
            db.commit()
        except Exception as exc:
            failed_count += 1
            image.status = "failed"
            image.processing_error = str(exc)
            db.commit()
            log.exception("Failed processing image %s", image.id)

    return {
        "images_processed": processed_count,
        "images_failed": failed_count,
        "faces_detected": total_faces,
    }
