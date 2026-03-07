from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import PipelineJob
from app.services.cluster import run_clustering
from app.services.face_engine import process_images
from app.services.storage import get_storage_service

log = logging.getLogger(__name__)


def create_pipeline_job(db: Session, *, user_id: int, image_ids: list[int] | None) -> PipelineJob:
    job = PipelineJob(
        id=uuid.uuid4().hex[:12],
        user_id=user_id,
        status="queued",
        progress=0,
        message="Queued",
        payload_json=json.dumps({"image_ids": image_ids}),
        result_json="{}",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def serialize_job(job: PipelineJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "result": job.get_result(),
        "error": job.error_text,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


def run_pipeline_job(job_id: str) -> bool:
    storage = get_storage_service()
    db = SessionLocal()
    try:
        job = db.query(PipelineJob).filter(PipelineJob.id == job_id).first()
        if job is None:
            log.warning("Skipping missing job %s", job_id)
            return False
        if job.status == "completed":
            return False

        job.status = "running"
        job.progress = max(job.progress, 10)
        job.message = "Detecting faces..."
        job.error_text = None
        job.started_at = job.started_at or datetime.now(timezone.utc)
        db.commit()

        process_result = process_images(
            image_ids=job.get_payload().get("image_ids"),
            db=db,
            storage=storage,
            user_id=job.user_id,
        )

        job.progress = 75
        job.message = "Clustering faces..."
        db.commit()

        cluster_result = run_clustering(db, storage=storage, user_id=job.user_id)

        job.status = "completed"
        job.progress = 100
        job.message = "Done"
        job.set_result({**process_result, **cluster_result})
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        return True
    except Exception as exc:
        log.exception("Pipeline job %s failed", job_id)
        job = db.query(PipelineJob).filter(PipelineJob.id == job_id).first()
        if job is not None:
            job.status = "failed"
            job.message = str(exc)
            job.error_text = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
        return False
    finally:
        db.close()
