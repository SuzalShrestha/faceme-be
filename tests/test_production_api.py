from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

TEST_ROOT = Path(tempfile.mkdtemp(prefix="faceme-backend-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_ROOT / 'test.db'}"
os.environ["STORAGE_PROVIDER"] = "local"
os.environ["QUEUE_PROVIDER"] = "database"
os.environ["LOCAL_STORAGE_ROOT"] = str(TEST_ROOT / "storage")
os.environ["SESSION_COOKIE_SECURE"] = "false"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Cluster, Face, Image  # noqa: E402
from app.services.pipeline import run_pipeline_job  # noqa: E402
from app.services.storage import get_storage_service  # noqa: E402


def fake_process_images(image_ids, db, storage, *, user_id):
    images = db.query(Image).filter(Image.user_id == user_id).all()
    image_lookup = {image.id: image for image in images}
    selected = [image_lookup[image_id] for image_id in (image_ids or list(image_lookup)) if image_id in image_lookup]
    if not selected:
        return {"images_processed": 0, "images_failed": 0, "faces_detected": 0}

    total_faces = 0
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
        total_faces += 1
    db.commit()
    return {
        "images_processed": len(selected),
        "images_failed": 0,
        "faces_detected": total_faces,
    }


def fake_run_clustering(db, storage, *, user_id):
    existing = db.query(Cluster).filter(Cluster.user_id == user_id).all()
    for cluster in existing:
        db.delete(cluster)
    db.flush()

    faces = (
        db.query(Face)
        .join(Image, Face.image_id == Image.id)
        .filter(Image.user_id == user_id)
        .all()
    )
    if not faces:
        return {"total_clusters": 0, "clustered_faces": 0, "ungrouped_faces": 0}

    cluster = Cluster(user_id=user_id, label="Person 1")
    db.add(cluster)
    db.flush()
    for face in faces:
        face.cluster_id = cluster.id
    cluster.representative_face_id = faces[0].id
    db.commit()
    return {"total_clusters": 1, "clustered_faces": len(faces), "ungrouped_faces": 0}


def fake_run_clustering_leaves_ungrouped(db, storage, *, user_id):
    faces = (
        db.query(Face)
        .join(Image, Face.image_id == Image.id)
        .filter(Image.user_id == user_id)
        .all()
    )
    for face in faces:
        face.cluster_id = None
    db.commit()
    return {"total_clusters": 0, "clustered_faces": 0, "ungrouped_faces": len(faces)}


class ProductionApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(TEST_ROOT, ignore_errors=True)

    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        shutil.rmtree(TEST_ROOT / "storage", ignore_errors=True)
        get_storage_service().readiness_check()
        self.client = TestClient(app)

    def register_user(self) -> None:
        response = self.client.post(
            "/api/auth/register",
            json={"email": "test@example.com", "name": "Test User", "password": "password123"},
        )
        self.assertEqual(response.status_code, 201)

    def test_cookie_auth_lifecycle(self) -> None:
        self.register_user()

        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["email"], "test@example.com")

        logout = self.client.post("/api/auth/logout")
        self.assertEqual(logout.status_code, 204)

        me_after_logout = self.client.get("/api/auth/me")
        self.assertEqual(me_after_logout.status_code, 401)

    def test_upload_pipeline_and_asset_flow(self) -> None:
        self.register_user()

        initiate = self.client.post(
            "/api/uploads/initiate",
            json={
                "files": [
                    {
                        "name": "family.jpg",
                        "size": 12,
                        "content_type": "image/jpeg",
                    }
                ]
            },
        )
        self.assertEqual(initiate.status_code, 200)
        target = initiate.json()["files"][0]

        upload = self.client.put(
            target["upload_url"],
            content=b"fake-image",
            headers={"Content-Type": "image/jpeg"},
        )
        self.assertEqual(upload.status_code, 200)

        complete = self.client.post(
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
        self.assertEqual(complete.status_code, 200)
        image_id = complete.json()["image_ids"][0]

        images = self.client.get("/api/images")
        self.assertEqual(images.status_code, 200)
        image = images.json()[0]
        asset = self.client.get(image["asset_url"])
        self.assertEqual(asset.status_code, 200)
        self.assertEqual(asset.content, b"fake-image")

        pipeline = self.client.post("/api/pipeline", json={"image_ids": [image_id]})
        self.assertEqual(pipeline.status_code, 200)
        job_id = pipeline.json()["job_id"]

        with patch("app.services.pipeline.process_images", side_effect=fake_process_images), patch(
            "app.services.pipeline.run_clustering",
            side_effect=fake_run_clustering,
        ):
            self.assertTrue(run_pipeline_job(job_id))

        job = self.client.get(f"/api/jobs/{job_id}")
        self.assertEqual(job.status_code, 200)
        self.assertEqual(job.json()["status"], "completed")

        clusters = self.client.get("/api/clusters")
        self.assertEqual(clusters.status_code, 200)
        cluster = clusters.json()[0]
        self.assertEqual(cluster["face_count"], 1)
        self.assertTrue(cluster["representative_url"])

        rename = self.client.patch(
            f"/api/clusters/{cluster['id']}",
            json={"label": "Renamed Person"},
        )
        self.assertEqual(rename.status_code, 200)
        self.assertEqual(rename.json()["label"], "Renamed Person")

    def test_single_face_pipeline_appears_in_clusters_with_real_clustering(self) -> None:
        self.register_user()

        initiate = self.client.post(
            "/api/uploads/initiate",
            json={
                "files": [
                    {
                        "name": "solo.jpg",
                        "size": 12,
                        "content_type": "image/jpeg",
                    }
                ]
            },
        )
        self.assertEqual(initiate.status_code, 200)
        target = initiate.json()["files"][0]

        upload = self.client.put(
            target["upload_url"],
            content=b"fake-image",
            headers={"Content-Type": "image/jpeg"},
        )
        self.assertEqual(upload.status_code, 200)

        complete = self.client.post(
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
        self.assertEqual(complete.status_code, 200)
        image_id = complete.json()["image_ids"][0]

        pipeline = self.client.post("/api/pipeline", json={"image_ids": [image_id]})
        self.assertEqual(pipeline.status_code, 200)
        job_id = pipeline.json()["job_id"]

        with patch("app.services.pipeline.process_images", side_effect=fake_process_images):
            self.assertTrue(run_pipeline_job(job_id))

        clusters = self.client.get("/api/clusters")
        self.assertEqual(clusters.status_code, 200)
        payload = clusters.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["face_count"], 1)
        self.assertTrue(payload[0]["representative_url"])

    def test_clusters_endpoint_repairs_single_ungrouped_face(self) -> None:
        self.register_user()

        initiate = self.client.post(
            "/api/uploads/initiate",
            json={
                "files": [
                    {
                        "name": "repair-me.jpg",
                        "size": 12,
                        "content_type": "image/jpeg",
                    }
                ]
            },
        )
        self.assertEqual(initiate.status_code, 200)
        target = initiate.json()["files"][0]

        upload = self.client.put(
            target["upload_url"],
            content=b"fake-image",
            headers={"Content-Type": "image/jpeg"},
        )
        self.assertEqual(upload.status_code, 200)

        complete = self.client.post(
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
        self.assertEqual(complete.status_code, 200)
        image_id = complete.json()["image_ids"][0]

        pipeline = self.client.post("/api/pipeline", json={"image_ids": [image_id]})
        self.assertEqual(pipeline.status_code, 200)
        job_id = pipeline.json()["job_id"]

        with patch("app.services.pipeline.process_images", side_effect=fake_process_images), patch(
            "app.services.pipeline.run_clustering",
            side_effect=fake_run_clustering_leaves_ungrouped,
        ):
            self.assertTrue(run_pipeline_job(job_id))

        ungrouped_before = self.client.get("/api/ungrouped")
        self.assertEqual(ungrouped_before.status_code, 200)
        self.assertEqual(ungrouped_before.json(), [])

        clusters = self.client.get("/api/clusters")
        self.assertEqual(clusters.status_code, 200)
        payload = clusters.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["face_count"], 1)
        self.assertTrue(payload[0]["representative_url"])


if __name__ == "__main__":
    unittest.main()
