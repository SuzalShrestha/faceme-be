from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)

    images = relationship("Image", back_populates="user", cascade="all, delete-orphan")
    clusters = relationship("Cluster", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("SessionToken", back_populates="user", cascade="all, delete-orphan")
    jobs = relationship("PipelineJob", back_populates="user", cascade="all, delete-orphan")


class Image(Base):
    __tablename__ = "images"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    storage_key = Column(String, unique=True, nullable=False)
    original_name = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    source = Column(String, nullable=False, default="upload")
    status = Column(String, nullable=False, default="uploaded")
    processing_error = Column(Text, nullable=True)
    uploaded_at = Column(DateTime, default=utcnow)
    processed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="images")
    faces = relationship("Face", back_populates="image", cascade="all, delete-orphan")


class Cluster(Base):
    __tablename__ = "clusters"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    label = Column(String, nullable=True)
    representative_face_id = Column(
        Integer,
        ForeignKey(
            "faces.id",
            use_alter=True,
            name="fk_clusters_representative_face_id_faces",
        ),
        nullable=True,
    )
    created_at = Column(DateTime, default=utcnow)

    user = relationship("User", back_populates="clusters")
    faces = relationship("Face", back_populates="cluster", foreign_keys="Face.cluster_id")


class Face(Base):
    __tablename__ = "faces"

    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(Integer, ForeignKey("images.id"), nullable=False)
    embedding = Column(LargeBinary, nullable=False)
    bbox = Column(Text, nullable=False)
    crop_key = Column(String, nullable=False)
    det_score = Column(String, nullable=True)
    cluster_id = Column(Integer, ForeignKey("clusters.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    image = relationship("Image", back_populates="faces")
    cluster = relationship("Cluster", back_populates="faces", foreign_keys=[cluster_id])

    def get_bbox(self) -> list:
        return json.loads(self.bbox)

    def set_bbox(self, bbox_list: list):
        self.bbox = json.dumps(bbox_list)


class SessionToken(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    last_seen_at = Column(DateTime, default=utcnow)

    user = relationship("User", back_populates="sessions")


class PipelineJob(Base):
    __tablename__ = "pipeline_jobs"

    id = Column(String, primary_key=True, default=lambda: uuid.uuid4().hex[:12])
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String, nullable=False, default="queued")
    progress = Column(Integer, nullable=False, default=0)
    message = Column(String, nullable=False, default="")
    payload_json = Column(Text, nullable=False, default="{}")
    result_json = Column(Text, nullable=False, default="{}")
    error_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="jobs")

    def get_payload(self) -> dict:
        return json.loads(self.payload_json or "{}")

    def set_payload(self, payload: dict) -> None:
        self.payload_json = json.dumps(payload or {})

    def get_result(self) -> dict:
        return json.loads(self.result_json or "{}")

    def set_result(self, payload: dict) -> None:
        self.result_json = json.dumps(payload or {})
