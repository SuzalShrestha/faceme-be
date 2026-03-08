from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

TEST_ROOT = Path(tempfile.mkdtemp(prefix="faceme-cluster-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_ROOT / 'test.db'}"
os.environ["STORAGE_PROVIDER"] = "local"
os.environ["QUEUE_PROVIDER"] = "database"
os.environ["LOCAL_STORAGE_ROOT"] = str(TEST_ROOT / "storage")
os.environ["SESSION_COOKIE_SECURE"] = "false"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import Cluster, Face, Image, User  # noqa: E402
from app.services.cluster import run_clustering  # noqa: E402
from app.services.storage import get_storage_service  # noqa: E402


def embedding_bytes(values: list[float]) -> bytes:
    vector = np.zeros(512, dtype=np.float32)
    vector[: len(values)] = np.array(values, dtype=np.float32)
    norm = np.linalg.norm(vector)
    if norm > 0:
        vector /= norm
    return vector.tobytes()


class ClusterServiceTest(unittest.TestCase):
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
        self.db = SessionLocal()

        user = User(email="cluster@test.dev", name="Cluster Test", hashed_password="hashed")
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        self.user = user

    def tearDown(self) -> None:
        self.db.close()

    def add_image_with_face(self, name: str, values: list[float], *, det_score: str = "0.99") -> Face:
        image = Image(
            user_id=self.user.id,
            storage_key=f"uploads/{name}",
            original_name=name,
            content_type="image/jpeg",
            size_bytes=123,
            source="upload",
            status="processed",
        )
        self.db.add(image)
        self.db.flush()

        face = Face(
            image_id=image.id,
            embedding=embedding_bytes(values),
            bbox="[0, 0, 32, 32]",
            crop_key=f"faces/{name}.jpg",
            det_score=det_score,
        )
        self.db.add(face)
        self.db.commit()
        self.db.refresh(face)
        return face

    def test_single_face_creates_gallery_cluster(self) -> None:
        face = self.add_image_with_face("solo.jpg", [1.0, 0.0])

        result = run_clustering(self.db, storage=get_storage_service(), user_id=self.user.id)

        self.assertEqual(result["total_clusters"], 1)
        self.assertEqual(result["clustered_faces"], 1)
        self.assertEqual(result["ungrouped_faces"], 0)

        cluster = self.db.query(Cluster).filter(Cluster.user_id == self.user.id).one()
        self.db.refresh(face)
        self.assertEqual(face.cluster_id, cluster.id)
        self.assertEqual(cluster.representative_face_id, face.id)

    def test_single_new_face_still_gets_clustered_alongside_existing_pair(self) -> None:
        face_a = self.add_image_with_face("pair-a.jpg", [1.0, 0.0], det_score="0.90")
        face_b = self.add_image_with_face("pair-b.jpg", [0.99, 0.01], det_score="0.95")
        lone_face = self.add_image_with_face("solo.jpg", [0.0, 1.0], det_score="0.99")

        result = run_clustering(self.db, storage=get_storage_service(), user_id=self.user.id)

        self.assertEqual(result["total_clusters"], 2)
        self.assertEqual(result["clustered_faces"], 3)
        self.assertEqual(result["ungrouped_faces"], 0)

        clusters = self.db.query(Cluster).filter(Cluster.user_id == self.user.id).all()
        face_counts = sorted(
            self.db.query(Face).filter(Face.cluster_id == cluster.id).count() for cluster in clusters
        )
        self.assertEqual(face_counts, [1, 2])

        for face in (face_a, face_b, lone_face):
            self.db.refresh(face)
            self.assertIsNotNone(face.cluster_id)

        singleton_cluster = next(
            cluster
            for cluster in clusters
            if self.db.query(Face).filter(Face.cluster_id == cluster.id).count() == 1
        )
        self.assertEqual(singleton_cluster.representative_face_id, lone_face.id)


if __name__ == "__main__":
    unittest.main()
