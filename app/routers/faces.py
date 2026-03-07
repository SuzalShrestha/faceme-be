from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Cluster, Face, Image, User
from app.services.storage import get_storage_service

router = APIRouter(tags=["faces"])


class RenameRequest(BaseModel):
    label: str


class MergeRequest(BaseModel):
    source_cluster_id: int
    target_cluster_id: int


@router.get("/clusters")
def list_clusters(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    storage = get_storage_service()
    clusters = db.query(Cluster).filter(Cluster.user_id == user.id).order_by(Cluster.created_at.desc()).all()
    result = []
    for cluster in clusters:
        face_count = db.query(Face).filter(Face.cluster_id == cluster.id).count()
        representative_face = (
            db.query(Face).filter(Face.id == cluster.representative_face_id).first()
            if cluster.representative_face_id
            else None
        )
        result.append(
            {
                "id": cluster.id,
                "label": cluster.label,
                "face_count": face_count,
                "representative_url": (
                    storage.build_asset_url("faces", representative_face.crop_key)
                    if representative_face
                    else None
                ),
            }
        )
    return result


@router.get("/clusters/{cluster_id}")
def get_cluster_detail(cluster_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    storage = get_storage_service()
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id, Cluster.user_id == user.id).first()
    if not cluster:
        raise HTTPException(404, "Cluster not found")

    faces = db.query(Face).filter(Face.cluster_id == cluster_id).all()
    image_ids = list({face.image_id for face in faces})
    images = db.query(Image).filter(Image.id.in_(image_ids)).all() if image_ids else []

    return {
        "id": cluster.id,
        "label": cluster.label,
        "faces": [
            {
                "id": face.id,
                "asset_url": storage.build_asset_url("faces", face.crop_key),
                "bbox": face.get_bbox(),
                "image_id": face.image_id,
            }
            for face in faces
        ],
        "images": [
            {
                "id": image.id,
                "asset_url": storage.build_asset_url("uploads", image.storage_key),
                "original_name": image.original_name,
            }
            for image in images
        ],
    }


@router.patch("/clusters/{cluster_id}")
def rename_cluster(
    cluster_id: int,
    body: RenameRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id, Cluster.user_id == user.id).first()
    if not cluster:
        raise HTTPException(404, "Cluster not found")
    cluster.label = body.label
    db.commit()
    return {"id": cluster.id, "label": cluster.label}


@router.get("/ungrouped")
def list_ungrouped_faces(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    storage = get_storage_service()
    user_image_ids = [image.id for image in db.query(Image).filter(Image.user_id == user.id).all()]
    faces = db.query(Face).filter(Face.cluster_id.is_(None), Face.image_id.in_(user_image_ids)).all()
    return [
        {
            "id": face.id,
            "asset_url": storage.build_asset_url("faces", face.crop_key),
            "bbox": face.get_bbox(),
            "image_id": face.image_id,
            "image_name": face.image.original_name,
        }
        for face in faces
    ]


@router.post("/clusters/merge")
def merge_clusters(body: MergeRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    source = db.query(Cluster).filter(Cluster.id == body.source_cluster_id, Cluster.user_id == user.id).first()
    target = db.query(Cluster).filter(Cluster.id == body.target_cluster_id, Cluster.user_id == user.id).first()
    if not source or not target:
        raise HTTPException(404, "One or both clusters not found")
    if source.id == target.id:
        raise HTTPException(400, "Cannot merge a cluster with itself")

    db.query(Face).filter(Face.cluster_id == source.id).update({Face.cluster_id: target.id})
    db.delete(source)
    db.commit()
    return {"message": f"Merged cluster {body.source_cluster_id} into {body.target_cluster_id}"}
