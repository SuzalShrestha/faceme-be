from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

TEST_ROOT = Path(tempfile.mkdtemp(prefix="faceme-backend-smoke-"))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_ROOT / 'smoke.db'}"
os.environ["STORAGE_PROVIDER"] = "local"
os.environ["QUEUE_PROVIDER"] = "database"
os.environ["LOCAL_STORAGE_ROOT"] = str(TEST_ROOT / "storage")
os.environ["SESSION_COOKIE_SECURE"] = "false"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Cluster, Face, Image  # noqa: E402
from app.services.pipeline import run_pipeline_job  # noqa: E402
from app.services.storage import get_storage_service  # noqa: E402


def fake_process_images(image_ids, db, storage, *, user_id):
    images = db.query(Image).filter(Image.user_id == user_id).all()
    image_lookup = {image.id: image for image in images}
    selected = [image_lookup[image_id] for image_id in (image_ids or list(image_lookup)) if image_id in image_lookup]
    for image in selected:
        crop_key = storage.new_face_key(user_id=user_id)
        storage.upload_bytes("faces", crop_key, b"fake-face", "image/jpeg")
        db.add(
            Face(
                image_id=image.id,
                embedding=np.zeros(512, dtype=np.float32).tobytes(),
                bbox="[0, 0, 32, 32]",
                crop_key=crop_key,
                det_score="0.99",
            )
        )
        image.status = "processed"
    db.commit()
    return {"images_processed": len(selected), "images_failed": 0, "faces_detected": len(selected)}


def fake_run_clustering(db, storage, *, user_id):
    faces = (
        db.query(Face)
        .join(Image, Face.image_id == Image.id)
        .filter(Image.user_id == user_id)
        .all()
    )
    if not faces:
        return {"total_clusters": 0, "clustered_faces": 0, "ungrouped_faces": 0}

    cluster = Cluster(user_id=user_id, label="Smoke Cluster")
    db.add(cluster)
    db.flush()
    for face in faces:
        face.cluster_id = cluster.id
    cluster.representative_face_id = faces[0].id
    db.commit()
    return {"total_clusters": 1, "clustered_faces": len(faces), "ungrouped_faces": 0}


def main() -> None:
    try:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        get_storage_service().readiness_check()

        client = TestClient(app)
        register = client.post(
            "/api/auth/register",
            json={"email": "smoke@example.com", "name": "Smoke User", "password": "password123"},
        )
        assert register.status_code == 201, register.text

        initiate = client.post(
            "/api/uploads/initiate",
            json={
                "files": [
                    {
                        "name": "smoke.jpg",
                        "size": 10,
                        "content_type": "image/jpeg",
                    }
                ]
            },
        )
        assert initiate.status_code == 200, initiate.text
        target = initiate.json()["files"][0]

        upload = client.put(
            target["upload_url"],
            content=b"smoke-image",
            headers={"Content-Type": "image/jpeg"},
        )
        assert upload.status_code == 200, upload.text

        complete = client.post(
            "/api/uploads/complete",
            json={
                "files": [
                    {
                        "storage_key": target["storage_key"],
                        "original_name": target["original_name"],
                        "content_type": target["content_type"],
                        "size_bytes": target["size_bytes"],
                    }
                ]
            },
        )
        assert complete.status_code == 200, complete.text
        image_id = complete.json()["image_ids"][0]

        pipeline = client.post("/api/pipeline", json={"image_ids": [image_id]})
        assert pipeline.status_code == 200, pipeline.text
        job_id = pipeline.json()["job_id"]

        with patch("app.services.pipeline.process_images", side_effect=fake_process_images), patch(
            "app.services.pipeline.run_clustering",
            side_effect=fake_run_clustering,
        ):
            assert run_pipeline_job(job_id)

        job = client.get(f"/api/jobs/{job_id}")
        assert job.status_code == 200, job.text
        assert job.json()["status"] == "completed", job.json()

        clusters = client.get("/api/clusters")
        assert clusters.status_code == 200, clusters.text
        cluster = clusters.json()[0]

        rename = client.patch(
            f"/api/clusters/{cluster['id']}",
            json={"label": "Smoke Rename"},
        )
        assert rename.status_code == 200, rename.text
        assert rename.json()["label"] == "Smoke Rename", rename.json()

        print("smoke test passed")
    finally:
        shutil.rmtree(TEST_ROOT, ignore_errors=True)


if __name__ == "__main__":
    main()
