import json
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, LargeBinary, Text, Boolean,
)
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    images = relationship("Image", back_populates="user", cascade="all, delete-orphan")
    clusters = relationship("Cluster", back_populates="user", cascade="all, delete-orphan")


class Image(Base):
    __tablename__ = "images"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    filename = Column(String, unique=True, nullable=False)
    original_name = Column(String, nullable=False)
    source = Column(String, nullable=False, default="upload")
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    processed = Column(Integer, default=0)

    user = relationship("User", back_populates="images")
    faces = relationship("Face", back_populates="image", cascade="all, delete-orphan")


class Cluster(Base):
    __tablename__ = "clusters"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    label = Column(String, nullable=True)
    representative_face_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="clusters")
    faces = relationship("Face", back_populates="cluster")


class Face(Base):
    __tablename__ = "faces"

    id = Column(Integer, primary_key=True, index=True)
    image_id = Column(Integer, ForeignKey("images.id"), nullable=False)
    embedding = Column(LargeBinary, nullable=False)
    bbox = Column(Text, nullable=False)
    crop_path = Column(String, nullable=False)
    det_score = Column(String, nullable=True)
    cluster_id = Column(Integer, ForeignKey("clusters.id"), nullable=True)

    image = relationship("Image", back_populates="faces")
    cluster = relationship("Cluster", back_populates="faces")

    def get_bbox(self) -> list:
        return json.loads(self.bbox)

    def set_bbox(self, bbox_list: list):
        self.bbox = json.dumps(bbox_list)
