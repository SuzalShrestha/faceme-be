from __future__ import annotations

import threading
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.jobs import JobStatus, create_job, get_job, update_job
from app.services.face_engine import process_images
from app.services.cluster import run_clustering
from app.models import User
from app.auth import get_current_user

router = APIRouter(tags=["jobs"])


class PipelineRequest(BaseModel):
    image_ids: Optional[list[int]] = None


def _run_pipeline(job_id: str, image_ids: list[int] | None, user_id: int):
    db = SessionLocal()
    try:
        update_job(job_id, status=JobStatus.RUNNING, progress=10, message="Detecting faces...")
        proc = process_images(image_ids, db, user_id=user_id)

        update_job(job_id, progress=60, message="Clustering faces...")
        cluster = run_clustering(db, user_id=user_id)

        update_job(
            job_id,
            status=JobStatus.COMPLETED,
            progress=100,
            message="Done",
            result={**proc, **cluster},
        )
    except Exception as e:
        update_job(
            job_id,
            status=JobStatus.FAILED,
            message=str(e),
        )
    finally:
        db.close()


@router.post("/pipeline")
def start_pipeline(body: PipelineRequest, user: User = Depends(get_current_user)):
    job = create_job()
    t = threading.Thread(target=_run_pipeline, args=(job.id, body.image_ids, user.id), daemon=True)
    t.start()
    return {"job_id": job.id}


@router.get("/jobs/{job_id}")
def get_job_status(job_id: str, user: User = Depends(get_current_user)):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job.to_dict()
