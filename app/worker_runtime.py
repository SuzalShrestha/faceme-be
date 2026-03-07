from __future__ import annotations

import logging
import threading

from app.config import WORKER_POLL_INTERVAL_SECONDS
from app.database import SessionLocal
from app.services.face_engine import warm_face_engine
from app.services.pipeline import run_pipeline_job
from app.services.queue import QueueMessage, get_queue_service
from app.services.storage import get_storage_service

log = logging.getLogger(__name__)


class WorkerRuntime:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        get_storage_service().readiness_check()
        get_queue_service().readiness_check()
        warm_face_engine()
        self._ready = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        queue = get_queue_service()
        while not self._stop.is_set():
            db = SessionLocal()
            message: QueueMessage | None = None
            try:
                message = queue.receive(db)
            finally:
                db.close()

            if message is None:
                self._stop.wait(WORKER_POLL_INTERVAL_SECONDS)
                continue

            try:
                run_pipeline_job(message.job_id)
                queue.ack(message)
            except Exception:
                log.exception("Worker failed job %s", message.job_id)
                queue.reject(message)


worker_runtime = WorkerRuntime()
