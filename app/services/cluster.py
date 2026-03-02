from __future__ import annotations

import numpy as np
from sklearn.cluster import DBSCAN
from sqlalchemy.orm import Session

from app.models import Cluster, Face, Image


def run_clustering(db: Session, *, user_id: int) -> dict:
    """Run DBSCAN clustering on all face embeddings for a specific user.

    Returns a summary dict with cluster counts.
    """
    user_image_ids = [img.id for img in db.query(Image).filter(Image.user_id == user_id).all()]
    faces = db.query(Face).filter(Face.image_id.in_(user_image_ids)).all()
    
    if not faces:
        return {"total_clusters": 0, "clustered_faces": 0, "ungrouped_faces": 0}

    embeddings = np.array(
        [np.frombuffer(f.embedding, dtype=np.float32) for f in faces]
    )

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
    for label_val in sorted(unique_labels):
        cluster = Cluster(user_id=user_id, label=f"Person {label_val + 1}")
        db.add(cluster)
        db.flush()
        cluster_map[label_val] = cluster

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

    db.commit()

    n_noise = int(np.sum(labels == -1))
    return {
        "total_clusters": len(cluster_map),
        "clustered_faces": len(faces) - n_noise,
        "ungrouped_faces": n_noise,
    }
