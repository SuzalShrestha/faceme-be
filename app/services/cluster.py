from __future__ import annotations

import numpy as np
from sklearn.cluster import DBSCAN
from sqlalchemy.orm import Session

from app.models import Cluster, Face, Image
from app.services.storage import StorageService


def _create_singleton_cluster(
    db: Session,
    *,
    user_id: int,
    face: Face,
    label_index: int,
) -> Cluster:
    cluster = Cluster(user_id=user_id, label=f"Person {label_index}")
    db.add(cluster)
    db.flush()
    face.cluster_id = cluster.id
    cluster.representative_face_id = face.id
    return cluster


def ensure_singleton_clusters(db: Session, *, user_id: int) -> int:
    user_image_ids = [img.id for img in db.query(Image).filter(Image.user_id == user_id).all()]
    if not user_image_ids:
        return 0

    ungrouped_faces = (
        db.query(Face)
        .filter(Face.cluster_id.is_(None), Face.image_id.in_(user_image_ids))
        .order_by(Face.id.asc())
        .all()
    )
    if not ungrouped_faces:
        return 0

    next_label_index = db.query(Cluster).filter(Cluster.user_id == user_id).count() + 1
    for face in ungrouped_faces:
        _create_singleton_cluster(
            db,
            user_id=user_id,
            face=face,
            label_index=next_label_index,
        )
        next_label_index += 1

    db.commit()
    return len(ungrouped_faces)


def run_clustering(db: Session, storage: StorageService, *, user_id: int) -> dict:
    """Run DBSCAN clustering on all face embeddings for a specific user.

    Returns a summary dict with cluster counts.
    """
    user_image_ids = [img.id for img in db.query(Image).filter(Image.user_id == user_id).all()]
    faces = db.query(Face).filter(Face.image_id.in_(user_image_ids)).all()

    if not faces:
        return {"total_clusters": 0, "clustered_faces": 0, "ungrouped_faces": 0}

    # Clear face → cluster references first, then delete clusters
    for f in faces:
        f.cluster_id = None
    db.flush()
    db.query(Cluster).filter(Cluster.user_id == user_id).delete()
    db.flush()

    if len(faces) == 1:
        _create_singleton_cluster(db, user_id=user_id, face=faces[0], label_index=1)
        db.commit()
        return {"total_clusters": 1, "clustered_faces": 1, "ungrouped_faces": 0}

    embeddings = np.array([np.frombuffer(f.embedding, dtype=np.float32) for f in faces])
    clustering = DBSCAN(eps=0.5, min_samples=2, metric="cosine").fit(embeddings)
    labels = clustering.labels_

    unique_labels = set(labels)
    unique_labels.discard(-1)

    clustered_groups: dict[int, Cluster] = {}
    for label_val in sorted(unique_labels):
        cluster = Cluster(user_id=user_id, label=f"Person {label_val + 1}")
        db.add(cluster)
        db.flush()
        clustered_groups[label_val] = cluster

    singleton_label_index = len(unique_labels) + 1
    singleton_count = 0
    for face, label_val in zip(faces, labels):
        if label_val == -1:
            _create_singleton_cluster(
                db,
                user_id=user_id,
                face=face,
                label_index=singleton_label_index,
            )
            singleton_label_index += 1
            singleton_count += 1
        else:
            face.cluster_id = clustered_groups[label_val].id

    for label_val, cluster in clustered_groups.items():
        cluster_faces = [f for f, l in zip(faces, labels) if l == label_val]
        best = max(
            cluster_faces,
            key=lambda f: float(f.det_score or 0),
        )
        cluster.representative_face_id = best.id

    db.commit()

    return {
        "total_clusters": len(clustered_groups) + singleton_count,
        "clustered_faces": len(faces),
        "ungrouped_faces": 0,
    }
