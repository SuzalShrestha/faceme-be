from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy.orm import Session

from app.config import (
    AZURE_QUEUE_ACCOUNT_URL,
    AZURE_QUEUE_CONNECTION_STRING,
    AZURE_QUEUE_NAME,
    QUEUE_PROVIDER,
    QUEUE_VISIBILITY_TIMEOUT,
)
from app.models import PipelineJob


@dataclass
class QueueMessage:
    job_id: str
    message_id: str | None = None
    pop_receipt: str | None = None


class QueueService:
    def enqueue(self, job_id: str) -> None:
        raise NotImplementedError

    def receive(self, db: Session | None = None) -> QueueMessage | None:
        raise NotImplementedError

    def ack(self, message: QueueMessage) -> None:
        raise NotImplementedError

    def reject(self, message: QueueMessage) -> None:
        raise NotImplementedError

    def readiness_check(self) -> None:
        raise NotImplementedError


class DatabaseQueueService(QueueService):
    def enqueue(self, job_id: str) -> None:
        return None

    def receive(self, db: Session | None = None) -> QueueMessage | None:
        if db is None:
            raise RuntimeError("Database queue requires a database session")

        job = (
            db.query(PipelineJob)
            .filter(PipelineJob.status == "queued")
            .order_by(PipelineJob.created_at.asc())
            .first()
        )
        if job is None:
            return None

        job.status = "running"
        job.started_at = job.started_at or datetime.now(timezone.utc)
        job.message = job.message or "Worker picked up job"
        db.commit()
        return QueueMessage(job_id=job.id)

    def ack(self, message: QueueMessage) -> None:
        return None

    def reject(self, message: QueueMessage) -> None:
        return None

    def readiness_check(self) -> None:
        return None


class AzureQueueService(QueueService):
    def __init__(self) -> None:
        from azure.identity import DefaultAzureCredential
        from azure.storage.queue import QueueClient

        if AZURE_QUEUE_CONNECTION_STRING:
            self.client = QueueClient.from_connection_string(
                conn_str=AZURE_QUEUE_CONNECTION_STRING,
                queue_name=AZURE_QUEUE_NAME,
            )
        elif AZURE_QUEUE_ACCOUNT_URL:
            self.client = QueueClient(
                account_url=AZURE_QUEUE_ACCOUNT_URL,
                queue_name=AZURE_QUEUE_NAME,
                credential=DefaultAzureCredential(),
            )
        else:
            raise RuntimeError("Azure queue configuration is missing")

    def enqueue(self, job_id: str) -> None:
        self.client.send_message(job_id)

    def receive(self, db: Session | None = None) -> QueueMessage | None:
        messages = list(
            self.client.receive_messages(
                messages_per_page=1,
                visibility_timeout=QUEUE_VISIBILITY_TIMEOUT,
            )
        )
        if not messages:
            return None

        message = messages[0]
        return QueueMessage(
            job_id=message.content,
            message_id=message.id,
            pop_receipt=message.pop_receipt,
        )

    def ack(self, message: QueueMessage) -> None:
        if message.message_id and message.pop_receipt:
            self.client.delete_message(message.message_id, message.pop_receipt)

    def reject(self, message: QueueMessage) -> None:
        return None

    def readiness_check(self) -> None:
        self.client.get_queue_properties()


@lru_cache(maxsize=1)
def get_queue_service() -> QueueService:
    if QUEUE_PROVIDER == "azure":
        return AzureQueueService()
    return DatabaseQueueService()
