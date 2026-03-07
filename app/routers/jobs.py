from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import PipelineJob, User
from app.services.pipeline import create_pipeline_job, serialize_job
from app.services.queue import get_queue_service

router = APIRouter(tags=["jobs"])


class PipelineRequest(BaseModel):
    image_ids: Optional[list[int]] = None


@router.post("/pipeline")
def start_pipeline(
    body: PipelineRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = create_pipeline_job(db, user_id=user.id, image_ids=body.image_ids)
    try:
        get_queue_service().enqueue(job.id)
    except Exception as exc:
        job.status = "failed"
        job.message = "Failed to enqueue job"
        job.error_text = str(exc)
        db.commit()
        raise HTTPException(500, "Failed to enqueue pipeline job") from exc
    return {"job_id": job.id}


@router.get("/jobs/{job_id}")
def get_job_status(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = (
        db.query(PipelineJob)
        .filter(PipelineJob.id == job_id, PipelineJob.user_id == user.id)
        .first()
    )
    if not job:
        raise HTTPException(404, "Job not found")
    return serialize_job(job)
