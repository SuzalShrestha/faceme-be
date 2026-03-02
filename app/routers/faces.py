from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Cluster, Face, Image, User
from app.services.face_engine import process_images
from app.services.cluster import run_clustering
from app.auth import get_current_user

router = APIRouter(tags=["faces"])


class ProcessRequest(BaseModel):
    image_ids: Optional[list[int]] = None


@router.post("/process")
def process_faces(body: ProcessRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    result = process_images(body.image_ids, db, user_id=user.id)
    return result


@router.post("/cluster")
def cluster_faces(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    result = run_clustering(db, user_id=user.id)
    return result


@router.get("/clusters")
def list_clusters(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    clusters = db.query(Cluster).filter(Cluster.user_id == user.id).all()
    result = []
    for c in clusters:
        face_count = db.query(Face).filter(Face.cluster_id == c.id).count()
        rep_face = (
            db.query(Face).filter(Face.id == c.representative_face_id).first()
            if c.representative_face_id
            else None
        )
        result.append(
            {
                "id": c.id,
                "label": c.label,
                "face_count": face_count,
                "representative_crop": rep_face.crop_path if rep_face else None,
            }
        )
    return result


@router.get("/clusters/{cluster_id}")
def get_cluster_detail(cluster_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id, Cluster.user_id == user.id).first()
    if not cluster:
        raise HTTPException(404, "Cluster not found")

    faces = db.query(Face).filter(Face.cluster_id == cluster_id).all()
    image_ids = list({f.image_id for f in faces})
    images = db.query(Image).filter(Image.id.in_(image_ids)).all()

    return {
        "id": cluster.id,
        "label": cluster.label,
        "faces": [
            {
                "id": f.id,
                "crop_path": f.crop_path,
                "bbox": f.get_bbox(),
                "image_id": f.image_id,
            }
            for f in faces
        ],
        "images": [
            {
                "id": img.id,
                "filename": img.filename,
                "original_name": img.original_name,
            }
            for img in images
        ],
    }


class RenameRequest(BaseModel):
    label: str


@router.patch("/clusters/{cluster_id}")
def rename_cluster(
    cluster_id: int, body: RenameRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id, Cluster.user_id == user.id).first()
    if not cluster:
        raise HTTPException(404, "Cluster not found")
    cluster.label = body.label
    db.commit()
    return {"id": cluster.id, "label": cluster.label}


@router.get("/ungrouped")
def list_ungrouped_faces(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    user_image_ids = [img.id for img in db.query(Image).filter(Image.user_id == user.id).all()]
    faces = db.query(Face).filter(Face.cluster_id.is_(None), Face.image_id.in_(user_image_ids)).all()
    return [
        {
            "id": f.id,
            "crop_path": f.crop_path,
            "bbox": f.get_bbox(),
            "image_id": f.image_id,
            "image_filename": f.image.filename,
        }
        for f in faces
    ]


class MergeRequest(BaseModel):
    source_cluster_id: int
    target_cluster_id: int


@router.post("/clusters/merge")
def merge_clusters(body: MergeRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    source = db.query(Cluster).filter(Cluster.id == body.source_cluster_id, Cluster.user_id == user.id).first()
    target = db.query(Cluster).filter(Cluster.id == body.target_cluster_id, Cluster.user_id == user.id).first()
    if not source or not target:
        raise HTTPException(404, "One or both clusters not found")
    if source.id == target.id:
        raise HTTPException(400, "Cannot merge a cluster with itself")

    db.query(Face).filter(Face.cluster_id == source.id).update(
        {Face.cluster_id: target.id}
    )
    db.delete(source)
    db.commit()
    return {"message": f"Merged cluster {body.source_cluster_id} into {body.target_cluster_id}"}
