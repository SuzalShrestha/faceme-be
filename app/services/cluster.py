from __future__ import annotations

import numpy as np
from sklearn.cluster import DBSCAN
from sqlalchemy.orm import Session

from app.models import Cluster, Face, Image
from app.services.storage import StorageService


def run_clustering(db: Session, storage: StorageService, *, user_id: int) -> dict:
    """Run DBSCAN clustering on all face embeddings for a specific user.

    Returns a summary dict with cluster counts.
    """
    user_image_ids = [img.id for img in db.query(Image).filter(Image.user_id == user_id).all()]
    faces = db.query(Face).filter(Face.image_id.in_(user_image_ids)).all()
    
    if not faces:
        return {"total_clusters": 0, "clustered_faces": 0, "ungrouped_faces": 0}

    embeddings = np.array([np.frombuffer(f.embedding, dtype=np.float32) for f in faces])

    clustering = DBSCAN(eps=0.5, min_samples=2, metric="cosine").fit(embeddings)
    labels = clustering.labels_

    # Clear face → cluster references first, then delete clusters
    for f in faces:
        f.cluster_id = None
    db.flush()
    db.query(Cluster).filter(Cluster.user_id == user_id).delete()
    db.flush()

    unique_labels = set(labels)
    unique_labels.discard(-1)

    cluster_map: dict[int, Cluster] = {}
    next_label = 1
    for label_val in sorted(unique_labels):
        cluster = Cluster(user_id=user_id, label=f"Person {next_label}")
        db.add(cluster)
        db.flush()
        cluster_map[label_val] = cluster
        next_label += 1

    for face, label_val in zip(faces, labels):
        if label_val == -1:
            continue
        face.cluster_id = cluster_map[label_val].id

    for label_val, cluster in cluster_map.items():
        cluster_faces = [
            f for f, l in zip(faces, labels) if l == label_val
        ]
        best = max(
            cluster_faces,
            key=lambda f: float(f.det_score or 0),
        )
        cluster.representative_face_id = best.id

    for face in faces:
        if face.cluster_id is None:
            cluster = Cluster(user_id=user_id, label=f"Person {next_label}")
            db.add(cluster)
            db.flush()
            face.cluster_id = cluster.id
            cluster.representative_face_id = face.id
            next_label += 1

    db.commit()

    return {
        "total_clusters": next_label - 1,
        "clustered_faces": len(faces),
        "ungrouped_faces": 0,
    }
