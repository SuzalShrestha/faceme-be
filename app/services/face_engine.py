from __future__ import annotations

import json
import uuid
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy.orm import Session

from app.config import FACES_DIR, UPLOAD_DIR
from app.models import Face, Image

_face_app = None


def _get_face_app():
    global _face_app
    if _face_app is None:
        from insightface.app import FaceAnalysis

        _face_app = FaceAnalysis(
            name="buffalo_l",
            providers=["CPUExecutionProvider"],
        )
        _face_app.prepare(ctx_id=0, det_size=(640, 640))
    return _face_app


def process_image(image: Image, db: Session) -> int:
    """Detect faces in a single image, extract embeddings, save crops.

    Returns the number of faces detected.
    """
    img_path = UPLOAD_DIR / image.filename
    if not img_path.exists():
        return 0

    img_bgr = cv2.imread(str(img_path))
    if img_bgr is None:
        return 0

    app = _get_face_app()
    detected = app.get(img_bgr)

    count = 0
    for face_obj in detected:
        bbox = face_obj.bbox.astype(int).tolist()
        embedding = face_obj.normed_embedding.astype(np.float32)
        det_score = float(face_obj.det_score) if hasattr(face_obj, "det_score") else 0.0

        x1, y1, x2, y2 = bbox
        h, w = img_bgr.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        crop = img_bgr[y1:y2, x1:x2]
        if crop.size == 0:
            continue

        crop_resized = cv2.resize(crop, (160, 160))
        crop_filename = f"{uuid.uuid4().hex}.jpg"
        crop_path = FACES_DIR / crop_filename
        cv2.imwrite(str(crop_path), crop_resized)

        face_record = Face(
            image_id=image.id,
            embedding=embedding.tobytes(),
            bbox=json.dumps(bbox),
            crop_path=crop_filename,
            det_score=str(det_score),
        )
        db.add(face_record)
        count += 1

    if count > 0:
        image.processed = 1
        db.commit()

    return count


def process_images(image_ids: list[int] | None, db: Session, *, user_id: int) -> dict:
    """Process multiple images. If image_ids is None, process all unprocessed for this user."""
    if image_ids:
        images = db.query(Image).filter(Image.id.in_(image_ids), Image.user_id == user_id).all()
    else:
        images = db.query(Image).filter(Image.processed == 0, Image.user_id == user_id).all()

    total_faces = 0
    processed_count = 0
    for img in images:
        n = process_image(img, db)
        total_faces += n
        processed_count += 1

    return {
        "images_processed": processed_count,
        "faces_detected": total_faces,
    }
